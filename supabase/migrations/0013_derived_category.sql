-- ============================================================================
-- 0013 — Phase 4: 한국 한글 용도명 + 한·일 파생 카테고리
-- ============================================================================
-- 사이트(courtauction)의 search 응답에 이미 한글 용도명 (dspslUsgNm) 20종이
-- 들어 있음 — 마스터(usage_codes lcl/mcl/scl) 보강 없이 이 값을 정규 컬럼화.
--
-- 추가로 사용자 정의 파생 카테고리(전원주택/도심단독/농가/별장 등)는 룰 엔진이
-- text[]로 채움. risk_flags 와 같은 패턴 (GIN 인덱스).
--
-- 적용: Supabase Dashboard SQL Editor 에 통째로 붙여 Run.
-- ============================================================================

-- ----- 한국 -----

-- (1) 한국 사이트의 한글 용도명 — search_row.dspslUsgNm 직접 매핑.
--     예: '아파트', '다세대', '연립주택,다세대,빌라', '오피스텔', '단독주택',
--          '단독주택다가구', '근린시설', '상가', '상가,오피스텔,근린시설',
--          '대지', '전답', '임야', '자동차', '중기', '기타' 등 20종.
alter table properties add column if not exists usage_nm text;
create index if not exists properties_usage_nm_idx
  on properties (usage_nm) where deleted_at is null;

-- (2) 한국 파생 카테고리 — 룰 엔진이 채움 (전원주택, 도심단독, 농가, 별장 ...).
--     risk_flags 와 같은 text[] + GIN 인덱스 패턴.
alter table properties add column if not exists derived_category text[] not null default '{}';
create index if not exists properties_derived_category_gin
  on properties using gin (derived_category)
  where deleted_at is null;
comment on column properties.derived_category is
  '룰 엔진 derived. 코드: country_house/townhouse/farm_house/vacation_home/... (확장 가능)';

-- ----- 일본 -----

-- 일본은 jp_properties.sale_cls / sale_cls_label 에 이미 표준 분류
-- (1=土地 / 2=戸建て / 3=マンション / 4=その他) 가 있음. 추가 컬럼 X.
-- derived_category 만 신설 (別荘, 駐車場 등 룰 추후).
alter table jp_properties add column if not exists derived_category text[] not null default '{}';
create index if not exists jp_properties_derived_category_gin
  on jp_properties using gin (derived_category);
