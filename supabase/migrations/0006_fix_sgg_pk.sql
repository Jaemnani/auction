-- ============================================================================
-- 0006 — regions_sgg PK 변경: code → (sd_code, code) 복합키
-- 문제: sgg 3자리 코드는 시·도 내에서만 unique이라, code가 PK면 sd가 다른 같은
--       code (예: 680)가 last-wins로 묻혀 178개 중 89개만 적재됨.
-- ============================================================================

-- regions_emd가 regions_sgg(code)에 FK 있어 먼저 제거 (emd 미적재라 안전)
alter table regions_emd drop constraint if exists regions_emd_sgg_code_fkey;

alter table regions_sgg drop constraint if exists regions_sgg_pkey;
alter table regions_sgg add primary key (sd_code, code);

-- regions_emd FK는 단일 sgg_code만 가지므로 다시 못 걸음 — composite 참조 컬럼 추가 필요
-- emd는 추후 적재 시 regions_emd 스키마도 함께 수정 예정 (지금은 unused).
