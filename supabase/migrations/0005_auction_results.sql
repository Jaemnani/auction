-- ============================================================================
-- 0005 — 매각결과 (종결 사건) 캐시 + 인근 낙찰 통계 집계 view
--
-- courtauction PGJ158M02 매각결과검색 endpoint로 받은 종결 매물을 별도 테이블에 저장.
-- 우리 properties 테이블은 "공고중" 매물만 다루고, 통계는 "종결" 매물에서 추출.
-- ============================================================================

create table if not exists sale_results (
  id                  uuid primary key default uuid_generate_v4(),
  docid               text unique,                          -- 시스템 유니크
  court_code          text not null,
  case_no             text not null,                        -- srnSaNo (예 "2023타경6292")
  maemul_ser          smallint not null,
  appraisal_amount    numeric(20,0),                        -- gamevalAmt
  min_sale_price      numeric(20,0),                        -- minmaePrice (마지막 회차)
  sale_amount         numeric(20,0),                        -- maeAmt (실제 낙찰가, 0=유찰)
  fail_count          smallint,                             -- yuchalCnt
  bidder_count        smallint,                             -- inqCnt (응찰자 수, 추정)
  sale_date           date,                                 -- maeGiil
  result_status_cd    text,                                 -- mulStatcd
  in_progress_yn      text,                                 -- mulJinYn
  usage_lcl_cd        text,
  usage_mcl_cd        text,
  usage_scl_cd        text,
  sd_code             text,
  sgg_code            text,
  emd_code            text,
  conv_addr           text,
  road_addr           text,
  building_summary    text,
  longitude           double precision,
  latitude            double precision,
  raw                 jsonb,
  fetched_at          timestamptz not null default now()
);

create index if not exists sale_results_sd_sgg_idx on sale_results(sd_code, sgg_code);
create index if not exists sale_results_usage_idx  on sale_results(usage_lcl_cd, usage_mcl_cd);
create index if not exists sale_results_date_idx   on sale_results(sale_date desc);
create index if not exists sale_results_court_idx  on sale_results(court_code);

-- RLS — anon 공개 read
alter table sale_results enable row level security;
do $$ begin
  drop policy if exists "public read" on sale_results;
  create policy "public read" on sale_results for select to anon, authenticated using (true);
end $$;

-- ============================================================================
-- 인근 낙찰 통계 view — (sd_code, sgg_code, usage_lcl_cd) 단위 집계
-- 매각된 건(sale_amount > 0)만 카운트해서 평균 낙찰가율 산출.
-- ============================================================================

create or replace view auction_stats_by_region as
select
  sd_code,
  sgg_code,
  usage_lcl_cd,
  count(*)                                              as total_count,
  count(*) filter (where sale_amount > 0)               as sold_count,
  count(*) filter (where sale_amount = 0 or sale_amount is null) as unsold_count,
  round(
    avg(case
      when sale_amount > 0 and appraisal_amount > 0
        then (sale_amount::numeric / appraisal_amount) * 100
    end), 1)                                            as avg_sale_rate_pct,
  round(avg(fail_count) filter (where sale_amount > 0), 1) as avg_fail_count_when_sold,
  round(avg(bidder_count) filter (where sale_amount > 0), 1) as avg_bidder_count,
  max(sale_date) filter (where sale_amount > 0)         as latest_sale_date,
  -- 90일 내 표본 수 (신선도 지표)
  count(*) filter (
    where sale_amount > 0
      and sale_date >= (current_date - interval '90 days')
  )                                                     as recent_sold_count
from sale_results
where sd_code is not null and sgg_code is not null
group by sd_code, sgg_code, usage_lcl_cd;

grant select on auction_stats_by_region to anon, authenticated;

create or replace view auction_stats_by_court as
select
  court_code,
  usage_lcl_cd,
  count(*)                                              as total_count,
  count(*) filter (where sale_amount > 0)               as sold_count,
  round(
    avg(case
      when sale_amount > 0 and appraisal_amount > 0
        then (sale_amount::numeric / appraisal_amount) * 100
    end), 1)                                            as avg_sale_rate_pct,
  round(avg(fail_count) filter (where sale_amount > 0), 1) as avg_fail_count_when_sold,
  max(sale_date) filter (where sale_amount > 0)         as latest_sale_date
from sale_results
group by court_code, usage_lcl_cd;

grant select on auction_stats_by_court to anon, authenticated;
