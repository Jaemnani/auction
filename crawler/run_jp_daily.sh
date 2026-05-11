#!/usr/bin/env bash
# BIT(bit.courts.go.jp) → Supabase 일일 갱신.
# cron 등록은 ./install_jp_cron.sh로.
#
# 흐름:
#   각 도도부현 search → 좌표·사진 미수집 매물 backfill-details + photos
#
# 환경변수:
#   PREFECTURES="13,27,..."  적재 대상 (기본: 47도도부현 전체)
#   PAGE_SIZE=30             검색 페이지 크기 (BIT 상한)
#   MAX_PAGES=12             도도부현당 페이지 상한 (기본 12)
#   DETAIL_LIMIT=200         backfill-details 1회 처리량
#   PHOTO_LIMIT=200          photos 1회 처리량
#   MAX_DRAIN_ITERS=15       drain 루프 최대 반복
#   TIME_BUDGET=7200         전체 예산 (초). 초과 시 남은 step 건너뜀
#   PYTHON=/path/...         (기본: 공용 venv)
#
# 모든 stdout/stderr → crawler/data/logs/jp_daily_<timestamp>.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON="${PYTHON:-/Users/ohyeahdani_m1/workspace/venv_common/bin/python}"
LOG_DIR="$PROJECT_ROOT/crawler/data/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/jp_daily_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

# --- 동시 실행 방지 ---
LOCK_DIR="$PROJECT_ROOT/crawler/data/.jp_daily.lock.d"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[skip] another jp daily run in progress (lock=$LOCK_DIR)"
  echo "       stale이면 'rmdir $LOCK_DIR' 후 재시도"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

# --- 사전 점검 ---
[ -x "$PYTHON" ] || { echo "[fatal] python not found: $PYTHON"; exit 1; }
[ -f "$PROJECT_ROOT/.env" ] || { echo "[fatal] .env missing"; exit 1; }

# .env 자동 로드
set -a
# shellcheck disable=SC1091
. "$PROJECT_ROOT/.env"
set +a

# --- 설정 ---
DEFAULT_PREFS="91,92,93,94,02,03,04,05,06,07,08,09,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47"
PREFECTURES="${PREFECTURES:-$DEFAULT_PREFS}"
PAGE_SIZE="${PAGE_SIZE:-30}"
MAX_PAGES="${MAX_PAGES:-12}"
DETAIL_LIMIT="${DETAIL_LIMIT:-200}"
PHOTO_LIMIT="${PHOTO_LIMIT:-200}"
MAX_DRAIN_ITERS="${MAX_DRAIN_ITERS:-15}"
TIME_BUDGET="${TIME_BUDGET:-7200}"

START_TS=$(date +%s)
budget_left() { echo $((TIME_BUDGET - ($(date +%s) - START_TS))); }

step() {
  local label="$1"; shift
  if [ "$(budget_left)" -le 0 ]; then
    echo "[skip] '$label' — TIME_BUDGET 소진"
    return
  fi
  local rc=0
  echo ""
  echo "==== $(date -Iseconds) [$label] (budget $(budget_left)s left) ===="
  "$PYTHON" "$@" || rc=$?
  [ $rc -ne 0 ] && echo "[warn] step '$label' exited $rc — 다음 step 계속"
}

drain() {
  local label="$1"; shift
  for i in $(seq 1 "$MAX_DRAIN_ITERS"); do
    if [ "$(budget_left)" -le 0 ]; then
      echo "[skip] '$label' iter=$i — TIME_BUDGET 소진"
      return
    fi
    echo ""
    echo "==== $(date -Iseconds) [$label iter=$i] (budget $(budget_left)s left) ===="
    local out
    out=$("$PYTHON" "$@" 2>&1) || true
    echo "$out"
    # 종결 조건: "no jp_properties" / "DONE: 0" / "0 ok"
    if echo "$out" | grep -qE "no jp_properties|DONE: 0 |0 ok"; then
      echo "[drain] $label — 처리할 row 없음, 종료"
      return
    fi
  done
  echo "[drain] $label — MAX_DRAIN_ITERS($MAX_DRAIN_ITERS) 도달, 다음 step으로"
}

echo "===== jp_daily run start: $(date -Iseconds) ====="
echo "log:         $LOG"
echo "python:      $PYTHON"
echo "prefectures: $PREFECTURES"
echo "budget:      ${TIME_BUDGET}s ($((TIME_BUDGET / 60))분)"

# run 시작 timestamp — 종결 매물(BIT 검색에서 사라진 매물) 자동 close용 기준
RUN_SINCE_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "since:       $RUN_SINCE_ISO (이 시각 이전 fetched_at 매물은 close-aged 대상)"

# 1) 전국 도도부현 search — 단일 process로 cookie 컨텍스트 격리.
#    upsert_search_card에서 fetched_at 갱신 → 살아있는 매물 표시.
step "search-all" crawler/scripts/jp_ingest.py search-all \
  --max-pages "$MAX_PAGES" --page-size "$PAGE_SIZE"

# 2) 좌표 + 가격·매각기일 backfill — latitude NULL 또는 가격 변경 감지용.
#    upsert_detail에서 가격 변경 시 jp_valuation_history 자동 기록.
drain "backfill-details-all" crawler/scripts/jp_ingest.py backfill-details-all \
  --limit "$DETAIL_LIMIT"

# 3) 사진 적재 (jp-auction-photos 버킷 + 썸네일)
drain "photos" crawler/scripts/jp_ingest.py photos --limit "$PHOTO_LIMIT"

# 4) 종결 매물 마킹 — BIT 검색에서 사라진 매물(낙찰/절차 정지)을 closed로 변경
step "close-aged" crawler/scripts/jp_ingest.py close-aged --since "$RUN_SINCE_ISO"

# 4) 30일 지난 로그 정리
find "$LOG_DIR" -name 'jp_daily_*.log' -mtime +30 -delete 2>/dev/null || true

echo ""
echo "===== jp_daily run end: $(date -Iseconds) ====="
echo "elapsed: $(( $(date +%s) - START_TS ))s"
