#!/usr/bin/env python
"""매각물건명세서 수집·파싱 → property_tenancy (0026).

사용:
  python scripts/spec_sheet.py fetch --docid B000210...       # 1건
  python scripts/spec_sheet.py fetch --limit 5                # 공개창 미수집분 N건
  python scripts/spec_sheet.py parse-file coords.json         # 저장된 캡처만 파싱(오프라인)

⚠ 요청량 주의 — 매물당 30~60초, 법원 사이트 UI 를 실제로 클릭한다.
   일괄 대량 수집은 차단 위험이 크다. 기본 limit 이 작은 이유.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from spec_sheet.collect import capture_spec_sheet  # noqa: E402
from spec_sheet.parse import parse_spec_sheet      # noqa: E402

logger = logging.getLogger(__name__)

# 명세서 공개 = 매각기일 1주 전부터 (web 의 SPEC_OPEN_DAYS 와 같은 규칙)
SPEC_OPEN_DAYS = 7


def _sb():
    from supabase import create_client
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_(SERVICE_)KEY env required")
    # .env 의 :8080 은 NAS LAN 전용 — 집 밖/핫스팟에서는 Connection refused.
    # 외부에서는 https(443, DSM→Caddy→PostgREST)로 붙어야 한다.
    if ":8080" in url:
        print(f"[warn] SUPABASE_URL 이 LAN 전용 주소입니다: {url}\n"
              "       LAN 밖이면 다음처럼 덮어쓰세요:\n"
              '       SUPABASE_URL="https://jeremylab.synology.me" python '
              "crawler/scripts/spec_sheet.py ...", file=sys.stderr)
    return create_client(url, key)


def _targets(sb, limit: int, docid: str | None) -> list[dict]:
    """수집 대상 — 명세서 공개창(오늘~+7일) 안이면서 아직 미수집인 활성 매물."""
    q = (sb.table("properties")
         .select("id, docid, sale_date, cases:case_id ( case_no, courts:court_code ( name ) )")
         .is_("deleted_at", "null"))
    if docid:
        q = q.eq("docid", docid)
    else:
        today = date.today()
        q = (q.gte("sale_date", today.isoformat())
              .lte("sale_date", (today + timedelta(days=SPEC_OPEN_DAYS)).isoformat())
              .order("sale_date"))
    rows = (q.limit(max(limit * 4, 20)).execute().data) or []
    if docid:
        return rows[:1]
    # 이미 수집된 것 제외 (온디맨드 캐시라 재수집은 별도 정책)
    ids = [r["id"] for r in rows]
    done: set[str] = set()
    for i in range(0, len(ids), 150):   # uuid .in_() 150 초과 시 nginx 414
        got = (sb.table("property_tenancy").select("property_id")
               .in_("property_id", ids[i:i + 150]).execute().data) or []
        done.update(g["property_id"] for g in got)
    return [r for r in rows if r["id"] not in done][:limit]


def _payload(prop: dict, spec, viewer_url: str | None) -> dict:
    return {
        "property_id": prop["id"],
        "lien_date": spec.lien_date,
        "lien_kind": spec.lien_kind,
        "demand_deadline": spec.demand_deadline,
        "tenants": [
            {"name": t.name, "deposit": t.deposit,
             "move_in_dates": t.move_in_dates, "other_dates": t.other_dates,
             "raw": t.raw}
            for t in spec.tenants
        ],
        "has_tenant_block": spec.has_tenant_block,
        "verdict": spec.opposable_risk(),
        "confidence": spec.confidence,
        "notes": spec.notes,
        "raw_text": spec.raw_text[:20000],
        "viewer_url": viewer_url,
    }


async def cmd_fetch(args: argparse.Namespace) -> None:
    sb = _sb()
    targets = _targets(sb, args.limit, args.docid)
    if not targets:
        print("[done] 대상 없음 (공개창 안 미수집 매물)")
        return
    print(f"[plan] {len(targets)}건 수집 (매물당 30~60초)")

    saved = failed = 0
    for i, p in enumerate(targets, 1):
        case_no = ((p.get("cases") or {}).get("case_no")) or ""
        court = (((p.get("cases") or {}).get("courts")) or {}).get("name") or ""
        started = time.monotonic()
        cap = await capture_spec_sheet(court, case_no,
                                       sale_date=p.get("sale_date"),
                                       headless=not args.headed)
        if not cap.ok:
            failed += 1
            print(f"  [{i}/{len(targets)}] {case_no} 실패 — {cap.reason}")
            continue
        spec = parse_spec_sheet(cap.nodes)
        if args.dry_run:
            print(f"  [{i}/{len(targets)}] {case_no} "
                  f"lien={spec.lien_date} verdict={spec.opposable_risk()} "
                  f"conf={spec.confidence} ({time.monotonic()-started:.0f}s)")
            continue
        try:
            sb.table("property_tenancy").upsert(
                _payload(p, spec, cap.viewer_url)).execute()
            saved += 1
            print(f"  [{i}/{len(targets)}] {case_no} → {spec.opposable_risk()} "
                  f"({spec.confidence}, {time.monotonic()-started:.0f}s)")
        except Exception as e:  # noqa: BLE001
            if "42P01" in str(e) or "does not exist" in str(e):
                print("[fatal] property_tenancy 테이블 없음 — "
                      "0026_property_tenancy.sql 을 NAS psql 로 먼저 적용하세요")
                sys.exit(1)
            failed += 1
            print(f"  [{i}/{len(targets)}] {case_no} 저장 실패: {e}")

    print(f"[done] spec-sheet — saved={saved} failed={failed}")


def cmd_parse_file(args: argparse.Namespace) -> None:
    """이미 저장된 캡처(JSON)만 파싱 — 법원 사이트 무접촉, 파서 개발용."""
    nodes = json.loads(Path(args.path).read_text())
    spec = parse_spec_sheet(nodes)
    print(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2))
    print(f"\nverdict = {spec.opposable_risk()}")


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="매각물건명세서 수집·파싱")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="법원 사이트에서 수집 → property_tenancy")
    f.add_argument("--docid", help="특정 매물만")
    f.add_argument("--limit", type=int, default=3, help="최대 건수 (기본 3 — 차단 위험)")
    f.add_argument("--headed", action="store_true", help="브라우저 표시 (디버깅)")
    f.add_argument("--dry-run", action="store_true", help="저장 없이 결과만")
    f.set_defaults(func=lambda a: asyncio.run(cmd_fetch(a)))

    p = sub.add_parser("parse-file", help="저장된 캡처 JSON 파싱 (오프라인)")
    p.add_argument("path")
    p.set_defaults(func=cmd_parse_file)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
