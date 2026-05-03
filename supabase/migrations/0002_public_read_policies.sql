-- ============================================================================
-- 0002 — anon (공개) 읽기 정책
-- service_role은 RLS 우회 → 적재(ingest)는 그대로 동작
-- anon은 read-only로 전체 노출 (이 데이터셋은 본래 공공정보)
-- ============================================================================

alter table courts                enable row level security;
alter table regions_sd            enable row level security;
alter table regions_sgg           enable row level security;
alter table regions_emd           enable row level security;
alter table usage_codes           enable row level security;
alter table cases                 enable row level security;
alter table properties            enable row level security;
alter table property_sale_dates   enable row level security;
alter table property_photos       enable row level security;

-- 공개 read 정책 — anon + authenticated 둘 다 SELECT 허용
do $$
declare t text;
begin
  for t in select unnest(array[
    'courts','regions_sd','regions_sgg','regions_emd','usage_codes',
    'cases','properties','property_sale_dates','property_photos'
  ])
  loop
    execute format($f$
      drop policy if exists "public read" on %I;
      create policy "public read" on %I
        for select to anon, authenticated
        using (true);
    $f$, t, t);
  end loop;
end $$;

-- 운영 테이블은 anon에 노출하지 않음 (RLS는 켜되 정책 미생성 → anon 차단)
alter table raw_responses enable row level security;
alter table crawl_runs    enable row level security;
alter table dead_letters  enable row level security;
