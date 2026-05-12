-- ============================================================================
-- 0012 — 강원도 시·군·구 누락 시드 (행안부 표준 코드)
--
-- 증상: 강원도 필터에서 시·군·구 dropdown이 강릉시만 노출. 동해시/양양군 등
--       나머지 17개 시·군·구가 선택 불가.
--
-- 원인: crawler/src/courtauction/client.py::list_sigungu가 courtauction.go.kr의
--       /pgj/pgj002/selectAdongSggLst.on을 pbancMidYn="Y"로 호출 → 공고중 매물
--       있는 sgg만 반환. 강원도 활성 매물이 강릉시에만 있던 시점에 masters
--       ingest가 돌면서 다른 17개 시·군·구는 regions_sgg에 들어가지 못함.
--
-- 해결: 행정안전부 표준 시·군·구 코드를 직접 시드. 매물이 있을 때마다 join
--       대상이 안정적으로 존재하게 보장.
--
-- 안전: 이미 같은 (sd_code, code) 또는 같은 name으로 row가 있으면 skip
--       (중복 행 생성 방지 — 0007의 MAX(code) canonical 로직과 충돌 회피).
-- ============================================================================

with seed (code, name) as (
  values
    ('110', '춘천시'), ('130', '원주시'), ('150', '강릉시'),
    ('170', '동해시'), ('190', '태백시'), ('210', '속초시'),
    ('230', '삼척시'), ('720', '홍천군'), ('730', '횡성군'),
    ('750', '영월군'), ('760', '평창군'), ('770', '정선군'),
    ('780', '철원군'), ('790', '화천군'), ('800', '양구군'),
    ('810', '인제군'), ('820', '고성군'), ('830', '양양군')
)
insert into regions_sgg (sd_code, code, name)
select '42', s.code, s.name
from seed s
where not exists (
  select 1 from regions_sgg r
  where r.sd_code = '42' and (r.code = s.code or r.name = s.name)
);
