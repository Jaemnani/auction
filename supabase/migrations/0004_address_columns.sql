-- ============================================================================
-- 0004 — 주소 컬럼 추가
-- conv_addr는 사실 [집합건물 철근콘크리트구조 28.33㎡] 같은 건물 구조 텍스트.
-- 진짜 도로명 주소(예: '서울특별시 관악구 신림로31가길 5')는 search_row.bgPlaceRdAllAddr에 있음.
-- ============================================================================

create extension if not exists pg_trgm;

alter table properties
  add column if not exists road_addr text,
  add column if not exists lot_addr  text;

create index if not exists properties_road_addr_trgm_idx
  on properties using gin (road_addr gin_trgm_ops);
