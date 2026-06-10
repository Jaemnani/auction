#!/usr/bin/env bash
# 마이그레이션 적용 — auction-db 컨테이너에 0001~0013 SQL 실행.
# 0003_storage / 0010_jp_storage 는 Supabase storage.buckets 전용이라 SKIP (MinIO 가 대체).
#
# 시놀로지에서:
#   cd /volume1/docker/auction
#   sudo bash apply-migrations.sh
#
# repo 의 supabase/migrations/ 를 이 디렉토리 옆에 복사해두거나,
# MIGRATIONS_DIR 환경변수로 경로 지정.

set -euo pipefail

CONTAINER="${CONTAINER:-auction-db}"
DB_USER="${DB_USER:-postgres}"
DB_NAME="${DB_NAME:-postgres}"
# 기본: 이 스크립트 기준 ../../supabase/migrations (repo 통째로 올린 경우)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-$SCRIPT_DIR/../../supabase/migrations}"

SKIP_FILES="0003_storage 0010_jp_storage"   # Supabase storage 전용 — MinIO 가 대체

echo "== auction migrations =="
echo "container:  $CONTAINER"
echo "migrations: $MIGRATIONS_DIR"

if ! sudo docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
  echo "[fatal] container '$CONTAINER' not running. 'docker-compose up -d' 먼저."
  exit 1
fi

run_sql() {
  sudo docker exec -i "$CONTAINER" psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" "$@"
}

# 0) 확장 (postgis 이미지에 postgis 포함. pg_trgm 은 명시 생성)
echo ""
echo "-- extensions --"
run_sql -c "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";"
run_sql -c "CREATE EXTENSION IF NOT EXISTS postgis;"
run_sql -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

# 1) 마이그레이션 순차 적용
echo ""
echo "-- migrations --"
for f in "$MIGRATIONS_DIR"/0*.sql; do
  base="$(basename "$f" .sql)"
  skip=false
  for s in $SKIP_FILES; do
    [ "$base" = "$s" ] && skip=true
  done
  if $skip; then
    echo "  SKIP  $base  (Supabase storage 전용 — MinIO 대체)"
    continue
  fi
  echo "  apply $base"
  run_sql < "$f"
done

# 2) PostgREST 스키마 캐시 갱신 (NOTIFY)
run_sql -c "NOTIFY pgrst, 'reload schema';" || true

echo ""
echo "== done =="
echo "검증:  sudo docker exec -i $CONTAINER psql -U $DB_USER -d $DB_NAME -c '\\dt'"
