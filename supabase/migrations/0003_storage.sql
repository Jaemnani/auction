-- ============================================================================
-- 0003 — Supabase Storage 버킷 (경매 매물 사진)
-- public 버킷 → 누구나 GET. 업로드/삭제는 service_role만.
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
