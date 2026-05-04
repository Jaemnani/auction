-- ============================================================================
-- 0008 — property_sale_dates 컬럼 백필 (raw에서 추출)
-- 이전 store.py가 잘못된 필드명(dspslPlc / lwsDspslPrc / dspslRsltCd)을 매핑해
-- place / min_price / result_cd 컬럼이 모두 NULL이었음. raw jsonb에 데이터는 있음.
-- 실제 응답 키: dxdyPlcNm / tsLwsDspslPrc / auctnDxdyRsltCd / dspslAmt
-- ============================================================================

-- sale_amount 컬럼 추가 (실제 낙찰가 — 유찰이면 NULL/0)
alter table property_sale_dates
  add column if not exists sale_amount numeric(20,0),
  add column if not exists kind_cd     text;

-- raw에서 추출해 컬럼 채우기
update property_sale_dates
set
  place      = nullif(raw->>'dxdyPlcNm', ''),
  min_price  = (nullif(raw->>'tsLwsDspslPrc', ''))::numeric,
  result_cd  = nullif(raw->>'auctnDxdyRsltCd', ''),
  sale_amount = (nullif(raw->>'dspslAmt', ''))::numeric,
  kind_cd    = nullif(raw->>'auctnDxdyKndCd', '')
where raw is not null;

-- 인덱스
create index if not exists property_sale_dates_result_cd_idx on property_sale_dates(result_cd);
