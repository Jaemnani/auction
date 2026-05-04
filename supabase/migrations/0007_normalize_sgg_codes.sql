-- ============================================================================
-- 0007 — sgg 코드 정규화
-- 같은 (sd_code, name) 조합이 여러 code로 존재 (예: 강북구 305+300, 광진구 215+210).
-- canonical code를 MAX(code)로 선택 (행안부 표준이 일반적으로 큰 코드).
-- properties의 비표준 코드를 canonical로 갱신 후, regions_sgg에서 비표준 row 삭제.
-- ============================================================================

-- 1. canonical 매핑 테이블 (임시) — (sd_code, name) → MAX(code)
with canonical as (
  select sd_code, name, max(code) as canonical_code
  from regions_sgg
  group by sd_code, name
  having count(*) > 1
),
non_canon as (
  select s.sd_code, s.code as old_code, c.canonical_code
  from regions_sgg s
  join canonical c on c.sd_code = s.sd_code and c.name = s.name
  where s.code <> c.canonical_code
)
-- 2. properties.sgg_code 업데이트
update properties p
set sgg_code = nc.canonical_code
from non_canon nc
where p.sd_code = nc.sd_code and p.sgg_code = nc.old_code;

-- 3. sale_results도 같이
with canonical as (
  select sd_code, name, max(code) as canonical_code
  from regions_sgg
  group by sd_code, name
  having count(*) > 1
),
non_canon as (
  select s.sd_code, s.code as old_code, c.canonical_code
  from regions_sgg s
  join canonical c on c.sd_code = s.sd_code and c.name = s.name
  where s.code <> c.canonical_code
)
update sale_results sr
set sgg_code = nc.canonical_code
from non_canon nc
where sr.sd_code = nc.sd_code and sr.sgg_code = nc.old_code;

-- 4. 비표준 sgg row 삭제
with canonical as (
  select sd_code, name, max(code) as canonical_code
  from regions_sgg
  group by sd_code, name
  having count(*) > 1
)
delete from regions_sgg s
using canonical c
where s.sd_code = c.sd_code and s.name = c.name and s.code <> c.canonical_code;
