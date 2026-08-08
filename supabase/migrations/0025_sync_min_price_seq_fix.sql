-- 0025: sync_min_sale_price_from_schedule() 회차 선택 버그 수정.
--
-- 0024 는 같은 sale_date 에 여러 회차 행이 있을 때 `order by seq desc` 로
-- "최신 seq" 를 골랐는데, 이는 현재 회차가 아니라 **다음 회차(더 낮은 가격)** 다.
-- 실측 B0002802025013050397211 (유찰 2회):
--     seq1 2026-07-06 11,500,000 (유찰)
--     seq2 2026-07-06  8,050,000 (유찰)
--     seq3 2026-08-10  5,635,000 ← 현재 회차 (미개최)
--     seq4 2026-08-10  3,945,000 ← 다음 회차 선반영
-- 0024 는 seq4(3,945,000)를 골라 properties.min_sale_price 를 실제보다 낮게 썼다.
-- 최저가를 실제보다 낮게 표시하면 "그 가격에 입찰 가능"으로 오해할 수 있어 방향이
-- 나쁜 오류다(예상가 하한도 함께 낮아짐).
--
-- 수정: 아직 개최되지 않은 행(result_cd is null) 중 **가장 이른 seq** 가 현재 회차.
-- (개최 완료 행은 result_cd 가 채워지므로 자연 제외된다.)

create or replace function sync_min_sale_price_from_schedule() returns integer
language sql security definer set search_path = public as $$
  with sched as (
    -- 매물별 "현재 예정 회차"(properties.sale_date 와 같은 날짜, 미개최)의 최저가.
    -- 같은 날짜에 여러 회차가 실려도 가장 이른 seq = 현재 회차.
    select distinct on (s.property_id) s.property_id, s.min_price
    from property_sale_dates s
    join properties p on p.id = s.property_id and p.sale_date = s.sale_date
    where s.min_price is not null and s.min_price > 0
      and s.result_cd is null                                  -- 미개최 회차만
      and coalesce(s.raw->>'auctnDxdyKndCd', '01') = '01'       -- 매각기일(01)만
      and p.deleted_at is null
    order by s.property_id, s.seq                              -- 가장 이른 회차
  ), upd as (
    update properties p set min_sale_price = sched.min_price
    from sched
    where p.id = sched.property_id
      and p.min_sale_price is distinct from sched.min_price
    returning 1
  ) select count(*)::int from upd;
$$;

comment on function sync_min_sale_price_from_schedule() is
  '검색 API stale 최저가 보정 — 현재 예정 회차(미개최·최소 seq)의 min_price 를 properties.min_sale_price 로 동기화. run_daily 가 검색 수집 후 매일 호출';

notify pgrst, 'reload schema';
