"""
seed.py — courtauction 데이터 적재 CLI.

서브커맨드:
    masters              마스터 코드 일괄 수집 (법원/시도/시군구/용도 대중소)
        --include-emd    + 시군구별 읍면동 (시간 다소 소요)
    search               검색 결과 페이지 단위로 jsonl dump
        --kind real_estate|movables  (default real_estate)
        --court CODE                 (옵션, 특정 법원만)
        --max-pages N                (옵션, 페이지 제한)
        --page-size N                (default 100)
    detail COURT CASE_NO SEQ        단일 사건/물건 상세 dump

산출물:
    crawler/data/seed/<job>_<timestamp>.jsonl
    crawler/data/raw/...           (모든 raw 응답)
    crawler/data/dead_letter.jsonl (영구 실패)

실행:
    /Users/jaemoonyeah/workspace/venv_common/bin/python crawler/scripts/seed.py masters
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# 패키지 import (src/ 레이아웃)
SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from courtauction import ClientConfig, CourtAuctionClient  # noqa: E402

CRAWLER_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = CRAWLER_ROOT / "data"
SEED_DIR = DATA_DIR / "seed"
RAW_DIR = DATA_DIR / "raw"
DEAD_LETTER = DATA_DIR / "dead_letter.jsonl"


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _writer(name: str):
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    path = SEED_DIR / f"{name}_{_stamp()}.jsonl"
    fp = path.open("w", encoding="utf-8")

    def write(record: dict) -> None:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        fp.flush()

    return path, write, fp


def _make_client(*, save_raw: bool) -> CourtAuctionClient:
    return CourtAuctionClient(ClientConfig(
        save_dir=RAW_DIR if save_raw else None,
        dead_letter_path=DEAD_LETTER,
    ))


# ---------- masters ----------

async def cmd_masters(args: argparse.Namespace) -> None:
    path, write, fp = _writer("masters")
    started = time.monotonic()

    async with _make_client(save_raw=args.save_raw) as c:
        # 1) 법원 목록 — B prefix 부동산, O prefix 다른 분류
        for prefix in ("00079B", "00079O"):
            try:
                courts = await c.list_courts(prefix)
            except Exception as e:
                print(f"  ! courts({prefix}) failed: {e}")
                continue
            for row in courts:
                write({"type": "court", "prefix": prefix, **row})
            print(f"  + courts({prefix}): {len(courts)}")

        # 2) 시도
        try:
            sido = await c.list_sido()
        except Exception as e:
            print(f"  ! sido failed: {e}")
            sido = []
        for row in sido:
            write({"type": "sido", **row})
        print(f"  + sido: {len(sido)}")

        # 3) 시군구 (시도별)
        sgg_total = 0
        sgg_by_sd: dict[str, list] = {}
        for sd in sido:
            sd_code = sd.get("code")
            try:
                sgg = await c.list_sigungu(sd_code)
            except Exception as e:
                print(f"  ! sgg({sd_code}) failed: {e}")
                continue
            sgg_by_sd[sd_code] = sgg
            for row in sgg:
                write({"type": "sgg", "sd_code": sd_code, **row})
            sgg_total += len(sgg)
        print(f"  + sgg: {sgg_total} (across {len(sgg_by_sd)} sido)")

        # 4) 읍면동 (옵션 — 시간 소요)
        if args.include_emd:
            emd_total = 0
            for sd_code, sgg_list in sgg_by_sd.items():
                for sgg in sgg_list:
                    sgg_code = sgg.get("code")
                    try:
                        emd = await c.list_emd(sgg_code)
                    except Exception as e:
                        print(f"  ! emd({sgg_code}) failed: {e}")
                        continue
                    for row in emd:
                        write({"type": "emd", "sd_code": sd_code,
                               "sgg_code": sgg_code, **row})
                    emd_total += len(emd)
            print(f"  + emd: {emd_total}")

        # 5) 용도 (대→중→소 트리)
        try:
            lcl = await c.list_usage_lcl()
        except Exception as e:
            print(f"  ! lcl failed: {e}")
            lcl = []
        for row in lcl:
            write({"type": "usage_lcl", **row})
        print(f"  + usage_lcl: {len(lcl)}")

        mcl_total = scl_total = 0
        for l in lcl:
            l_code = l.get("code")
            try:
                mcl = await c.list_usage_mcl(l_code)
            except Exception as e:
                print(f"  ! mcl({l_code}) failed: {e}")
                continue
            for row in mcl:
                write({"type": "usage_mcl", "lcl_code": l_code, **row})
            mcl_total += len(mcl)

            for m in mcl:
                m_code = m.get("code")
                try:
                    scl = await c.list_usage_scl(m_code)
                except Exception as e:
                    print(f"  ! scl({m_code}) failed: {e}")
                    continue
                for row in scl:
                    write({"type": "usage_scl",
                           "lcl_code": l_code, "mcl_code": m_code, **row})
                scl_total += len(scl)
        print(f"  + usage_mcl: {mcl_total}, usage_scl: {scl_total}")

    fp.close()
    elapsed = time.monotonic() - started
    print(f"\n[done] masters → {path} ({elapsed:.1f}s)")


# ---------- search ----------

async def cmd_search(args: argparse.Namespace) -> None:
    path, write, fp = _writer(f"search_{args.kind}")
    started = time.monotonic()

    async with _make_client(save_raw=args.save_raw) as c:
        n_rows = 0
        n_pages = 0
        async for page in c.search_iter(
            kind=args.kind,
            page_size=args.page_size,
            cort_ofc_cd=args.court,
            max_pages=args.max_pages,
        ):
            rows = page.get("dlt_srchResult") or []
            page_info = page.get("dma_pageInfo") or {}
            n_pages += 1
            for row in rows:
                write({"type": f"search_{args.kind}",
                       "page_no": page_info.get("pageNo"), **row})
            n_rows += len(rows)
            print(f"  page {page_info.get('pageNo')}/"
                  f"{page_info.get('totalCnt')} → +{len(rows)} rows "
                  f"(running total {n_rows})")

    fp.close()
    elapsed = time.monotonic() - started
    print(f"\n[done] search → {path}: {n_rows} rows in {n_pages} pages ({elapsed:.1f}s)")


# ---------- detail ----------

async def cmd_detail(args: argparse.Namespace) -> None:
    path, write, fp = _writer(f"detail_{args.court}_{args.case_no}")

    async with _make_client(save_raw=args.save_raw) as c:
        result = await c.get_case_detail(args.court, args.case_no, args.seq)
        write({"court": args.court, "case_no": args.case_no,
               "dspsl_gds_seq": args.seq, "result": result})

    fp.close()
    print(f"[done] detail → {path}")


# ---------- main ----------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ap = argparse.ArgumentParser(description="courtauction.go.kr 데이터 적재")
    ap.add_argument("--save-raw", action="store_true",
                    help="모든 raw 응답을 data/raw/에 저장 (디버깅용)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_m = sub.add_parser("masters", help="마스터 코드 dump")
    p_m.add_argument("--include-emd", action="store_true",
                     help="읍면동까지 (시간 소요)")
    p_m.set_defaults(func=cmd_masters)

    p_s = sub.add_parser("search", help="검색 결과 dump")
    p_s.add_argument("--kind", choices=("real_estate", "movables"),
                     default="real_estate")
    p_s.add_argument("--court", default=None, help="법원코드 필터 (예 B000210)")
    p_s.add_argument("--page-size", type=int, default=50)
    p_s.add_argument("--max-pages", type=int, default=None)
    p_s.set_defaults(func=cmd_search)

    p_d = sub.add_parser("detail", help="단일 사건/물건 상세 dump")
    p_d.add_argument("court", help="법원코드 (예 B000210)")
    p_d.add_argument("case_no", help="사건번호 표시 (예 2023타경6292)")
    p_d.add_argument("seq", help="매물순번 (보통 1)")
    p_d.set_defaults(func=cmd_detail)

    args = ap.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
