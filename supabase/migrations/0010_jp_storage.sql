-- ============================================================================
-- 0010 — Supabase Storage 버킷 (일본 경매 매물 사진)
-- 한국 auction-photos와 분리: 한·일 사진 데이터 격리
-- public 버킷 → 누구나 GET. 업로드/삭제는 service_role만.
--
-- ⚠️ self-host 에선 적용 안 함 (0003 와 동일 — apply-migrations.sh 자동 SKIP).
--    jp-auction-photos 버킷은 deploy/synology/README.md 6장에서 MinIO 로 생성.
-- ============================================================================

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'jp-auction-photos',
  'jp-auction-photos',
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
  drop policy if exists "jp-auction-photos public read" on storage.objects;
exception when undefined_object then null;
end $$;

create policy "jp-auction-photos public read" on storage.objects
  for select to anon, authenticated
  using (bucket_id = 'jp-auction-photos');
