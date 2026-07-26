-- ============================================================================
-- 0019 — 낙찰 아카이브 view (지역 과거 낙찰 사례)
--
-- 별도 아카이브 테이블은 불필요 — sale_results(0005)가 낙찰 시점 스냅샷
-- (감정가·최저가·낙찰가·유찰·응찰자·주소·좌표·용도)을 자체 보유하고 영구 축적됨.
-- 이 view 는 낙찰 건(sale_amount > 0)만 골라 properties 를 docid 로 enrich
-- (면적/지번주소). view 는 owner 권한으로 실행되므로 30일 유예(0018)가 지난
-- properties 행도 여기 경유로는 읽힘 = "과거 사례" 영구 노출.
-- (0002/0005 주석의 "본래 공공정보" 설계 의도와 일치 — 무거운/원본 컬럼 미포함)
--
-- 웹: 상세 페이지 "인근 낙찰 통계" 카드가 emd(+용도) 우선 → sgg 폴백으로
--     최근 사례 리스트를 이 view 에서 조회.
--
-- 적용(시놀로지): docker exec -i auction-db psql -U postgres -d postgres < 0019_*.sql
-- ============================================================================

-- [핫픽스] sale_results.usage_nm — store.upsert_sale_results 가 이 컬럼을 쓰는데
-- 0005 에 없어서 PGRST204 로 sales-results 적재가 매일 통째로 실패해 왔음
-- (crawl_runs 실측: rows=50 fetch, upserted=0, status=failed → 테이블 0건).
-- 컬럼 추가로 적재 재개. 기존 실패분은 sales-results --bid-from 백필로 소급.
alter table sale_results add column if not exists usage_nm text;

create or replace view sale_archive as
select
  sr.docid,
  sr.court_code,
  sr.case_no,
  sr.maemul_ser,
  sr.appraisal_amount,
  sr.min_sale_price,
  sr.sale_amount,
  sr.fail_count,
  sr.bidder_count,
  sr.sale_date,
  round(sr.sale_amount::numeric / nullif(sr.appraisal_amount, 0) * 100, 1) as sale_rate_pct,
  sr.usage_lcl_cd,
  sr.usage_mcl_cd,
  sr.sd_code,
  sr.sgg_code,
  sr.emd_code,
  sr.conv_addr,
  sr.road_addr,
  sr.building_summary,
  coalesce(sr.usage_nm, p.usage_nm) as usage_nm,
  p.area_summary,
  p.lot_addr
from sale_results sr
left join properties p on p.docid = sr.docid
where sr.sale_amount > 0;

grant select on sale_archive to anon, authenticated;

-- 지역 사례 조회 인덱스 (sgg + 용도 + 최신순)
create index if not exists sale_results_region_date_idx
  on sale_results (sgg_code, usage_lcl_cd, sale_date desc)
  where sale_amount > 0;
create index if not exists sale_results_emd_date_idx
  on sale_results (emd_code, sale_date desc)
  where sale_amount > 0;

-- 새 view → PostgREST 스키마 캐시 갱신
notify pgrst, 'reload schema';
