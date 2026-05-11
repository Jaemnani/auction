"""
ingest.py — courtauction → Supabase 직접 적재 CLI.

서브커맨드:
    masters              마스터 코드 (법원/시도/시군구/용도) → courts/regions_*/usage_codes
        --include-emd    + 시군구별 읍면동 (시간 다소 소요)
    search               검색 결과 → cases + properties upsert
        --kind real_estate|movables  (default real_estate)
        --court CODE                 (옵션, 특정 법원만)
        --max-pages N                (옵션, 페이지 제한)
        --page-size N                (default 50, 서버 상한)
    detail COURT CASE_NO SEQ        단일 사건/물건 detail → properties.detail_result + sale_dates + photos
    backfill-details              검색 적재된 properties 중 detail 미수집인 것들을 일괄 채움
        --limit N                    (default 100)
        --court CODE                 (옵션)

환경변수 (.env):
    SUPABASE_URL
    SUPABASE_SERVICE_KEY (권장; 없으면 SUPABASE_KEY anon)

실행:
    /Users/ohyeahdani_m1/workspace/venv_common/bin/python crawler/scripts/ingest.py masters
    .../python crawler/scripts/ingest.py search --court B000210 --max-pages 5
    .../python crawler/scripts/ingest.py backfill-details --limit 50
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# .env 로드 (프로젝트 루트)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

# 패키지 import
SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from courtauction import (  # noqa: E402
    ClientConfig, CourtAuctionClient, Store,
)
from courtauction.store import PHOTO_BUCKET  # noqa: E402

CRAWLER_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = CRAWLER_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DEAD_LETTER = DATA_DIR / "dead_letter.jsonl"


def _make_client(*, save_raw: bool) -> CourtAuctionClient:
    return CourtAuctionClient(ClientConfig(
        save_dir=RAW_DIR if save_raw else None,
        dead_letter_path=DEAD_LETTER,
    ))


# ---------- masters ----------

async def cmd_masters(args: argparse.Namespace) -> None:
    store = Store()
    run_id = store.start_run("masters", {"include_emd": args.include_emd})
    started = time.monotonic()
    totals: dict[str, int] = {}

    try:
        async with _make_client(save_raw=args.save_raw) as c:
            # 1) 법원 (B + O prefix)
            court_rows: list[dict] = []
            for prefix in ("00079B", "00079O"):
                try:
                    courts = await c.list_courts(prefix)
                except Exception as e:
                    print(f"  ! courts({prefix}) failed: {e}")
                    continue
                for row in courts:
                    court_rows.append({"prefix": prefix, **row})
                print(f"  + courts({prefix}): {len(courts)}")
            totals["courts"] = store.upsert_courts(court_rows)

            # 2) 시도
            try:
                sido = await c.list_sido()
            except Exception as e:
                print(f"  ! sido failed: {e}")
                sido = []
            totals["regions_sd"] = store.upsert_regions_sd(sido)
            print(f"  + sido: {len(sido)}")

            # 3) 시군구
            sgg_all: list[dict] = []
            sgg_by_sd: dict[str, list[dict]] = {}
            for sd in sido:
                sd_code = sd.get("code")
                try:
                    sgg = await c.list_sigungu(sd_code)
                except Exception as e:
                    print(f"  ! sgg({sd_code}) failed: {e}")
                    continue
                sgg_by_sd[sd_code] = sgg
                for r in sgg:
                    sgg_all.append({"sd_code": sd_code, **r})
            totals["regions_sgg"] = store.upsert_regions_sgg(sgg_all)
            print(f"  + sgg: {len(sgg_all)} (across {len(sgg_by_sd)} sido)")

            # 4) 읍면동 (옵션)
            if args.include_emd:
                emd_all: list[dict] = []
                for sd_code, sgg_list in sgg_by_sd.items():
                    for sgg in sgg_list:
                        sgg_code = sgg.get("code")
                        try:
                            emd = await c.list_emd(sgg_code)
                        except Exception as e:
                            print(f"  ! emd({sgg_code}) failed: {e}")
                            continue
                        for r in emd:
                            emd_all.append({"sd_code": sd_code,
                                            "sgg_code": sgg_code, **r})
                totals["regions_emd"] = store.upsert_regions_emd(emd_all)
                print(f"  + emd: {len(emd_all)}")

            # 5) 용도 트리
            usage_rows: list[dict] = []
            try:
                lcl = await c.list_usage_lcl()
            except Exception as e:
                print(f"  ! lcl failed: {e}")
                lcl = []
            for r in lcl:
                usage_rows.append({"type": "usage_lcl", **r})

            for l in lcl:
                l_code = l.get("code")
                try:
                    mcl = await c.list_usage_mcl(l_code)
                except Exception as e:
                    print(f"  ! mcl({l_code}) failed: {e}")
                    continue
                for r in mcl:
                    usage_rows.append({"type": "usage_mcl", "lcl_code": l_code, **r})

                for m in mcl:
                    m_code = m.get("code")
                    try:
                        scl = await c.list_usage_scl(m_code)
                    except Exception as e:
                        print(f"  ! scl({m_code}) failed: {e}")
                        continue
                    for r in scl:
                        usage_rows.append({"type": "usage_scl",
                                           "lcl_code": l_code,
                                           "mcl_code": m_code, **r})
            totals["usage_codes"] = store.upsert_usage_codes(usage_rows)
            print(f"  + usage_codes (lcl+mcl+scl): {totals['usage_codes']}")

        store.finish_run(run_id, totals=totals)
    except Exception as e:
        store.finish_run(run_id, totals=totals, status="failed", error=str(e))
        raise

    elapsed = time.monotonic() - started
    print(f"\n[done] masters → {totals} ({elapsed:.1f}s)")


# ---------- search ----------

async def cmd_search(args: argparse.Namespace) -> None:
    store = Store()
    run_id = store.start_run("search", {
        "kind": args.kind, "court": args.court, "sd": getattr(args, "sd", None),
        "split_sd": getattr(args, "split_sd", False),
        "max_pages": args.max_pages, "page_size": args.page_size,
    })
    started = time.monotonic()
    totals = {"pages": 0, "rows": 0, "upserted": 0, "by_sd": {}}

    # split_sd 모드: 17개 시도로 분할 호출 (페이징 안정화 → 누락 방지)
    if getattr(args, "split_sd", False):
        sds = [r["code"] for r in (
            store.sb.table("regions_sd").select("code").execute().data or []
        )]
        sd_list = sds
    elif getattr(args, "sd", None):
        sd_list = [args.sd]
    else:
        sd_list = [None]  # 단일 호출 (전국)

    try:
        async with _make_client(save_raw=args.save_raw) as c:
            for sd in sd_list:
                sd_total = 0
                kwargs = {}
                if sd:
                    kwargs["filters"] = {"rprsAdongSdCd": sd}
                async for page in c.search_iter(
                    kind=args.kind,
                    page_size=args.page_size,
                    cort_ofc_cd=args.court,
                    max_pages=args.max_pages,
                    **kwargs,
                ):
                    rows = page.get("dlt_srchResult") or []
                    page_info = page.get("dma_pageInfo") or {}
                    totals["pages"] += 1
                    totals["rows"] += len(rows)
                    upserted = store.upsert_search_rows(rows)
                    totals["upserted"] += upserted
                    sd_total += upserted
                    sd_lbl = f"sd={sd} " if sd else ""
                    print(f"  {sd_lbl}page {page_info.get('pageNo')}/"
                          f"{page_info.get('totalCnt')} → +{len(rows)} rows "
                          f"(upserted {upserted}; total {totals['upserted']})")
                if sd:
                    totals["by_sd"][sd] = sd_total

        store.finish_run(run_id, totals=totals)
    except Exception as e:
        store.finish_run(run_id, totals=totals, status="failed", error=str(e))
        raise

    elapsed = time.monotonic() - started
    print(f"\n[done] search → {totals} ({elapsed:.1f}s)")


# ---------- detail ----------

async def cmd_detail(args: argparse.Namespace) -> None:
    store = Store()
    async with _make_client(save_raw=args.save_raw) as c:
        result = await c.get_case_detail(args.court, args.case_no, args.seq)
        prop_id = store.upsert_detail(args.court, args.case_no,
                                      int(args.seq), result)
    print(f"[done] detail upserted → property_id={prop_id}")


# ---------- backfill ----------

async def cmd_backfill(args: argparse.Namespace) -> None:
    """detail 백필 — 동시 요청 N개로 병렬 처리.

    --concurrency N (기본 5): 동시에 처리할 매물 수
    한 매물당: API 1회 호출 + DB upsert (sync) → asyncio.to_thread로 분리
    """
    store = Store()
    run_id = store.start_run("backfill_details",
                             {"limit": args.limit, "court": args.court,
                              "concurrency": args.concurrency})
    started = time.monotonic()

    q = (
        store.sb.table("properties")
        .select("id, maemul_ser, cases!inner(court_code, case_no)")
        .is_("detail_synced_at", "null")
        .limit(args.limit)
    )
    if args.court:
        q = q.eq("cases.court_code", args.court)
    res = q.execute()
    targets = res.data or []
    print(f"  targets: {len(targets)} (concurrency={args.concurrency})")

    totals = {"requested": len(targets), "ok": 0, "failed": 0}
    sem = asyncio.Semaphore(args.concurrency)
    last_print = time.monotonic()

    try:
        async with _make_client(save_raw=args.save_raw) as c:
            async def worker(t: dict) -> None:
                nonlocal last_print
                court = t["cases"]["court_code"]
                case_no = t["cases"]["case_no"]
                seq = t["maemul_ser"]
                async with sem:
                    try:
                        result = await c.get_case_detail(court, case_no, seq)
                        # upsert_detail은 동기 — 별도 스레드에서 실행
                        await asyncio.to_thread(
                            store.upsert_detail, court, case_no, seq, result
                        )
                        totals["ok"] += 1
                    except Exception as e:
                        totals["failed"] += 1
                        print(f"    ! {court}/{case_no}#{seq}: {e}")
                    # 진행률 한 줄 (최소 5초 간격)
                    now = time.monotonic()
                    if now - last_print >= 5.0:
                        last_print = now
                        elapsed = now - started
                        rate = totals["ok"] / max(elapsed, 0.001)
                        eta_s = (totals["requested"] - totals["ok"] - totals["failed"]) / max(rate, 0.001)
                        print(f"    progress: ok={totals['ok']} fail={totals['failed']} "
                              f"rate={rate:.2f}/s eta={eta_s/60:.1f}min")

            await asyncio.gather(*[worker(t) for t in targets])
        store.finish_run(run_id, totals=totals)
    except Exception as e:
        store.finish_run(run_id, totals=totals, status="failed", error=str(e))
        raise

    elapsed = time.monotonic() - started
    print(f"\n[done] backfill → {totals} ({elapsed:.1f}s, "
          f"{totals['ok']/elapsed:.1f}/s)")


# ---------- backfill photos ----------

async def cmd_backfill_photos(args: argparse.Namespace) -> None:
    """이전 적재로 raw.picFile에 base64가 남아있는 photo row들을 Storage로 옮긴다.

    raw 컬럼에 base64가 들어있어 한 번에 select하면 timeout이 난다.
    → 1) id 목록만 lightweight select  2) row 단위로 raw 포함 fetch + upload + 정리.
    """
    from courtauction.store import _guess_content_type  # local import

    store = Store()
    run_id = store.start_run("backfill_photos", {"limit": args.limit})
    started = time.monotonic()

    id_res = (
        store.sb.table("property_photos")
        .select("id")
        .is_("storage_path", "null")
        .limit(args.limit)
        .execute()
    )
    ids = [r["id"] for r in (id_res.data or [])]
    print(f"  candidates: {len(ids)}")

    totals = {"requested": len(ids), "ok": 0, "skipped": 0, "failed": 0}
    try:
        for pid in ids:
            try:
                row_res = (
                    store.sb.table("property_photos")
                    .select(
                        "id, seq, raw, property_id, "
                        "properties!inner(id, maemul_ser, "
                        "cases!inner(court_code, case_no))"
                    )
                    .eq("id", pid)
                    .single()
                    .execute()
                )
            except Exception as e:
                totals["failed"] += 1
                print(f"    ! fetch {pid}: {e}")
                continue
            t = row_res.data
            raw = t.get("raw") or {}
            pic_b64 = raw.get("picFile")
            if not pic_b64:
                totals["skipped"] += 1
                continue
            court = t["properties"]["cases"]["court_code"]
            case_no = t["properties"]["cases"]["case_no"]
            ms = t["properties"]["maemul_ser"]
            seq = t["seq"]
            path = store._photo_storage_path(
                court, case_no, ms, seq, title=raw.get("picTitlNm"),
            )
            try:
                store._upload_photo(
                    path, pic_b64,
                    content_type=_guess_content_type(raw.get("picTitlNm")),
                )
                raw_meta = {k: v for k, v in raw.items() if k != "picFile"}
                store.sb.table("property_photos").update(
                    {"storage_path": path, "raw": raw_meta}
                ).eq("id", t["id"]).execute()
                totals["ok"] += 1
                if totals["ok"] % 20 == 0:
                    print(f"    {totals['ok']} uploaded… latest={path}")
            except Exception as e:
                totals["failed"] += 1
                print(f"    ! {path}: {e}")
        store.finish_run(run_id, totals=totals)
    except Exception as e:
        store.finish_run(run_id, totals=totals, status="failed", error=str(e))
        raise

    elapsed = time.monotonic() - started
    print(f"\n[done] backfill-photos → {totals} ({elapsed:.1f}s)")


# ---------- backfill thumbs ----------

async def cmd_backfill_thumbs(args: argparse.Namespace) -> None:
    """이미 storage_path가 있는 photo들의 썸네일을 일괄 생성.

    원본 다운로드 → Pillow resize → thumbs/{path} 업로드 (upsert).
    이미 thumbs가 있어도 멱등(upsert=true)이라 안전하지만, 비용 절감을 위해 미리 list로
    있는 것은 skip한다.
    """
    import httpx  # 동기 다운로드용
    from courtauction.store import Store as _S, THUMB_PREFIX

    store = Store()
    run_id = store.start_run("backfill_thumbs", {"limit": args.limit})
    started = time.monotonic()

    # storage_path 있는 photo
    res = (
        store.sb.table("property_photos")
        .select("id, storage_path")
        .not_.is_("storage_path", "null")
        .limit(args.limit)
        .execute()
    )
    targets = res.data or []
    print(f"  candidates: {len(targets)}")

    # 이미 존재하는 thumbs 목록 (Storage list — prefix별로 호출하면 비싸니
    # 일단 단순 upsert 전략. supabase-py list API는 페이지네이션 필요)
    totals = {"requested": len(targets), "ok": 0, "failed": 0}
    bucket = store.sb.storage.from_(PHOTO_BUCKET)
    base_url = store.cfg.url.rstrip("/") + f"/storage/v1/object/public/{PHOTO_BUCKET}"

    try:
        with httpx.Client(timeout=30.0) as cli:
            for t in targets:
                path = t["storage_path"]
                try:
                    r = cli.get(f"{base_url}/{path}")
                    if r.status_code != 200:
                        raise RuntimeError(f"download {r.status_code}")
                    thumb_blob = _S._make_thumb(r.content)
                    bucket.upload(
                        path=THUMB_PREFIX + path,
                        file=thumb_blob,
                        file_options={"content-type": "image/jpeg",
                                      "upsert": "true"},
                    )
                    totals["ok"] += 1
                    if totals["ok"] % 20 == 0:
                        print(f"    {totals['ok']} thumbs… latest={path}")
                except Exception as e:
                    totals["failed"] += 1
                    print(f"    ! {path}: {e}")
        store.finish_run(run_id, totals=totals)
    except Exception as e:
        store.finish_run(run_id, totals=totals, status="failed", error=str(e))
        raise

    elapsed = time.monotonic() - started
    print(f"\n[done] backfill-thumbs → {totals} ({elapsed:.1f}s)")


# ---------- backfill coords ----------

async def cmd_backfill_coords(args: argparse.Namespace) -> None:
    """기존 properties.search_row.xCordi/yCordi (KATEC)을 WGS84로 변환해 longitude/latitude 갱신."""
    from courtauction.store import katec_to_wgs84

    store = Store()
    run_id = store.start_run("backfill_coords", {"limit": args.limit})
    started = time.monotonic()

    res = (
        store.sb.table("properties")
        .select("id, search_row, longitude, latitude")
        .limit(args.limit)
        .execute()
    )
    targets = res.data or []
    totals = {"requested": len(targets), "updated": 0, "noop": 0, "skipped": 0}
    print(f"  candidates: {totals['requested']}")

    try:
        for t in targets:
            sr = t.get("search_row") or {}
            ll = katec_to_wgs84(sr.get("xCordi"), sr.get("yCordi"))
            if not ll:
                totals["skipped"] += 1
                continue
            lng, lat = ll
            cur_lng = t.get("longitude")
            cur_lat = t.get("latitude")
            # 이미 정확하면 skip
            if cur_lng and cur_lat and abs(cur_lng - lng) < 1e-4 and abs(cur_lat - lat) < 1e-4:
                totals["noop"] += 1
                continue
            store.sb.table("properties").update(
                {"longitude": lng, "latitude": lat}
            ).eq("id", t["id"]).execute()
            totals["updated"] += 1
        store.finish_run(run_id, totals=totals)
    except Exception as e:
        store.finish_run(run_id, totals=totals, status="failed", error=str(e))
        raise

    elapsed = time.monotonic() - started
    print(f"\n[done] backfill-coords → {totals} ({elapsed:.1f}s)")


# ---------- backfill addrs ----------

async def cmd_backfill_addrs(args: argparse.Namespace) -> None:
    """기존 properties.search_row의 주소 필드를 road_addr/lot_addr로 채움."""
    from courtauction.store import _clean_addr

    store = Store()
    run_id = store.start_run("backfill_addrs", {"limit": args.limit})
    started = time.monotonic()

    res = (
        store.sb.table("properties")
        .select("id, search_row, road_addr, lot_addr")
        .limit(args.limit)
        .execute()
    )
    targets = res.data or []
    totals = {"requested": len(targets), "updated": 0, "noop": 0, "skipped": 0}

    for t in targets:
        sr = t.get("search_row") or {}
        road = _clean_addr(sr.get("bgPlaceRdAllAddr") or sr.get("rdAllAddr"))
        lot  = _clean_addr(sr.get("bgPlaceLotAllAddr") or sr.get("lotAllAddr"))
        if not road and not lot:
            totals["skipped"] += 1
            continue
        if road == t.get("road_addr") and lot == t.get("lot_addr"):
            totals["noop"] += 1
            continue
        store.sb.table("properties").update(
            {"road_addr": road, "lot_addr": lot}
        ).eq("id", t["id"]).execute()
        totals["updated"] += 1

    store.finish_run(run_id, totals=totals)
    elapsed = time.monotonic() - started
    print(f"\n[done] backfill-addrs → {totals} ({elapsed:.1f}s)")


# ---------- backfill-risk-flags ----------

async def cmd_backfill_risk_flags(args: argparse.Namespace) -> None:
    """detail_result가 있는데 risk_flags가 비어있는 매물에 대해 일괄 분석.

    detail 재호출 없이 DB의 detail_result만 읽어 분석 → properties.risk_flags 갱신.
    --force 옵션은 기존 risk_flags가 채워져있어도 재계산.
    """
    from courtauction.risk_flags import compute_risk_flags  # noqa: E402

    store = Store()
    started = time.monotonic()
    n_updated = 0
    n_seen = 0
    page_size = max(50, int(args.batch))
    last_id: str | None = None

    while True:
        q = (
            store.sb.table("properties")
            .select(
                "id, detail_result, appraisal_amount, fail_count, "
                "usage_lcl_cd, usage_mcl_cd, area_summary, building_summary, risk_flags"
            )
            .not_.is_("detail_result", "null")
            .order("id")
            .limit(page_size)
        )
        if last_id:
            q = q.gt("id", last_id)
        if not args.force:
            # risk_flags가 빈 array인 row만 — PostgREST 비교: eq.{} (배열 비교)
            q = q.eq("risk_flags", "{}")
        if args.limit and n_seen >= args.limit:
            break
        res = q.execute()
        rows = res.data or []
        if not rows:
            break

        for r in rows:
            n_seen += 1
            last_id = r["id"]
            flags = compute_risk_flags(
                detail_result=r.get("detail_result"),
                appraisal_amount=r.get("appraisal_amount"),
                fail_count=r.get("fail_count"),
                usage_lcl_cd=r.get("usage_lcl_cd"),
                usage_mcl_cd=r.get("usage_mcl_cd"),
                area_summary=r.get("area_summary"),
                building_summary=r.get("building_summary"),
            )
            prev = r.get("risk_flags") or []
            if sorted(prev) == sorted(flags):
                continue  # 변경 없음 — skip
            store.sb.table("properties").update({"risk_flags": flags}).eq(
                "id", r["id"]
            ).execute()
            n_updated += 1
            if n_updated % 100 == 0:
                print(f"  ... {n_updated} updated (seen {n_seen})")

        if args.limit and n_seen >= args.limit:
            break

    elapsed = time.monotonic() - started
    print(f"\n[done] backfill-risk-flags → updated={n_updated}, seen={n_seen} ({elapsed:.1f}s)")


# ---------- reverse geocoding (Kakao Local) ----------

async def cmd_reverse_geocode(args: argparse.Namespace) -> None:
    """좌표는 있는데 road_addr이 비어있는 매물을 Kakao 역지오코딩으로 채움."""
    import httpx

    api_key = os.environ.get("KAKAO_REST_API_KEY")
    if not api_key:
        print("[fatal] KAKAO_REST_API_KEY 환경변수 없음")
        return

    store = Store()
    run_id = store.start_run("reverse_geocode",
                             {"limit": args.limit, "concurrency": args.concurrency})
    started = time.monotonic()

    # Supabase 기본 max-rows 1000 → range로 페이지 분할
    PAGE = 1000
    targets: list[dict] = []
    offset = 0
    while len(targets) < args.limit:
        res = (
            store.sb.table("properties")
            .select("id, longitude, latitude")
            .is_("road_addr", "null")
            .not_.is_("longitude", "null")
            .not_.is_("latitude", "null")
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            break
        targets.extend(rows)
        if len(rows) < PAGE:
            break
        offset += PAGE
    targets = targets[:args.limit]
    print(f"  targets: {len(targets)} (concurrency={args.concurrency})")

    totals = {"requested": len(targets), "ok": 0, "no_addr": 0, "failed": 0}
    sem = asyncio.Semaphore(args.concurrency)
    last_print = time.monotonic()

    async with httpx.AsyncClient(
        timeout=15.0,
        headers={"Authorization": f"KakaoAK {api_key}"},
    ) as cli:
        async def worker(t: dict) -> None:
            nonlocal last_print
            async with sem:
                lng = t["longitude"]; lat = t["latitude"]
                try:
                    r = await cli.get(
                        "https://dapi.kakao.com/v2/local/geo/coord2address.json",
                        params={"x": lng, "y": lat, "input_coord": "WGS84"},
                    )
                    if r.status_code != 200:
                        totals["failed"] += 1
                        return
                    docs = r.json().get("documents") or []
                    if not docs:
                        totals["no_addr"] += 1
                        return
                    d = docs[0]
                    road = d.get("road_address") or {}
                    addr = d.get("address") or {}
                    payload: dict = {}
                    if road.get("address_name"):
                        payload["road_addr"] = road["address_name"]
                    if addr.get("address_name"):
                        payload["lot_addr"] = addr["address_name"]
                    if not payload:
                        totals["no_addr"] += 1
                        return
                    await asyncio.to_thread(
                        lambda: store.sb.table("properties")
                            .update(payload).eq("id", t["id"]).execute()
                    )
                    totals["ok"] += 1
                except Exception:
                    totals["failed"] += 1
                # progress
                now = time.monotonic()
                if now - last_print >= 5.0:
                    last_print = now
                    elapsed = now - started
                    done = totals["ok"] + totals["no_addr"] + totals["failed"]
                    rate = done / max(elapsed, 0.001)
                    eta = (totals["requested"] - done) / max(rate, 0.001)
                    print(f"    progress: ok={totals['ok']} no_addr={totals['no_addr']} "
                          f"fail={totals['failed']} rate={rate:.1f}/s eta={eta/60:.1f}min")

        await asyncio.gather(*[worker(t) for t in targets])

    store.finish_run(run_id, totals=totals)
    elapsed = time.monotonic() - started
    print(f"\n[done] reverse-geocode → {totals} ({elapsed:.1f}s)")


# ---------- sales results (매각결과) ----------

async def cmd_sales_results(args: argparse.Namespace) -> None:
    """매각결과검색으로 종결 매물 일괄 적재 → sale_results 테이블.

    기본 기간: 90일 전 ~ 오늘. 17개 시도 × 4 용도 매트릭스로 페이징 (전국).
    """
    from datetime import date, timedelta

    bid_to = args.bid_to or date.today().strftime("%Y%m%d")
    bid_from = args.bid_from or (date.today() - timedelta(days=90)).strftime("%Y%m%d")

    store = Store()
    run_id = store.start_run("sales_results",
                             {"bid_from": bid_from, "bid_to": bid_to})
    started = time.monotonic()

    # 시도 코드 (17개) — 전국 페이징
    sd_codes = [r["code"] for r in (
        store.sb.table("regions_sd").select("code").execute().data or []
    )]
    if not sd_codes:
        print("[warn] regions_sd 비어있음 — masters 먼저 실행하세요")
        store.finish_run(run_id, status="failed", error="regions_sd empty")
        return

    print(f"  bid range: {bid_from} ~ {bid_to}, sd × {len(sd_codes)}")
    totals = {"pages": 0, "rows": 0, "upserted": 0, "by_sd": {}}

    try:
        async with _make_client(save_raw=args.save_raw) as c:
            for sd in sd_codes:
                sd_total = 0
                async for page in c.search_results_iter(
                    page_size=50,
                    sd_code=sd,
                    bid_from=bid_from, bid_to=bid_to,
                    max_pages=args.max_pages,
                ):
                    rows = page.get("dlt_srchResult") or []
                    page_info = page.get("dma_pageInfo") or {}
                    totals["pages"] += 1
                    totals["rows"] += len(rows)
                    n = store.upsert_sale_results(rows)
                    totals["upserted"] += n
                    sd_total += n
                    print(f"  sd={sd} page {page_info.get('pageNo')}/"
                          f"{page_info.get('totalCnt')} → +{len(rows)} (up {n})")
                totals["by_sd"][sd] = sd_total
        store.finish_run(run_id, totals=totals)
    except Exception as e:
        store.finish_run(run_id, totals=totals, status="failed", error=str(e))
        raise

    elapsed = time.monotonic() - started
    print(f"\n[done] sales-results → {totals} ({elapsed:.1f}s)")


# ---------- main ----------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ap = argparse.ArgumentParser(description="courtauction → Supabase 적재")
    ap.add_argument("--save-raw", action="store_true",
                    help="모든 raw 응답을 data/raw/에 저장 (디버깅용)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_m = sub.add_parser("masters", help="마스터 코드 적재")
    p_m.add_argument("--include-emd", action="store_true")
    p_m.set_defaults(func=cmd_masters)

    p_s = sub.add_parser("search", help="검색결과 cases+properties 적재")
    p_s.add_argument("--kind", choices=("real_estate", "movables"),
                     default="real_estate")
    p_s.add_argument("--court", default=None)
    p_s.add_argument("--page-size", type=int, default=50)
    p_s.add_argument("--max-pages", type=int, default=None)
    p_s.add_argument("--sd", default=None,
                     help="시도 코드 필터 (rprsAdongSdCd) — 페이징 안정화용")
    p_s.add_argument("--split-sd", action="store_true",
                     help="17개 시도로 자동 분할 호출 (누락 방지, 권장)")
    p_s.set_defaults(func=cmd_search)

    p_d = sub.add_parser("detail", help="단일 detail 적재")
    p_d.add_argument("court")
    p_d.add_argument("case_no")
    p_d.add_argument("seq")
    p_d.set_defaults(func=cmd_detail)

    p_b = sub.add_parser("backfill-details", help="detail 미수집 properties 일괄 채움")
    p_b.add_argument("--limit", type=int, default=100)
    p_b.add_argument("--court", default=None)
    p_b.add_argument("--concurrency", type=int, default=2,
                     help="동시 detail 호출 수 (기본 2 — 더 늘리면 IP 차단)")
    p_b.set_defaults(func=cmd_backfill)

    p_p = sub.add_parser("backfill-photos",
                         help="property_photos.raw에 base64 picFile이 남아있는 row를 Storage로 옮김")
    p_p.add_argument("--limit", type=int, default=200)
    p_p.set_defaults(func=cmd_backfill_photos)

    p_t = sub.add_parser("backfill-thumbs",
                         help="storage_path가 있는데 thumbs/{path}가 없는 사진들에 썸네일 생성")
    p_t.add_argument("--limit", type=int, default=500)
    p_t.set_defaults(func=cmd_backfill_thumbs)

    p_c = sub.add_parser("backfill-coords",
                         help="search_row.xCordi/yCordi (KATEC)을 정확한 WGS84로 재계산")
    p_c.add_argument("--limit", type=int, default=10000)
    p_c.set_defaults(func=cmd_backfill_coords)

    p_a = sub.add_parser("backfill-addrs",
                         help="search_row의 도로명/지번 주소를 properties.road_addr/lot_addr로 채움")
    p_a.add_argument("--limit", type=int, default=10000)
    p_a.set_defaults(func=cmd_backfill_addrs)

    p_rf = sub.add_parser("backfill-risk-flags",
        help="detail_result를 분석해 risk_flags 컬럼 채움 (체크박스 필터용)")
    p_rf.add_argument("--batch", type=int, default=200)
    p_rf.add_argument("--limit", type=int, default=0,
                      help="최대 처리 매물 수 (0=무제한)")
    p_rf.add_argument("--force", action="store_true",
                      help="기존 risk_flags가 채워져있어도 재계산")
    p_rf.set_defaults(func=cmd_backfill_risk_flags)

    p_g = sub.add_parser("reverse-geocode",
                         help="좌표만 있고 도로명 없는 매물에 Kakao Local API로 주소 채움")
    p_g.add_argument("--limit", type=int, default=10000)
    p_g.add_argument("--concurrency", type=int, default=5)
    p_g.set_defaults(func=cmd_reverse_geocode)

    p_r = sub.add_parser("sales-results",
                         help="매각결과(종결 사건) 적재 — sale_results 테이블")
    p_r.add_argument("--bid-from", default=None,
                     help="YYYYMMDD (기본: 90일 전)")
    p_r.add_argument("--bid-to", default=None,
                     help="YYYYMMDD (기본: 오늘)")
    p_r.add_argument("--max-pages", type=int, default=None)
    p_r.set_defaults(func=cmd_sales_results)

    args = ap.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
