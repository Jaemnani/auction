"""
jp_ingest.py — BIT(bit.courts.go.jp) → Supabase 적재 CLI.

서브커맨드:
    search                BIT 검색 → jp_cases + jp_properties upsert
        --prefecture CODE     도도부현 (예: 13 東京)
        --block CODE          블록 (자동 추론 — prefecture에서 jp_prefectures로 lookup)
        --sale-cls 1,2,3,4    용도 필터 (콤마 구분, default: 전체)
        --max-pages N         페이지 제한 (default: 무제한)
        --page-size N         페이지 크기 (default: 30, BIT 상한)
    search-all            모든 도도부현 순회 (--skip CODE,CODE 로 제외 가능)
        --skip CODE,CODE      제외 도도부현
        --max-pages N         도도부현당 페이지 상한 (default: 12)
        --page-size N         페이지 크기 (default: 30)
    photos                jp_properties 중 사진 미수집인 매물의 search_row.photo_url 다운로드
        --limit N             (default 50)
    backfill-details      detail_result IS NULL인 jp_properties 매물 상세 일괄 fetch
        --prefecture CODE     도도부현 (default: 13 東京)
        --limit N             (default 100)
    detail SALE_UNIT_ID COURT_ID  단일 매물 상세 응답 → jp_properties.detail_result

환경변수 (.env):
    SUPABASE_URL
    SUPABASE_SERVICE_KEY (권장; 없으면 SUPABASE_KEY anon)

실행:
    /Users/ohyeahdani_m1/workspace/venv_common/bin/python crawler/scripts/jp_ingest.py search --prefecture 13 --max-pages 2
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from bit import BitClient, BitClientConfig, BitStore, BitTransientError  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("jp_ingest")


# 도도부현 → 블록 매핑 (jp_prefectures 시드와 동일 — DB lookup 회피용)
PREFECTURE_BLOCK = {
    # 北海道 지점 (01)
    "91": "01", "92": "01", "93": "01", "94": "01",
    # 東北 (02-07)
    "02": "02", "03": "02", "04": "02", "05": "02", "06": "02", "07": "02",
    # 関東 (08-14)
    "08": "03", "09": "03", "10": "03", "11": "03", "12": "03", "13": "03", "14": "03",
    # 北陸甲信越 (15-20)
    "15": "04", "16": "04", "17": "04", "18": "04", "19": "04", "20": "04",
    # 東海 (21-24)
    "21": "05", "22": "05", "23": "05", "24": "05",
    # 近畿 (25-30)
    "25": "06", "26": "06", "27": "06", "28": "06", "29": "06", "30": "06",
    # 中国 (31-35)
    "31": "07", "32": "07", "33": "07", "34": "07", "35": "07",
    # 四国 (36-39)
    "36": "08", "37": "08", "38": "08", "39": "08",
    # 九州沖縄 (40-47)
    "40": "09", "41": "09", "42": "09", "43": "09", "44": "09",
    "45": "09", "46": "09", "47": "09",
}


# ---------- search ----------

async def cmd_search(args: argparse.Namespace) -> None:
    pref = args.prefecture
    block = args.block or PREFECTURE_BLOCK.get(pref)
    if not block:
        raise SystemExit(f"unknown prefecture {pref!r} — use --block to override")

    sale_cls = (
        [s.strip() for s in args.sale_cls.split(",") if s.strip()]
        if args.sale_cls else None
    )

    store = BitStore()
    cfg = BitClientConfig()

    n_cards = 0
    n_pages = 0
    async with BitClient(cfg) as c:
        page = 1
        total: int | None = None
        seen = 0
        while True:
            try:
                result = await c.search(
                    prefecture_id=pref,
                    block_cls=block,
                    sale_cls=sale_cls,
                    page=page,
                    page_size=args.page_size,
                )
            except BitTransientError as e:
                # 페이지 범위 초과 시 BIT는 HTTP 500 — graceful stop
                logger.info("page %d aborted (%s) — assume end", page, e)
                break
            if total is None:
                total = result.get("total", 0)
                logger.info("BIT total=%d for prefecture=%s", total, pref)
            cards = result.get("properties") or []
            if not cards:
                logger.info("page %d empty — stop", page)
                break

            n = store.upsert_search_cards(cards, prefecture_code=pref)
            n_cards += n
            n_pages += 1
            seen += len(cards)
            logger.info(
                "page %d: cards=%d upserted=%d (total seen=%d/%d)",
                page, len(cards), n, seen, total,
            )

            if args.max_pages and n_pages >= args.max_pages:
                logger.info("max-pages %d reached — stop", args.max_pages)
                break
            if total and seen >= total:
                logger.info("seen all %d — stop", total)
                break
            page += 1
            if page > 100:
                logger.warning("safety stop at page 100")
                break

    print(f"DONE: {n_pages} pages, {n_cards} cards upserted (prefecture={pref}, block={block})")


# ---------- search-all (47도도부현 순회) ----------

async def cmd_search_all(args: argparse.Namespace) -> None:
    skip = set((args.skip or "").replace(" ", "").split(",")) - {""}
    prefs = [p for p in PREFECTURE_BLOCK.keys() if p not in skip]
    sale_cls = (
        [s.strip() for s in args.sale_cls.split(",") if s.strip()]
        if args.sale_cls else None
    )

    store = BitStore()
    cfg = BitClientConfig()
    grand_total = 0
    pref_results: list[tuple[str, int]] = []

    for pref in prefs:
        block = PREFECTURE_BLOCK[pref]
        pref_cards = 0
        try:
            # 도도부현마다 새 client (세션 컨텍스트 격리 — IP block 회복도 깨끗)
            async with BitClient(cfg) as c:
                page = 1
                total: int | None = None
                seen = 0
                while True:
                    try:
                        result = await c.search(
                            prefecture_id=pref, block_cls=block,
                            sale_cls=sale_cls,
                            page=page, page_size=args.page_size,
                        )
                    except BitTransientError as e:
                        logger.info("pref=%s page %d aborted (%s) — end", pref, page, e)
                        break
                    if total is None:
                        total = result.get("total", 0)
                    cards = result.get("properties") or []
                    if not cards:
                        break
                    n = store.upsert_search_cards(cards, prefecture_code=pref)
                    pref_cards += n
                    seen += len(cards)
                    logger.info(
                        "pref=%s page %d: upserted=%d (seen=%d/%d)",
                        pref, page, n, seen, total or 0,
                    )
                    if args.max_pages and page >= args.max_pages:
                        break
                    if total and seen >= total:
                        break
                    page += 1
                    if page > 100:
                        break
        except Exception as e:
            logger.warning("pref=%s failed: %s", pref, e)
        pref_results.append((pref, pref_cards))
        grand_total += pref_cards
        logger.info("pref=%s DONE %d cards (grand total=%d)", pref, pref_cards, grand_total)

    print("===== search-all summary =====")
    for pref, n in pref_results:
        if n > 0:
            print(f"  {pref}: {n}")
    print(f"TOTAL: {grand_total} cards across {len(prefs)} prefectures")


# ---------- photos ----------

async def cmd_photos(args: argparse.Namespace) -> None:
    store = BitStore()
    sel = (
        store.sb.table("jp_properties")
        .select("sale_unit_id,search_row")
        .limit(args.limit)
        .execute()
    )
    rows = sel.data or []
    if not rows:
        print("no jp_properties rows")
        return

    n_ok = 0
    for row in rows:
        sale_unit_id = row["sale_unit_id"]
        sr = row.get("search_row") or {}
        photo_url = sr.get("photo_url") if isinstance(sr, dict) else None
        if not photo_url:
            continue
        seq = (sr.get("photo_meta") or {}).get("seq") or 1
        rec = store.upload_photo_from_url(sale_unit_id, seq, photo_url)
        if rec:
            n_ok += 1
            logger.info("photo ok: %s seq=%d", sale_unit_id, seq)
    print(f"DONE: {n_ok} photos uploaded")


# ---------- backfill-details ----------

async def cmd_backfill_details(args: argparse.Namespace) -> None:
    pref = args.prefecture
    block = args.block or PREFECTURE_BLOCK.get(pref)
    if not block:
        raise SystemExit(f"unknown prefecture {pref!r}")

    store = BitStore()
    base = (
        store.sb.table("jp_properties")
        .select("sale_unit_id,search_row")
        .eq("prefecture_code", pref)
    )
    if args.force:
        # 전체 재처리 (좌표·新 필드 추가 시)
        sel = base.limit(args.limit).execute()
    else:
        # 미수집만 (latitude NULL인 것을 트리거 — detail에서 좌표 추출됨)
        sel = base.is_("latitude", "null").limit(args.limit).execute()
    rows = sel.data or []
    if not rows:
        print("no jp_properties with NULL detail_result")
        return

    logger.info("backfilling %d details (prefecture=%s)", len(rows), pref)
    cfg = BitClientConfig()
    n_ok = 0
    n_fail = 0
    async with BitClient(cfg) as c:
        for i, row in enumerate(rows):
            sale_unit_id = row["sale_unit_id"]
            sr = row.get("search_row") or {}
            court_id = sr.get("court_id") if isinstance(sr, dict) else None
            if not court_id:
                logger.warning("skip %s — no court_id in search_row", sale_unit_id)
                n_fail += 1
                continue
            try:
                d = await c.get_detail(
                    sale_unit_id=sale_unit_id,
                    court_id=court_id,
                    prefecture_id=pref,
                    block_cls=block,
                    warmup=(i == 0),  # 첫 회만 세션 워밍업
                )
                # html은 너무 크므로 detail_result에는 parsed만 저장
                store.upsert_detail(sale_unit_id, d.get("parsed") or {})
                n_ok += 1
                logger.info(
                    "  ok %s court=%s photos=%d",
                    sale_unit_id, court_id,
                    len((d.get("parsed") or {}).get("photos") or []),
                )
            except Exception as e:
                logger.warning("  fail %s: %s", sale_unit_id, e)
                n_fail += 1

    print(f"DONE: {n_ok} ok / {n_fail} fail")


# ---------- close-aged ----------

async def cmd_close_aged(args: argparse.Namespace) -> None:
    """fetched_at < SINCE_ISO인 매물을 closed 마킹.

    SINCE는 ISO datetime. 보통 daily script가 search-all 시작 timestamp를 전달.
    """
    store = BitStore()
    n = store.close_aged(args.since)
    print(f"DONE: {n} properties closed (fetched_at < {args.since})")


# ---------- backfill-details-all (모든 도도부현 단일 프로세스 백필) ----------

async def cmd_backfill_details_all(args: argparse.Namespace) -> None:
    """모든 도도부현에 걸쳐 latitude NULL인 매물을 단일 BitClient로 backfill.

    shell loop로 도도부현마다 process를 띄우면 매번 warmup이 필요해 느린데,
    이 명령은 도도부현마다 첫 매물만 warmup=True, 이후는 False로 가속.
    """
    store = BitStore()
    base = (
        store.sb.table("jp_properties")
        .select("sale_unit_id,search_row,prefecture_code")
    )
    if args.force:
        sel = base.limit(args.limit).execute()
    else:
        sel = base.is_("latitude", "null").limit(args.limit).execute()
    rows = sel.data or []
    if not rows:
        print("no jp_properties with NULL latitude")
        return

    # 도도부현별 group
    by_pref: dict[str, list[dict]] = {}
    for r in rows:
        p = r.get("prefecture_code")
        if not p:
            continue
        by_pref.setdefault(p, []).append(r)

    logger.info("backfilling %d details across %d prefectures",
                len(rows), len(by_pref))

    cfg = BitClientConfig()
    n_ok = 0
    n_fail = 0

    for pref, pref_rows in by_pref.items():
        block = PREFECTURE_BLOCK.get(pref)
        if not block:
            logger.warning("skip pref=%s — unknown block", pref)
            n_fail += len(pref_rows)
            continue
        logger.info("=== pref=%s (%d rows) ===", pref, len(pref_rows))
        try:
            async with BitClient(cfg) as c:
                for i, row in enumerate(pref_rows):
                    sale_unit_id = row["sale_unit_id"]
                    sr = row.get("search_row") or {}
                    court_id = sr.get("court_id") if isinstance(sr, dict) else None
                    if not court_id:
                        n_fail += 1
                        continue
                    try:
                        d = await c.get_detail(
                            sale_unit_id=sale_unit_id,
                            court_id=court_id,
                            prefecture_id=pref,
                            block_cls=block,
                            warmup=(i == 0),
                        )
                        store.upsert_detail(sale_unit_id, d.get("parsed") or {})
                        n_ok += 1
                        if n_ok % 20 == 0:
                            logger.info("  progress: %d ok / %d fail", n_ok, n_fail)
                    except Exception as e:
                        logger.warning("  fail %s: %s", sale_unit_id, e)
                        n_fail += 1
        except Exception as e:
            logger.warning("pref=%s client error: %s", pref, e)

    print(f"DONE: {n_ok} ok / {n_fail} fail")


# ---------- backfill derived_category (일본) ----------

async def cmd_backfill_categories(args: argparse.Namespace) -> None:
    """일본 매물 derived_category 일괄 계산 (別荘/空き家/리조트/離島).

    1) 룰 엔진 — bit/derived_category.derive_categories (무료)
    2) --llm 옵션: 룰 미분류 + sale_cls='2'(戸建て) 매물에 Gemini Flash Lite 보강.
       매물당 ~$0.00004. 1179건 중 戸建て 일부 → 비용 미미.
    --force: 기존 derived_category 있어도 재계산.
    """
    from bit.derived_category import derive_categories  # noqa: E402

    classifier = None
    if args.llm:
        from llm import GeminiJpClassifier  # noqa: E402
        classifier = GeminiJpClassifier()
        print("[+] LLM 보강 활성화 (Gemini 2.5 Flash Lite) "
              "— 룰 미분류 戸建て만 호출")

    store = BitStore()

    # prefecture name lookup — 47건, 한 번에 dict
    pref_rows = (
        store.sb.table("jp_prefectures").select("code,name").execute().data or []
    )
    pref_name_by_code: dict[str, str] = {r["code"]: r["name"] for r in pref_rows}

    n_rule_updated = 0
    n_llm_called = 0
    n_llm_updated = 0
    n_seen = 0
    page_size = max(50, int(args.batch))
    last_id: str | None = None

    while True:
        q = (
            store.sb.table("jp_properties")
            .select("sale_unit_id, sale_cls, sale_cls_label, address_text, "
                    "prefecture_code, sale_standard_price, derived_category")
            .order("sale_unit_id")
            .limit(page_size)
        )
        if last_id:
            q = q.gt("sale_unit_id", last_id)
        if not args.force:
            q = q.eq("derived_category", "{}")
        if args.limit and n_seen >= args.limit:
            break
        res = q.execute()
        rows = res.data or []
        if not rows:
            break

        for r in rows:
            n_seen += 1
            last_id = r["sale_unit_id"]
            cats = derive_categories(r)
            via_llm = False

            # 룰 미분류 + 戸建て + LLM 활성 → Gemini 호출
            if (not cats and classifier is not None
                    and str(r.get("sale_cls") or "") == "2"):
                pref_name = pref_name_by_code.get(
                    r.get("prefecture_code") or "", ""
                )
                llm_out = await asyncio.to_thread(
                    classifier.classify, r, pref_name=pref_name,
                )
                n_llm_called += 1
                cats = llm_out.get("categories") or []
                if cats:
                    via_llm = True
                    n_llm_updated += 1

            prev = r.get("derived_category") or []
            if sorted(prev) == sorted(cats):
                continue

            store.sb.table("jp_properties").update(
                {"derived_category": cats}
            ).eq("sale_unit_id", r["sale_unit_id"]).execute()

            if not via_llm and cats:
                n_rule_updated += 1
            done = n_rule_updated + n_llm_updated
            if done > 0 and done % 50 == 0:
                print(f"  ... rule={n_rule_updated} llm={n_llm_updated} "
                      f"(seen {n_seen}, llm_called {n_llm_called})")

        if args.limit and n_seen >= args.limit:
            break

    print(f"\n[done] jp backfill-categories → rule={n_rule_updated}, "
          f"llm={n_llm_updated}/{n_llm_called} called, seen={n_seen}")
    if classifier:
        print(f"  LLM cost: {classifier.cost_estimate()}")


# ---------- detail ----------

async def cmd_detail(args: argparse.Namespace) -> None:
    pref = args.prefecture
    block = args.block or PREFECTURE_BLOCK.get(pref)
    if not block:
        raise SystemExit(f"unknown prefecture {pref!r}")
    store = BitStore()
    cfg = BitClientConfig()
    async with BitClient(cfg) as c:
        d = await c.get_detail(
            sale_unit_id=args.sale_unit_id,
            court_id=args.court_id,
            prefecture_id=pref,
            block_cls=block,
        )
    if args.save_html:
        Path(args.save_html).write_text(d["html"], encoding="utf-8")
        print(f"  saved: {args.save_html} ({len(d['html'])} bytes)")
    store.upsert_detail(args.sale_unit_id, d)
    print(f"DONE: detail upsert for {args.sale_unit_id}")
    print("  title:", (d.get("parsed") or {}).get("title"))


# ---------- main ----------

async def _run_with_tracking(args: argparse.Namespace) -> None:
    """모든 cmd_* 함수를 crawl_runs 추적으로 감싸기.

    각 cmd 함수 자체는 건드리지 않고 main() 진입 직전에 한 번만 wrap.
    한국 ingest는 함수별 inline 패턴이라 totals(pages/rows 등) 세밀,
    일본은 1차로 wrapper만 — status/error 추적 가능하면 충분 (cron 검증 목적).
    향후 totals가 필요하면 함수별 보강.
    """
    store = BitStore()
    job_type = f"jp_{(args.cmd or 'unknown').replace('-', '_')}"
    # argparse가 args에 fn(callable), cmd(str) 등 모두 담음 — JSON 직렬화 가능한 것만 params로
    params = {k: v for k, v in vars(args).items()
              if k != "fn" and isinstance(v, (str, int, float, bool, type(None)))}
    run_id = store.start_run(job_type, params)
    try:
        await args.fn(args)
        store.finish_run(run_id)
    except Exception as e:
        store.finish_run(run_id, status="failed", error=str(e))
        raise


def main() -> None:
    p = argparse.ArgumentParser(prog="jp_ingest")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search")
    s.add_argument("--prefecture", required=True, help="JIS code (e.g. 13)")
    s.add_argument("--block", help="block code (auto if omitted)")
    s.add_argument("--sale-cls", help="comma-separated, e.g. 1,2,3")
    s.add_argument("--max-pages", type=int, default=None)
    s.add_argument("--page-size", type=int, default=30)
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("search-all")
    s.add_argument("--skip", help="comma-separated prefecture codes to skip")
    s.add_argument("--sale-cls", help="comma-separated, e.g. 1,2,3")
    s.add_argument("--max-pages", type=int, default=12)
    s.add_argument("--page-size", type=int, default=30)
    s.set_defaults(fn=cmd_search_all)

    s = sub.add_parser("photos")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(fn=cmd_photos)

    s = sub.add_parser("close-aged")
    s.add_argument("--since", required=True, help="ISO datetime (e.g. 2026-05-11T05:30:00Z)")
    s.set_defaults(fn=cmd_close_aged)

    s = sub.add_parser("backfill-details-all")
    s.add_argument("--limit", type=int, default=2000)
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_backfill_details_all)

    s = sub.add_parser("backfill-details")
    s.add_argument("--prefecture", default="13")
    s.add_argument("--block", help="auto if omitted")
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--force", action="store_true", help="re-fetch all (default: latitude NULL only)")
    s.set_defaults(fn=cmd_backfill_details)

    s = sub.add_parser("detail")
    s.add_argument("sale_unit_id")
    s.add_argument("court_id")
    s.add_argument("--prefecture", required=True)
    s.add_argument("--block", help="auto if omitted")
    s.add_argument("--save-html", help="save raw HTML to path")
    s.set_defaults(fn=cmd_detail)

    s = sub.add_parser("backfill-categories",
                       help="derived_category 일괄 계산 (別荘/空き家/리조트/離島)")
    s.add_argument("--batch", type=int, default=500)
    s.add_argument("--limit", type=int, default=None)
    s.add_argument("--force", action="store_true")
    s.add_argument("--llm", action="store_true",
                   help="룰 미분류 戸建て(sale_cls=2)에 Gemini Flash Lite 보강 "
                        "(GEMINI_API_KEY 필요)")
    s.set_defaults(fn=cmd_backfill_categories)

    args = p.parse_args()
    asyncio.run(_run_with_tracking(args))


if __name__ == "__main__":
    main()
