-- ============================================================================
-- 0022 — 낙찰 예상가 (배치 예측 저장) + 지역 실거래 시세 집계 view
--
-- 모델: LightGBM quantile 회귀(α=0.1/0.5/0.9), 타깃은 매각가율
--       (sale_amount/appraisal_amount) — 예측치 × 감정가로 가격 복원.
--       학습 crawler/scripts/estimate.py train (주 1회), 예측 estimate.py predict
--       (run_daily.sh 말미, 활성 매물 전량). 표본 얇은 세그먼트는
--       auction_stats_by_region 평균 매각가율 폴백(method='region_avg').
--
-- properties 컬럼 추가 대신 별도 테이블 — hot 테이블 스키마 변경/PostgREST
-- 캐시 리스크 회피, model_version 관리 용이.
--
-- 적용(시놀로지): docker exec -i auction-db psql -U postgres -d postgres < 0022_*.sql
-- ============================================================================

create table if not exists property_estimates (
  property_id        uuid primary key references properties(id) on delete cascade,
  estimated_price    numeric(20,0),   -- 예상 낙찰가 (원, α=0.5)
  estimated_low      numeric(20,0),   -- α=0.1
  estimated_high     numeric(20,0),   -- α=0.9
  estimated_rate_pct numeric(6,1),    -- 예상 매각가율 (%)
  method             text not null check (method in ('model', 'region_avg')),
  model_version      text,
  sample_count       int,             -- 같은 (시군구, 용도) 학습 표본 수 — 신뢰도 표시용
  features_used      jsonb,           -- 사용/결측 피처 (디버깅·UI 안내용)
  predicted_at       timestamptz not null default now()
);

alter table property_estimates enable row level security;
do $$ begin
  drop policy if exists "public read" on property_estimates;
  create policy "public read" on property_estimates
    for select to anon, authenticated using (true);
end $$;

-- 지역 실거래 시세 — (시군구, 유형, 분기)별 ㎡당 중위가 (만원/㎡).
-- 모델 피처 + (추후) 상세 페이지 참고 표시용. molit_deals(0020) 축적분 집계.
create or replace view molit_price_by_region as
select
  lawd_cd,
  deal_type,
  to_char(date_trunc('quarter', deal_date), 'YYYY"Q"Q') as quarter,
  date_trunc('quarter', deal_date)::date                as quarter_start,
  count(*)                                              as deal_count,
  round(percentile_cont(0.5) within group
    (order by amount_manwon / nullif(area_m2, 0))::numeric, 1) as median_manwon_per_m2
from molit_deals
where amount_manwon > 0 and area_m2 > 0 and deal_date is not null
group by lawd_cd, deal_type, date_trunc('quarter', deal_date);

grant select on molit_price_by_region to anon, authenticated;

notify pgrst, 'reload schema';
