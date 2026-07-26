-- ============================================================================
-- 0018 — 낙찰 확정 + 1개월 유예 노출
--
-- 배경: close-aged 는 "검색에서 사라짐"만 알지 낙찰/취하를 구분 못 함.
--       sale_results(0005, PGJ158M02 매각결과)와 docid 로 조인하면 구분 가능:
--       sale_amount > 0 → 낙찰(sold), 0 → 유찰 후 종결 등(not_sold).
--       낙찰 매물은 삭제 즉시 숨기지 않고 30일간 웹에 계속 노출(낙찰가와 함께),
--       이후 기존처럼 RLS 로 숨김. 데이터는 계속 보존(soft delete 유지).
--
-- 흐름: run_daily.sh 8) sales-results 직후 finalize-sold 스텝이
--       finalize_sold_properties() 를 rpc 로 호출 — deleted && 미확정 행을
--       매일 재매칭 (sale_results 가 늦게 도착해도 다음 날 확정됨).
--
-- 적용(시놀로지): docker exec -i auction-db psql -U postgres -d postgres < 0018_*.sql
-- ============================================================================

-- 1) properties 낙찰 확정 컬럼
alter table properties add column if not exists final_result text
  check (final_result in ('sold', 'not_sold'));  -- null = 미확정(취하/기타 포함)
alter table properties add column if not exists sold_amount numeric(20,0);
alter table properties add column if not exists sold_date date;
alter table properties add column if not exists finalized_at timestamptz;

comment on column properties.final_result is
  '종결 확정 결과 — sold(낙찰)/not_sold(유찰 후 종결 등)/null(미확정). sale_results docid 매칭';
comment on column properties.sold_amount is 'sale_results.sale_amount(maeAmt) — 낙찰가. sold 일 때만';
comment on column properties.sold_date is 'sale_results.sale_date(maeGiil) — 낙찰된 매각기일';

-- 유예창 조회용 (deleted_at 최근 30일 & sold)
create index if not exists properties_sold_grace_idx
  on properties (deleted_at desc) where final_result = 'sold';
-- finalize 대상 스캔용 (deleted && 미확정)
create index if not exists properties_unfinalized_idx
  on properties (id) where deleted_at is not null and finalized_at is null;

-- 2) 확정 함수 — crawler 가 sb.rpc("finalize_sold_properties") 로 매일 호출.
--    PostgREST(supabase-py)는 집합 UPDATE 를 못 하므로 서버측 함수로.
--    security definer: anon RLS 무관하게 service 경로에서만 호출된다는 전제지만
--    낙찰 확정은 공개돼도 무해한 연산이라 EXECUTE 권한은 기본(공개)로 둠.
create or replace function finalize_sold_properties() returns integer
language sql security definer set search_path = public as $$
  with upd as (
    update properties p
    set final_result = case when sr.sale_amount > 0 then 'sold' else 'not_sold' end,
        sold_amount  = nullif(sr.sale_amount, 0),
        sold_date    = sr.sale_date,
        finalized_at = now()
    from sale_results sr
    where sr.docid = p.docid
      and p.docid is not null
      and p.deleted_at is not null
      and p.finalized_at is null
    returning 1
  ) select count(*)::int from upd;
$$;

-- dry-run 카운트용 (변경 없이 매칭 수만)
create or replace function count_finalizable_properties() returns integer
language sql stable security definer set search_path = public as $$
  select count(*)::int
  from properties p
  join sale_results sr on sr.docid = p.docid
  where p.deleted_at is not null and p.finalized_at is null;
$$;

-- 3) RLS — 유예창 확장 (0015 대체).
--    낙찰(sold) 매물은 deleted_at 후 30일간 anon 읽기 허용.
--    유예 기준을 sold_date 가 아닌 deleted_at 으로 한 이유: 매각기일(sold_date)은
--    매물이 아직 검색에 살아있을 때부터 존재 → 활성 매물인데 카운트다운이 도는 모순.
--    cases 는 crawler 가 soft-delete 하지 않으므로(properties 만) 0015 정책 유지.
drop policy if exists "public read" on properties;
create policy "public read" on properties
  for select to anon, authenticated
  using (
    deleted_at is null
    or (final_result = 'sold' and deleted_at > now() - interval '30 days')
  );

drop policy if exists "public read" on property_sale_dates;
create policy "public read" on property_sale_dates
  for select to anon, authenticated
  using (exists (
    select 1 from properties p
    where p.id = property_sale_dates.property_id
      and (p.deleted_at is null
           or (p.final_result = 'sold' and p.deleted_at > now() - interval '30 days'))
  ));

drop policy if exists "public read" on property_photos;
create policy "public read" on property_photos
  for select to anon, authenticated
  using (exists (
    select 1 from properties p
    where p.id = property_photos.property_id
      and (p.deleted_at is null
           or (p.final_result = 'sold' and p.deleted_at > now() - interval '30 days'))
  ));

-- 새 컬럼/함수 → PostgREST 스키마 캐시 갱신 필요
notify pgrst, 'reload schema';
