-- ============================================================================
-- 0003 — Supabase Storage 버킷 (경매 매물 사진)
-- public 버킷 → 누구나 GET. 업로드/삭제는 service_role만.
--
-- ⚠️ self-host (Synology Postgres+PostgREST+MinIO) 에선 이 파일을 적용하지 않는다.
--    storage.buckets / storage.objects 는 Supabase 전용 스키마라 존재하지 않음.
--    MinIO 가 대체 — deploy/synology/apply-migrations.sh 가 자동 SKIP, 버킷·public 은
--    deploy/synology/README.md 6장 (mc 명령) 으로 생성.
-- ============================================================================

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'auction-photos',
  'auction-photos',
  true,
  10485760, -- 10MB
  array['image/jpeg','image/jpg','image/png','image/webp']
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

-- 공개 read (anon + authenticated). insert/update/delete 정책은 만들지 않음 → service_role만 가능.
do $$
begin
  drop policy if exists "auction-photos public read" on storage.objects;
exception when undefined_object then null;
end $$;

create policy "auction-photos public read" on storage.objects
  for select to anon, authenticated
  using (bucket_id = 'auction-photos');
