"""1회성 audit — Phase 1-A(차량/건물) + Phase 1-C(has_pdf) root cause 확정.

실행:
    /Users/jaemoonyeah/workspace/venv_common/bin/python crawler/scripts/audit_filters.py

읽기 전용. 데이터 변경 없음.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

from supabase import create_client

# .env 수동 로드
for line in (Path(__file__).resolve().parent.parent.parent / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))

sb = create_client(
    os.environ["SUPABASE_URL"],
    os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_KEY"],
)


def fetch_all(table: str, columns: str, **filters):
    """range로 페이징해 모든 row 가져오기."""
    PAGE = 1000
    out: list[dict] = []
    offset = 0
    while True:
        q = sb.table(table).select(columns)
        for k, v in filters.items():
            q = getattr(q, k)(*v) if isinstance(v, tuple) else q.eq(k, v)
        r = q.range(offset, offset + PAGE - 1).execute()
        rows = r.data or []
        if not rows:
            break
        out.extend(rows)
        if len(rows) < PAGE:
            break
        offset += PAGE
        if offset > 100_000:  # safety
            break
    return out


print("=" * 70)
print("AUDIT #1 — 한국 properties.usage_lcl_cd 분포")
print("=" * 70)
rows = fetch_all("properties", "usage_lcl_cd")
# deleted_at filter — 별도로 다시 fetch (filter 추가)
not_deleted = sb.table("properties").select("usage_lcl_cd", count="exact") \
    .is_("deleted_at", "null").range(0, 0).execute()
print(f"  공고중 매물 (deleted_at IS NULL) 총: {not_deleted.count}건")
print(f"  fetched (all): {len(rows)}건")
lcl_counter = Counter(r.get("usage_lcl_cd") for r in rows)
for code, cnt in lcl_counter.most_common():
    label = {"10000": "토지", "20000": "건물", "30000": "차량 및 운송장비",
             "40000": "기타", None: "(null)"}.get(code, f"unknown:{code}")
    print(f"  {code!s:>10} ({label:20s}) : {cnt}")
print()

print("=" * 70)
print("AUDIT #2 — 차량(lcl=30000) 매물의 mcl/scl 분포")
print("=" * 70)
veh_rows = fetch_all("properties", "usage_lcl_cd,usage_mcl_cd,usage_scl_cd",
                    usage_lcl_cd="30000")
print(f"  차량 매물: {len(veh_rows)}건")
mcl_counter = Counter(r.get("usage_mcl_cd") for r in veh_rows)
print("  mcl 분포 (top 10):")
for code, cnt in mcl_counter.most_common(10):
    print(f"    {code!s:>10} : {cnt}")
scl_counter = Counter(r.get("usage_scl_cd") for r in veh_rows)
print("  scl 분포 (top 10):")
for code, cnt in scl_counter.most_common(10):
    print(f"    {code!s:>10} : {cnt}")
print()

print("=" * 70)
print("AUDIT #3 — 의심 패턴: lcl=20000(건물)인데 mcl이 차량 코드 류")
print("=" * 70)
# mcl이 301* / 311* 시작 (차량 의심)
sus1 = sb.table("properties") \
    .select("docid,usage_lcl_cd,usage_mcl_cd,usage_scl_cd,building_summary,conv_addr") \
    .eq("usage_lcl_cd", "20000") \
    .like("usage_mcl_cd", "301%").limit(10).execute()
print(f"  mcl=301* 매물 (건물 lcl인데 차량 mcl): {len(sus1.data)}건 (샘플)")
for r in sus1.data[:5]:
    print(f"    {r.get('docid')[:25]} lcl={r['usage_lcl_cd']} mcl={r['usage_mcl_cd']} scl={r['usage_scl_cd']}")
    print(f"      addr={r.get('conv_addr','')[:50]}")
    print(f"      bld={(r.get('building_summary') or '')[:50]}")
sus2 = sb.table("properties") \
    .select("docid,usage_lcl_cd,usage_mcl_cd,building_summary,conv_addr") \
    .eq("usage_lcl_cd", "20000") \
    .like("usage_mcl_cd", "311%").limit(10).execute()
print(f"  mcl=311* 매물: {len(sus2.data)}건 (샘플)")
for r in sus2.data[:5]:
    print(f"    {r.get('docid')[:25]} mcl={r['usage_mcl_cd']}")
# building_summary에 '차량' 또는 '자동차' 포함
sus3 = sb.table("properties") \
    .select("docid,usage_lcl_cd,usage_mcl_cd,building_summary") \
    .eq("usage_lcl_cd", "20000") \
    .ilike("building_summary", "%차량%").limit(10).execute()
print(f"  건물 lcl + building_summary에 '차량' 포함: {len(sus3.data)}건 (샘플)")
for r in sus3.data[:5]:
    print(f"    {r.get('docid')[:25]} bld={(r.get('building_summary') or '')[:60]}")
print()

print("=" * 70)
print("AUDIT #4 — 일본 has_three_set_pdf 키 분포")
print("=" * 70)
jp_total = sb.table("jp_properties").select("sale_unit_id", count="exact") \
    .range(0, 0).execute()
jp_with_detail = sb.table("jp_properties").select("sale_unit_id", count="exact") \
    .not_.is_("detail_result", "null").range(0, 0).execute()
print(f"  jp_properties 총: {jp_total.count}건")
print(f"  detail_result NOT NULL: {jp_with_detail.count}건")

# has_pdf 값 분포 (detail 있는 row 기준) — fetch_all helper의 not.is 문법
# 우회: 직접 페이징
PAGE = 1000
jp_rows: list[dict] = []
offset = 0
while True:
    rr = sb.table("jp_properties") \
        .select("sale_unit_id,has_pdf:detail_result->>has_three_set_pdf") \
        .not_.is_("detail_result", "null") \
        .range(offset, offset + PAGE - 1).execute()
    rows = rr.data or []
    if not rows: break
    jp_rows.extend(rows)
    if len(rows) < PAGE: break
    offset += PAGE
pdf_counter = Counter(r.get("has_pdf") for r in jp_rows)
print(f"  has_three_set_pdf 값 분포 (detail 있는 {len(jp_rows)}건):")
for v, cnt in pdf_counter.most_common(10):
    print(f"    {v!r:>30} : {cnt}")

# detail에 has_three_set_pdf 키 자체가 있는 row vs 없는 row
null_count = pdf_counter.get(None, 0)
print(f"  -> NULL: {null_count}건 (detail은 있지만 has_three_set_pdf 키 없음)")
print(f"  -> 'true': {pdf_counter.get('true', 0)}건")
print(f"  -> 'false': {pdf_counter.get('false', 0)}건")
print()

print("=" * 70)
print("DONE")
print("=" * 70)
