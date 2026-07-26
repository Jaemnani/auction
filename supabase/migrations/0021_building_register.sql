-- ============================================================================
-- 0021 — 건축물대장 표제부 캐시 (건물 연식 등)
--
-- 배경: 건축HUB(getBrTitleInfo)는 웹 프록시로 상세 페이지에서만 live 조회.
--       낙찰 예상가 모델(Phase D) 피처(건물 연식·연면적·구조)로 쓰려면 축적 필요.
--       활성 건물 매물당 1회 수집 (crawler/scripts/molit_ingest.py building-register).
--
-- 재수집 정책: fetch_status='ok'/'not_found' 는 재시도 안 함(대장은 거의 불변),
--       'error' 는 30일 후 재시도.
--
-- 적용(시놀로지): docker exec -i auction-db psql -U postgres -d postgres < 0021_*.sql
-- ============================================================================

create table if not exists property_building_register (
  property_id        uuid primary key references properties(id) on delete cascade,
  use_approval_day   date,          -- 사용승인일 (연식)
  structure          text,          -- 구조 (철근콘크리트 등)
  main_purpose       text,          -- 주용도
  total_area         numeric,       -- 연면적 ㎡
  arch_area          numeric,       -- 건축면적 ㎡
  plat_area          numeric,       -- 대지면적 ㎡
  ground_floors      smallint,
  underground_floors smallint,
  households         int,
  height             numeric,
  fetch_status       text not null default 'ok'
    check (fetch_status in ('ok', 'not_found', 'error')),
  raw                jsonb,         -- 표제부 첫 항목 원본
  fetched_at         timestamptz not null default now()
);

create index if not exists pbr_status_idx
  on property_building_register (fetch_status, fetched_at);

-- RLS — 공공정보 공개 read
alter table property_building_register enable row level security;
do $$ begin
  drop policy if exists "public read" on property_building_register;
  create policy "public read" on property_building_register
    for select to anon, authenticated using (true);
end $$;

notify pgrst, 'reload schema';
