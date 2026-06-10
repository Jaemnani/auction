-- ============================================================================
-- bootstrap/00_roles.sql
-- Supabase 클라우드가 기본 제공하던 역할을 self-host 에서 직접 생성.
-- docker-entrypoint-initdb.d 로 **DB 최초 1회 자동 실행** (데이터 디렉토리가 빈 경우만).
-- 마이그레이션(0001~) 이 'to anon, authenticated' role 을 참조하므로 반드시 선행.
--
-- 주의: 'CHANGE_ME_SAME_AS_ENV' 를 .env 의 AUTHENTICATOR_PASSWORD 와 동일하게.
--       (docker compose 가 initdb 시 이 파일을 그대로 실행 — 변수 치환 안 됨.
--        README 4장에서 sed 로 치환하는 단계 제공.)
-- ============================================================================

-- PostgREST 가 익명 요청을 매핑할 역할
create role anon nologin noinherit;
create role authenticated nologin noinherit;
-- service_role: RLS 우회 (크롤러 적재용 — 단, 우리는 PGRST 로는 anon 만 씀.
-- 크롤러는 postgres superuser 또는 service_role 로 직접 접속)
create role service_role nologin noinherit bypassrls;

-- PostgREST 가 로그인하는 역할 — 위 3개로 SET ROLE 전환
create role authenticator noinherit login password 'CHANGE_ME_SAME_AS_ENV';
grant anon, authenticated, service_role to authenticator;

-- public 스키마 사용권
grant usage on schema public to anon, authenticated, service_role;

-- 이후 생성될 테이블 기본 권한
--  anon: 공개 read (마이그레이션 0002 의 RLS 정책과 함께 동작)
--  service_role: 전체 (적재)
alter default privileges in schema public grant select on tables to anon, authenticated;
alter default privileges in schema public grant all on tables to service_role;
alter default privileges in schema public grant all on sequences to service_role;
