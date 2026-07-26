"""
score.py — 매수 안전도 점수(가격 제외) 배치 계산 CLI.

서브커맨드:
    run                  활성 매물 전량 채점 → property_scores upsert (0023)
        --limit N            상위 N건만 (테스트용)
        --dry-run            분포만 출력, 저장 안 함

규칙: crawler/src/scorer/rules.py (순수 함수). 100 에서 risk_flags tier 별 감점 +
물건유형/연식 보정. detail 미동기 매물은 신뢰도 low + 점수 상한.

스케줄: run_daily.sh 말미(estimate-predict 직후, DB-only 수 초).
환경변수 (.env): SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import os  # noqa: E402

from supabase import Client, create_client  # noqa: E402

from scorer import VERSION, score_property  # noqa: E402


def _client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_(SERVICE_)KEY env required")
    return create_client(url, key)


def _page_all(q_builder, page: int = 1000) -> list[dict]:
    """PostgREST 1000행 상한 우회 — q_builder()가 매번 새 쿼리를 만들어야 함."""
    out: list[dict] = []
    offset = 0
    while True:
        r = q_builder().range(offset, offset + page - 1).execute()
        rows = r.data or []
        out.extend(rows)
        if len(rows) < page:
            return out
        offset += page


def _building_year_map(sb: Client, property_ids: list[str]) -> dict[str, int]:
    """property_id → 준공년도. property_building_register(있으면). 없으면 빈 dict."""
    out: dict[str, int] = {}
    CHUNK = 150  # uuid .in_() 150 초과 시 NAS nginx 414 (memo.txt 주의사항)
    try:
        for i in range(0, len(property_ids), CHUNK):
            r = (sb.table("property_building_register")
                 .select("property_id, use_approval_day")
                 .eq("fetch_status", "ok")
                 .in_("property_id", property_ids[i:i + CHUNK])
                 .execute())
            for row in r.data or []:
                day = row.get("use_approval_day")
                if day and len(str(day)) >= 4:
                    out[row["property_id"]] = int(str(day)[:4])
    except Exception as e:  # noqa: BLE001 — 0021 미적용 시 콜드스타트
        print(f"[warn] building_register 조회 실패(연식 없이 진행): {e}")
    return out


def cmd_run(args: argparse.Namespace) -> None:
    started = time.monotonic()
    sb = _client()

    rows = _page_all(lambda: sb.table("properties")
                     .select("id, risk_flags, conv_addr, usage_lcl_cd, usage_nm, "
                             "detail_synced_at")
                     .is_("deleted_at", "null")
                     .order("id"))
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        print("[done] score — candidates: 0")
        return

    year_map = _building_year_map(sb, [r["id"] for r in rows])
    now_iso = datetime.now(timezone.utc).isoformat()
    this_year = datetime.now(timezone.utc).year

    payload: list[dict] = []
    conf_ctr: Counter[str] = Counter()
    buckets = Counter()  # 점수대 분포
    for r in rows:
        res = score_property(
            risk_flags=r.get("risk_flags"),
            conv_addr=r.get("conv_addr"),
            usage_lcl_cd=r.get("usage_lcl_cd"),
            usage_nm=r.get("usage_nm"),
            building_year=year_map.get(r["id"]),
            has_detail=bool(r.get("detail_synced_at")),
            this_year=this_year,
        )
        conf_ctr[res["confidence"]] += 1
        buckets[min(90, (res["score"] // 10) * 10)] += 1
        payload.append({
            "property_id": r["id"],
            "score": res["score"],
            "confidence": res["confidence"],
            "breakdown": res["breakdown"],
            "version": VERSION,
            "scored_at": now_iso,
        })

    dist = " ".join(f"{b}+:{buckets[b]}" for b in sorted(buckets))
    print(f"[dist] {len(payload)}건 | {dist}")
    print(f"[conf] high={conf_ctr['high']} medium={conf_ctr['medium']} "
          f"low={conf_ctr['low']}")
    if args.dry_run:
        print("[dry-run] 저장 생략")
        return

    CHUNK = 200
    try:
        for i in range(0, len(payload), CHUNK):
            sb.table("property_scores").upsert(payload[i:i + CHUNK]).execute()
    except Exception as e:  # noqa: BLE001
        if "42P01" in str(e) or "does not exist" in str(e):
            print("[fatal] property_scores 테이블 없음 — "
                  "0023_property_scores.sql 을 NAS psql 로 먼저 적용하세요")
            sys.exit(1)
        raise

    # properties.safety_score 동기화 (정렬/필터용 미러) — 0023 함수. 없으면 경고만.
    synced = None
    try:
        r = sb.rpc("sync_safety_scores").execute()
        synced = r.data
    except Exception as e:  # noqa: BLE001 — 0023 함수 미적용 등
        print(f"[warn] sync_safety_scores 실패(정렬용 미러 미갱신): {e}")

    print(f"[done] score — saved={len(payload)}"
          f"{f' synced={synced}' if synced is not None else ''} "
          f"({time.monotonic() - started:.0f}s)")


def main() -> None:
    ap = argparse.ArgumentParser(description="매수 안전도 점수 배치 계산")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="활성 매물 채점 → property_scores")
    p.add_argument("--limit", type=int, default=None, help="상위 N건만 (테스트)")
    p.add_argument("--dry-run", action="store_true", help="분포만 출력, 저장 생략")
    p.set_defaults(func=cmd_run)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
