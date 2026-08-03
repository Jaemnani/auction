-- 0024: properties.min_sale_price 를 상세 기일 일정 기준으로 보정하는 RPC.
--
-- 배경: 법원 검색 API 의 minmaePrice 는 유찰 후에도 이전 회차 값이 남는(갱신 지연)
-- 소스 특성이 있음. 실측: 2026타경30547 — 7/22 재스캔에서 fail_count 0→1,
-- sale_date 7/7→8/6 으로 바뀌었는데 minmaePrice 는 634,000,000 그대로
-- (실제 8/6 회차 최저가는 property_sale_dates 에 443,800,000 으로 정확).
-- 이 stale 값이 웹 목록/상세/지도 최저가 표시와 낙찰 예상가 모델의
-- min_rate 피처를 오염시킴 (감정가 6.34억 유찰 매물에 6.49억 예측 사고).
--
-- 해법: 상세 API 가 채우는 property_sale_dates(기일 일정)의 "현재 예정 회차"
-- 최저가를 properties.min_sale_price 로 동기화. 검색 재스캔이 매일 stale 값을
-- 다시 쓸 수 있으므로 run_daily 에서 검색 수집 이후 단계로 매일 호출한다.
-- (sync_safety_scores 0023 / finalize_sold_properties 0018 과 동일 RPC 패턴)

create or replace function sync_min_sale_price_from_schedule() returns integer
language sql security definer set search_path = public as $$
  with sched as (
    -- 매물별 "현재 예정 회차"(properties.sale_date 와 같은 날짜)의 최저가.
    -- kind 02(매각결정기일)는 min_price 가 0/NULL 이라 gt 필터로 자연 배제되지만
    -- 명시적으로 매각기일(01)만 취한다. 같은 날짜 중복 시 최신 seq.
    select distinct on (s.property_id) s.property_id, s.min_price
    from property_sale_dates s
    join properties p on p.id = s.property_id and p.sale_date = s.sale_date
    where s.min_price is not null and s.min_price > 0
      and coalesce(s.raw->>'auctnDxdyKndCd', '01') = '01'
      and p.deleted_at is null
    order by s.property_id, s.seq desc
  ), upd as (
    update properties p set min_sale_price = sched.min_price
    from sched
    where p.id = sched.property_id
      and p.min_sale_price is distinct from sched.min_price
    returning 1
  ) select count(*)::int from upd;
$$;

comment on function sync_min_sale_price_from_schedule() is
  '검색 API stale 최저가 보정 — 현재 예정 회차(property_sale_dates)의 min_price 를 properties.min_sale_price 로 동기화. run_daily 가 검색 수집 후 매일 호출';

notify pgrst, 'reload schema';
