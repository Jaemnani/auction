#!/usr/bin/env bash
# courtauction → Supabase 일일 갱신.
# cron 등록은 ./install_cron.sh로.
#
# 환경변수로 동작 조정:
#   COURT=B000210     특정 법원만 (기본: 전국)
#   PAGE_SIZE=50      검색 페이지 크기 (서버 상한)
#   MAX_PAGES=10      검색 페이지 상한 (기본: 무제한)
#   DETAIL_LIMIT=200  detail 백필 1회 처리량
#   PHOTO_LIMIT=500   사진 적재 1회 처리량
#   THUMB_LIMIT=500   썸네일 생성 1회 처리량
#   PYTHON=/path/to/python  (기본: 공용 venv)
#
# 모든 stdout/stderr는 crawler/data/logs/daily_<timestamp>.log 에 함께 저장.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# --- 경로 / 로그 ---
PYTHON="${PYTHON:-/Users/ohyeahdani_m1/workspace/venv_common/bin/python}"
LOG_DIR="$PROJECT_ROOT/crawler/data/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/daily_$(date +%Y%m%d_%H%M%S).log"

# stdout/stderr 모두 로그 파일에 미러
exec > >(tee -a "$LOG") 2>&1

# --- 동시 실행 방지 (mkdir 기반 락 — macOS flock 없음) ---
LOCK_DIR="$PROJECT_ROOT/crawler/data/.daily.lock.d"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[skip] another run in progress (lock=$LOCK_DIR)"
  echo "       stale이면 'rmdir $LOCK_DIR' 후 재시도"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

# --- python 점검 ---
if [ ! -x "$PYTHON" ]; then
  echo "[fatal] python not found: $PYTHON"
  exit 1
fi
if [ ! -f "$PROJECT_ROOT/.env" ]; then
  echo "[fatal] .env not found at $PROJECT_ROOT/.env"
  exit 1
fi

# --- 설정 (env override 가능) ---
COURT="${COURT:-}"
PAGE_SIZE="${PAGE_SIZE:-50}"
MAX_PAGES="${MAX_PAGES:-}"
DETAIL_LIMIT="${DETAIL_LIMIT:-200}"
PHOTO_LIMIT="${PHOTO_LIMIT:-500}"
THUMB_LIMIT="${THUMB_LIMIT:-500}"

step() {
  local label="$1"; shift
  local rc=0
  echo ""
  echo "==== $(date -Iseconds) [$label] ===="
  "$PYTHON" "$@" || rc=$?
  if [ $rc -ne 0 ]; then
    echo "[warn] step '$label' exited $rc — 다음 step 계속"
  fi
}

echo "===== courtauction daily run start: $(date -Iseconds) ====="
echo "log:    $LOG"
echo "python: $PYTHON"
echo "court:  ${COURT:-<all>}"

step "masters" crawler/scripts/ingest.py masters

# 검색 적재 — COURT가 있으면 그 법원만
if [ -n "$COURT" ]; then
  step "search ($COURT)" crawler/scripts/ingest.py search \
    --court "$COURT" --page-size "$PAGE_SIZE" \
    ${MAX_PAGES:+--max-pages "$MAX_PAGES"}
else
  step "search (all)" crawler/scripts/ingest.py search \
    --page-size "$PAGE_SIZE" \
    ${MAX_PAGES:+--max-pages "$MAX_PAGES"}
fi

step "backfill-details" crawler/scripts/ingest.py backfill-details \
  --limit "$DETAIL_LIMIT" ${COURT:+--court "$COURT"}

step "backfill-photos" crawler/scripts/ingest.py backfill-photos --limit "$PHOTO_LIMIT"
step "backfill-thumbs" crawler/scripts/ingest.py backfill-thumbs --limit "$THUMB_LIMIT"
step "backfill-coords" crawler/scripts/ingest.py backfill-coords
step "backfill-addrs"  crawler/scripts/ingest.py backfill-addrs

# 오래된 로그 정리 (30일 이상)
find "$LOG_DIR" -name "daily_*.log" -mtime +30 -delete 2>/dev/null || true

echo ""
echo "===== courtauction daily run done: $(date -Iseconds) ====="
