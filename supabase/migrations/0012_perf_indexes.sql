-- ============================================================================
-- 0012 — 성능 인덱스 보강
-- 목적: 자주 사용되는 필터·정렬 조합에서 풀스캔 회피.
-- 적용: Supabase Dashboard → SQL Editor 에 통째로 붙여 Run.
-- 0011 에 properties.risk_flags GIN 이미 존재 → 중복 생성 X.
-- ============================================================================

-- (한국) 지도 bbox + 용도/가격 동시 필터
-- 단일 GIST(location) 만으로는 다중 컬럼 활용 어려움.
-- 좌표(lng/lat) 일반 인덱스 + 자주 쓰는 필터 컬럼 묶음.
create index if not exists properties_lng_lat_usage_price_idx
  on properties (longitude, latitude, usage_lcl_cd, min_sale_price)
  where deleted_at is null;

-- (한국) 리스트 정렬 — sale_date 기준 + 용도 보조
-- "/?usage_lcl=20000&sort=sale_date" 류 빈번 쿼리 가속
create index if not exists properties_usage_sale_date_idx
  on properties (usage_lcl_cd, sale_date desc nulls last, min_sale_price)
  where deleted_at is null;

-- (한국) sgg + 용도 — 지역별 매물 카운트
create index if not exists properties_sd_sgg_usage_idx
  on properties (sd_code, sgg_code, usage_lcl_cd)
  where deleted_at is null;

-- (일본) bid_period_start 정렬 — 일본 리스트 기본 정렬 가속
create index if not exists jp_properties_bid_period_start_idx
  on jp_properties (bid_period_start desc nulls last);

-- (일본) prefecture + sale_cls + 가격 — 일본 필터 흔한 조합
create index if not exists jp_properties_pref_cls_price_idx
  on jp_properties (prefecture_code, sale_cls, sale_standard_price);
