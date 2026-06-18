-- ============================================================================
-- 0014 — 매각가율(sale_rate_pct) generated column + 인덱스
-- 목적: 매각가율 필터/정렬을 DB 레벨로. (기존엔 web에서 페이지 fetch 후 JS 후처리
--       → 페이지네이션 total 오류 + 페이지별 누락. queries.ts 참조.)
--
-- 매각가율(%) = 최저매각가 / 감정가 × 100. 감정가 0/NULL 또는 최저가 NULL → NULL.
-- numeric 나눗셈은 immutable → STORED generated column 가능.
--
-- 적용: Supabase Dashboard → SQL Editor 에 통째로 붙여 Run.
-- ============================================================================

alter table properties
  add column if not exists sale_rate_pct numeric(8,2)
  generated always as (
    case
      when appraisal_amount > 0 and min_sale_price is not null
      then (min_sale_price::numeric / appraisal_amount * 100)
      else null
    end
  ) stored;

comment on column properties.sale_rate_pct is
  '매각가율(%) = min_sale_price / appraisal_amount × 100. 감정가 0/NULL 시 NULL. generated stored.';

-- 필터(gte/lte) + 정렬(discount_asc/desc) 가속
create index if not exists properties_sale_rate_pct_idx
  on properties (sale_rate_pct)
  where deleted_at is null;
