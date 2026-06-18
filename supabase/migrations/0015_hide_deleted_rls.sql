-- ============================================================================
-- 0015 — soft-deleted 행을 anon 읽기에서 차단 (RLS)
-- 문제: 0002 의 "public read" 정책이 using(true) 라 deleted_at IS NOT NULL 행
--       (낙찰/취하로 운영자가 내린 매물)도 anon 이 REST 로 직접 조회 가능.
--       UI(목록/지도)는 deleted_at IS NULL 로 거르지만 DB 레벨 미강제 → 누락 차단.
-- 범위: deleted_at 보유 테이블(properties, cases) + 그 자식(photos, sale_dates).
--       courts/regions/usage_codes 는 마스터라 그대로(공개 유지).
--
-- 참고: 컬럼 단위 노출(detail_result 등)은 0002 주석대로 "본래 공공정보" 설계 의도라
--       유지. 웹은 anon 키로 detail_result 를 읽으므로 컬럼 revoke 시 상세페이지 깨짐.
--
-- 적용(시놀로지): docker exec -i auction-db psql -U postgres -d postgres < 0015_*.sql
-- (RLS 정책은 PostgREST 캐시와 무관 — 즉시 적용. NOTIFY 불필요.)
-- ============================================================================

-- properties / cases — 자신의 deleted_at 기준
drop policy if exists "public read" on properties;
create policy "public read" on properties
  for select to anon, authenticated
  using (deleted_at is null);

drop policy if exists "public read" on cases;
create policy "public read" on cases
  for select to anon, authenticated
  using (deleted_at is null);

-- 자식 테이블 — 부모(properties)가 살아있을 때만 (property_id 인덱스 존재)
drop policy if exists "public read" on property_sale_dates;
create policy "public read" on property_sale_dates
  for select to anon, authenticated
  using (exists (
    select 1 from properties p
    where p.id = property_sale_dates.property_id and p.deleted_at is null
  ));

drop policy if exists "public read" on property_photos;
create policy "public read" on property_photos
  for select to anon, authenticated
  using (exists (
    select 1 from properties p
    where p.id = property_photos.property_id and p.deleted_at is null
  ));
