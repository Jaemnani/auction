"""1회성 read-only 검증 — 웹 필터(queries.ts applyFilters)가 실제 DB에서
의도대로 동작하는지 PostgREST로 직접 재현해 확인.

실행:
    /Users/jaemoonyeah/workspace/venv_common/bin/python crawler/scripts/verify_filters.py

데이터 변경 없음. count(exact)만 비교.
"""

from __future__ import annotations

import os
from pathlib import Path

from supabase import create_client

for line in (Path(__file__).resolve().parent.parent.parent / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))

# 웹과 동일하게 anon 키로 검증 (RLS/노출 동작까지 같이 봄). 없으면 service.
KEY = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_KEY") \
    or os.environ["SUPABASE_SERVICE_KEY"]
sb = create_client(os.environ["SUPABASE_URL"], KEY)


def cnt(**build) -> int | str:
    """build: callable(q)->q. count(exact) 반환. 에러 시 메시지."""
    try:
        q = sb.table("properties").select("id", count="exact").is_("deleted_at", "null")
        q = build["fn"](q)
        r = q.range(0, 0).execute()
        return r.count
    except Exception as e:  # noqa: BLE001
        return f"ERR: {str(e)[:120]}"


base = cnt(fn=lambda q: q)
print(f"기준: deleted_at IS NULL 공고중 매물 = {base}건\n")

checks: list[tuple[str, object]] = []

# 1) sale_rate_pct generated column 존재 + 필터 동작 (마이그레이션 0014)
checks.append(("0014 sale_rate_pct 컬럼 존재", cnt(fn=lambda q: q.not_.is_("sale_rate_pct", "null"))))
checks.append(("매각가율 >= 70%", cnt(fn=lambda q: q.gte("sale_rate_pct", 70))))
checks.append(("매각가율 40~70%", cnt(fn=lambda q: q.gte("sale_rate_pct", 40).lte("sale_rate_pct", 70))))

# 2) 가격/감정가/유찰 범위 (만원→원 ×10000)
checks.append(("감정가 1억~5억", cnt(fn=lambda q: q.gte("appraisal_amount", 100_000_000).lte("appraisal_amount", 500_000_000))))
checks.append(("유찰 >= 2회", cnt(fn=lambda q: q.gte("fail_count", 2))))

# 3) 지역/용도/법원 eq
checks.append(("sd=11(서울)", cnt(fn=lambda q: q.eq("sd_code", "11"))))
checks.append(("usage_lcl=20000(건물)", cnt(fn=lambda q: q.eq("usage_lcl_cd", "20000"))))

# 4) 법원 — 임베드 inner join eq (queries.ts:31)
checks.append(("court 임베드 eq (inner)", cnt(fn=lambda q:
    sb.table("properties").select("id, cases:case_id!inner(court_code)", count="exact")
      .is_("deleted_at", "null").eq("cases.court_code", "B000210"))))

# 5) usage_nm in() — 콤마 포함 값 직렬화 (postgrest 따옴표 처리 확인)
checks.append(("usage_nm in [아파트,오피스텔]", cnt(fn=lambda q: q.in_("usage_nm", ["아파트", "오피스텔"]))))
checks.append(("usage_nm in [콤마포함값]", cnt(fn=lambda q: q.in_("usage_nm", ["연립주택,다세대,빌라"]))))

# 6) derived overlaps
checks.append(("derived overlaps {townhouse}", cnt(fn=lambda q: q.overlaps("derived_category", ["townhouse"]))))

# 7) exclude_flags — NULL 포함 OR (queries.ts:99)
checks.append(("exclude share_sale (NULL포함)", cnt(fn=lambda q:
    q.or_("risk_flags.is.null,risk_flags.not.ov.{share_sale}"))))

# 8) addr_state
checks.append(("road_addr NOT NULL", cnt(fn=lambda q: q.not_.is_("road_addr", "null"))))

# 9) q 키워드 — sanitize 후 or ilike
checks.append(("q='강남구' 주소검색", cnt(fn=lambda q:
    q.or_("road_addr.ilike.%강남구%,conv_addr.ilike.%강남구%,lot_addr.ilike.%강남구%"))))

# 10) risk_flags 오분류 실측 — farm_land가 건물(20000)에 붙는지
checks.append(("[BUG실측] farm_land & lcl=20000(건물)", cnt(fn=lambda q:
    q.contains("risk_flags", ["farm_land"]).eq("usage_lcl_cd", "20000"))))
checks.append(("[참고] farm_land & lcl=10000(토지)", cnt(fn=lambda q:
    q.contains("risk_flags", ["farm_land"]).eq("usage_lcl_cd", "10000"))))

# 11) anon이 detail_result 원본을 읽을 수 있는가 (RLS 노출 실측)
try:
    leak = sb.table("properties").select("detail_result").not_.is_("detail_result", "null").limit(1).execute()
    has = bool(leak.data and leak.data[0].get("detail_result"))
    checks.append(("[보안실측] anon detail_result 읽힘?", "YES (노출)" if has else "no"))
except Exception as e:  # noqa: BLE001
    checks.append(("[보안실측] anon detail_result 읽힘?", f"막힘: {str(e)[:60]}"))

print(f"{'검증 항목':40s} 결과")
print("-" * 60)
for name, res in checks:
    print(f"{name:40s} {res}")
print("\n사용 키 role:", "service" if KEY == os.environ.get("SUPABASE_SERVICE_KEY") else "anon/public")
