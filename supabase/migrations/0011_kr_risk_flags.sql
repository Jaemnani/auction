-- ============================================================================
-- 0011 — 한국 매물 위험 플래그 (risk_flags)
-- 사용자가 "패스 키워드"를 선택해 제외 필터링하기 위한 사전 분석 컬럼.
-- backfill은 crawler/scripts/ingest.py backfill-risk-flags 명령으로 실행.
-- ============================================================================

alter table properties
  add column if not exists risk_flags text[] not null default '{}';

-- GIN 인덱스: risk_flags가 특정 키워드 포함하는지 검사 (cs / ov 연산자)
create index if not exists properties_risk_flags_gin
  on properties using gin (risk_flags);

comment on column properties.risk_flags is
'사전 분석된 위험 플래그 코드 목록. 매물 적재/상세 backfill 시 crawler가 자동 계산.
예: {share_sale, maeng_ji, yuchi}. 사용자 측에서 NOT overlap으로 제외 필터링.';
