-- ============================================================================
-- 0020 — 국토부(MOLIT) 실거래가 수집 테이블
--
-- 배경: 실거래가는 지금까지 웹 프록시(api/molit-deals)로 상세 페이지에서
--       live 조회만 했음(DB 미저장). 낙찰 예상가 모델(Phase D)의 피처
--       (지역 ㎡당 시세)로 쓰려면 축적이 필요 → 크롤러가 월 단위로 수집.
--
-- 키 설계: MOLIT 응답 row 에는 자연키가 없음(같은 단지·같은 날 동일 조건 복수
--       거래 가능) → 행 단위 upsert 불가. 수집 단위 (deal_type, lawd_cd,
--       deal_ymd) 통째 delete+insert 교체가 단순·안전. 수집 상태는
--       molit_fetch_log 로 관리 (증분/백필 스케줄 판단).
--
-- 수집기: crawler/scripts/molit_ingest.py deals (run_daily.sh 8.6 스텝)
--
-- 적용(시놀로지): docker exec -i auction-db psql -U postgres -d postgres < 0020_*.sql
-- ============================================================================

create table if not exists molit_deals (
  id            bigint generated always as identity primary key,
  deal_type     text not null,     -- apt/rh/sh/offi/land/nrg/indu (웹 route.ts 키와 동일)
  lawd_cd       text not null,     -- 5자리 법정동 시군구 (sd_code+sgg_code)
  deal_ymd      text not null,     -- YYYYMM (수집 단위)
  name          text,              -- 단지/건물명 (aptNm/offiNm/mhouseNm/houseType/buildingType)
  umd_nm        text,              -- 법정동명
  jibun         text,
  area_m2       numeric,           -- 전용/대지/연면적 — 유형별 폴백 (normalizeDeal 규칙)
  floor         smallint,
  built_year    smallint,          -- buildYear (준공년도)
  amount_manwon numeric(12,0),     -- 거래금액 (만원)
  deal_date     date,              -- dealYear/Month/Day 조합
  raw           jsonb,             -- 원본 (필드 추가 대비)
  fetched_at    timestamptz not null default now()
);

create index if not exists molit_deals_key_idx
  on molit_deals (deal_type, lawd_cd, deal_ymd);
create index if not exists molit_deals_lawd_date_idx
  on molit_deals (lawd_cd, deal_date desc);

-- 수집 상태 — (조합)별 마지막 수집 시각/건수. 증분(당월+전월 7일 경과 재수집)과
-- 과거 24개월 백필 drain 의 진행 상황 판단에 사용.
create table if not exists molit_fetch_log (
  deal_type  text not null,
  lawd_cd    text not null,
  deal_ymd   text not null,
  row_count  int,
  fetched_at timestamptz not null default now(),
  primary key (deal_type, lawd_cd, deal_ymd)
);

-- RLS — 공공정보라 공개 read (0002/0005 설계 의도와 동일)
alter table molit_deals enable row level security;
alter table molit_fetch_log enable row level security;
do $$ begin
  drop policy if exists "public read" on molit_deals;
  create policy "public read" on molit_deals
    for select to anon, authenticated using (true);
  drop policy if exists "public read" on molit_fetch_log;
  create policy "public read" on molit_fetch_log
    for select to anon, authenticated using (true);
end $$;

notify pgrst, 'reload schema';
