-- ============================================================================
-- 0017 — 주소 키워드 검색 trgm 인덱스 보강 (conv_addr, lot_addr)
-- 배경: 목록 키워드 검색은 road_addr/conv_addr/lot_addr 3컬럼에 ilike %kw% (OR).
--       0004에서 road_addr만 trgm 인덱스 → 나머지 2컬럼은 seq-scan.
--       BitmapOr가 3개 trgm 인덱스를 합치려면 세 컬럼 모두 인덱스 필요.
-- 부분 인덱스(deleted_at is null) — 쿼리가 항상 이 조건이라 인덱스 작게 유지.
--       (0004의 road_addr 인덱스는 전체라, 필요 시 나중에 부분으로 교체 가능.)
-- 적용(시놀로지): docker exec -i auction-db psql -U postgres -d postgres < 0017_*.sql
-- (인덱스는 PostgREST 스키마캐시와 무관 → NOTIFY 불필요.)
-- ============================================================================

create extension if not exists pg_trgm;

create index if not exists properties_conv_addr_trgm_idx
  on properties using gin (conv_addr gin_trgm_ops)
  where deleted_at is null;

create index if not exists properties_lot_addr_trgm_idx
  on properties using gin (lot_addr gin_trgm_ops)
  where deleted_at is null;
