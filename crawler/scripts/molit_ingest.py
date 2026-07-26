"""
molit_ingest.py — 국토부 실거래가·건축물대장 → Supabase 적재 CLI.

서브커맨드:
    deals                실거래가 월 단위 수집 (molit_deals)
        --budget N           일일 API 호출 예산 (기본 900 — data.go.kr 1,000/일
                             한도에서 웹 프록시 몫을 남김)
        --backfill-months N  과거 백필 범위 (기본 24개월)
        --dry-run            수집 계획(잡 목록)만 출력
    building-register    건축물대장 표제부 — 활성 건물 매물당 1회 (property_building_register)
        --limit N            1회 처리 매물 수 (기본 500)
        --dry-run            후보 카운트만

증분 전략(deals):
    당월+전월은 수집 후 7일 지나면 재수집(거래 신고 지연 반영),
    과거 N개월은 fetch_log 에 없는 (유형, 시군구, 월) 조합을 오래된 순 drain.
    대상 시군구는 활성 매물이 있는 곳만, 유형은 그 지역 매물 용도에서 유도(+apt 상시).

환경변수 (.env): SUPABASE_URL, SUPABASE_SERVICE_KEY, DATA_GO_KR_API_KEY

실행:
    /Users/jaemoonyeah/workspace/venv_common/bin/python crawler/scripts/molit_ingest.py deals --budget 20 --dry-run
    .../python crawler/scripts/molit_ingest.py building-register --limit 10
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from molit import MolitClient, MolitError, MolitStore  # noqa: E402

logger = logging.getLogger(__name__)

STALE_DAYS = 7  # 당월+전월 재수집 주기


def _months_back(n: int) -> list[str]:
    """이번 달부터 n개월 전까지 YYYYMM 리스트 (최신 → 과거)."""
    out = []
    d = datetime.now(timezone.utc).replace(day=1)
    for _ in range(n + 1):
        out.append(d.strftime("%Y%m"))
        d = (d - timedelta(days=1)).replace(day=1)
    return out


def _start_run(store: MolitStore, job_type: str, params: dict) -> str:
    r = store.sb.table("crawl_runs").insert(
        {"job_type": job_type, "params": params, "status": "running"}
    ).execute()
    return r.data[0]["id"]


def _finish_run(store: MolitStore, run_id: str, totals: dict,
                *, status: str = "done", error: str | None = None) -> None:
    store.sb.table("crawl_runs").update(
        {"status": status, "totals": totals,
         "finished_at": datetime.now(timezone.utc).isoformat(), "error": error}
    ).eq("id", run_id).execute()


# ---------- deals ----------

def cmd_deals(args: argparse.Namespace) -> None:
    store = MolitStore()
    started = time.monotonic()

    region_types = store.active_region_types()
    try:
        log = store.fetch_log_map()
    except Exception as e:  # noqa: BLE001
        if "42P01" in str(e) or "does not exist" in str(e):
            print("[fatal] molit_fetch_log/molit_deals 테이블 없음 — "
                  "0020_molit_deals.sql 을 NAS psql 로 먼저 적용하세요")
            sys.exit(1)
        raise
    months = _months_back(args.backfill_months)
    recent, backfill_months = months[:2], months[2:]
    stale_before = (datetime.now(timezone.utc)
                    - timedelta(days=STALE_DAYS)).isoformat()

    # 잡 목록 — (deal_type, lawd_cd, deal_ymd). 증분(당월+전월) 먼저,
    # 백필은 오래된 월부터 drain (fetch_log 에 남아 다음 실행에서 이어짐).
    jobs: list[tuple[str, str, str]] = []
    for lawd in sorted(region_types):
        for t in sorted(region_types[lawd]):
            for ym in recent:
                prev = log.get((t, lawd, ym))
                if prev is None or prev < stale_before:
                    jobs.append((t, lawd, ym))
    for ym in reversed(backfill_months):  # 오래된 월부터
        for lawd in sorted(region_types):
            for t in sorted(region_types[lawd]):
                if (t, lawd, ym) not in log:
                    jobs.append((t, lawd, ym))

    n_regions = len(region_types)
    print(f"[plan] regions={n_regions} jobs={len(jobs)} budget={args.budget} "
          f"(backfill {args.backfill_months}mo, stale {STALE_DAYS}d)")
    if args.dry_run:
        for t, lawd, ym in jobs[:30]:
            print(f"  {t:5s} {lawd} {ym}")
        if len(jobs) > 30:
            print(f"  ... +{len(jobs) - 30} more")
        print(f"[dry-run] candidates: {len(jobs)}")
        return
    if not jobs:
        print("[done] molit deals — candidates: 0")
        return

    run_id = _start_run(store, "molit_deals",
                        {"budget": args.budget, "jobs": len(jobs)})
    client = MolitClient()
    n_jobs = n_rows = 0
    err: str | None = None
    try:
        for t, lawd, ym in jobs:
            if client.calls >= args.budget:
                print(f"[cap] API 예산 {args.budget}콜 소진 — 남은 잡 {len(jobs) - n_jobs}개는 다음 실행")
                break
            try:
                rows = client.fetch_deals(t, lawd, ym)
            except MolitError as e:
                # 쿼터 초과 등 — 오늘은 더 못 함. 지금까지 적재분은 보존.
                err = str(e)
                print(f"[abort] {t} {lawd} {ym}: {e}")
                break
            n = store.replace_deals(t, lawd, ym, rows)
            n_jobs += 1
            n_rows += n
            if n_jobs % 50 == 0:
                print(f"  ... {n_jobs}/{len(jobs)} jobs, {n_rows} rows, "
                      f"{client.calls} calls")
    finally:
        client.close()
        _finish_run(store, run_id,
                    {"jobs": n_jobs, "rows": n_rows, "calls": client.calls},
                    status="done" if err is None else "failed", error=err)
    elapsed = time.monotonic() - started
    print(f"[done] molit deals — jobs={n_jobs}/{len(jobs)} rows={n_rows} "
          f"calls={client.calls} ({elapsed:.0f}s)")


# ---------- building-register ----------

_PAD4 = lambda s: s.zfill(4)  # noqa: E731


def _br_params(row: dict) -> tuple[str, str, str, str, str] | None:
    """properties row → (sigungu, bjdong, bun, ji, plat_gb). 파싱 불가 시 None.
    웹 building-register.tsx:33-37 파라미터 파생 로직 포팅."""
    sigungu = f"{row['sd_code']}{row['sgg_code']}"
    if len(sigungu) != 5:
        return None
    bjdong = f"{row['emd_code']}00"
    lot_no = str(row.get("lot_no") or "").strip()
    lot_addr = str(row.get("lot_addr") or "")
    mountain = lot_no.startswith("산") or bool(re.search(r"산\s*\d", lot_addr))
    m = re.match(r"^(\d+)(?:-(\d+))?", lot_no.lstrip("산").strip())
    if not m:
        return None
    bun = _PAD4(m.group(1))
    ji = _PAD4(m.group(2) or "0")
    return sigungu, bjdong, bun, ji, ("1" if mountain else "0")


def cmd_building_register(args: argparse.Namespace) -> None:
    store = MolitStore()
    started = time.monotonic()
    try:
        cands = store.br_candidates(args.limit)
    except Exception as e:  # noqa: BLE001
        if "42P01" in str(e) or "does not exist" in str(e):
            print("[fatal] property_building_register 테이블 없음 — "
                  "0021_building_register.sql 을 NAS psql 로 먼저 적용하세요")
            sys.exit(1)
        raise
    print(f"[plan] candidates: {len(cands)} (limit {args.limit})")
    if args.dry_run or not cands:
        if not cands:
            print("[done] building-register — candidates: 0")
        return

    run_id = _start_run(store, "molit_building_register",
                        {"limit": args.limit, "candidates": len(cands)})
    client = MolitClient()
    n_ok = n_nf = n_err = n_skip = 0
    try:
        for row in cands:
            params = _br_params(row)
            if params is None:
                # 지번 파싱 불가 — not_found 로 기록해 재시도 루프에서 제외
                store.upsert_br(row["id"], {"fetch_status": "not_found"})
                n_skip += 1
                continue
            sigungu, bjdong, bun, ji, plat_gb = params
            try:
                titles = client.fetch_br_title(sigungu, bjdong, bun, ji, plat_gb)
            except MolitError as e:
                print(f"[abort] quota/API error: {e}")
                break
            except Exception as e:  # noqa: BLE001
                store.upsert_br(row["id"], {"fetch_status": "error"})
                n_err += 1
                logger.warning("br fetch 실패 %s: %s", row["id"], e)
                continue
            if not titles:
                store.upsert_br(row["id"], {"fetch_status": "not_found"})
                n_nf += 1
            else:
                store.upsert_br(row["id"], {**titles[0], "fetch_status": "ok"})
                n_ok += 1
            done = n_ok + n_nf + n_err + n_skip
            if done % 100 == 0:
                print(f"  ... {done}/{len(cands)} (ok={n_ok} nf={n_nf} err={n_err})")
    finally:
        client.close()
        _finish_run(store, run_id,
                    {"ok": n_ok, "not_found": n_nf, "error": n_err,
                     "unparsable": n_skip, "calls": client.calls})
    elapsed = time.monotonic() - started
    print(f"[done] building-register — ok={n_ok} not_found={n_nf} error={n_err} "
          f"unparsable={n_skip} calls={client.calls} ({elapsed:.0f}s)")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(description="MOLIT 실거래가/건축물대장 → Supabase 적재")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_d = sub.add_parser("deals", help="실거래가 월 단위 수집 (증분+백필, 예산제)")
    p_d.add_argument("--budget", type=int, default=900,
                     help="API 호출 예산 (기본 900 — data.go.kr 1,000/일 대비 여유)")
    p_d.add_argument("--backfill-months", type=int, default=24)
    p_d.add_argument("--dry-run", action="store_true", help="수집 계획만 출력")
    p_d.set_defaults(func=cmd_deals)

    p_b = sub.add_parser("building-register",
                         help="건축물대장 표제부 — 활성 건물 매물당 1회")
    p_b.add_argument("--limit", type=int, default=500)
    p_b.add_argument("--dry-run", action="store_true", help="후보 카운트만")
    p_b.set_defaults(func=cmd_building_register)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
