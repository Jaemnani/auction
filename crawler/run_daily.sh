#!/usr/bin/env bash
# courtauction → Supabase 일일 갱신.
# cron 등록은 ./install_cron.sh로.
#
# 흐름:
#   masters → search(전국 페이징) → 신규 detail/사진/썸네일/좌표/주소 백필
#   백필은 drain 루프 — 한 번에 처리 못 하면 다음 iter에서 이어서 처리
#
# 환경변수:
#   COURT=B000210         특정 법원만 (기본: 전국)
#   PAGE_SIZE=50          검색 페이지 크기 (서버 상한)
#   MAX_PAGES=10          검색 페이지 상한 (기본: 무제한)
#   DETAIL_LIMIT=500      detail 백필 1회 처리량
#   PHOTO_LIMIT=1000      사진 적재 1회 처리량
#   THUMB_LIMIT=1000      썸네일 생성 1회 처리량
#   MAX_DRAIN_ITERS=20    drain 루프 최대 반복
#   TIME_BUDGET=7200      전체 예산 (초). 초과 시 남은 step 건너뜀
#   PHOTOS_PER_PROPERTY=1 매물당 사진 N장만 저장 (무료 5GB 안전), ""=전체
#   SALES_DAYS=7          매각결과 조회 기간 (오늘 기준 N일 전까지)
#   REVERSE_GEOCODE_LIMIT=2000  Kakao 역지오코딩 1회 처리량 (KAKAO_REST_API_KEY 필요)
#   PYTHON=/path/...      (기본: 공용 venv)
#
# 모든 stdout/stderr → crawler/data/logs/daily_<timestamp>.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON="${PYTHON:-/Users/ohyeahdani_m1/workspace/venv_common/bin/python}"
LOG_DIR="$PROJECT_ROOT/crawler/data/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/daily_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

# --- 동시 실행 방지 ---
LOCK_DIR="$PROJECT_ROOT/crawler/data/.daily.lock.d"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[skip] another run in progress (lock=$LOCK_DIR)"
  echo "       stale이면 'rmdir $LOCK_DIR' 후 재시도"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

# --- 사전 점검 ---
[ -x "$PYTHON" ] || { echo "[fatal] python not found: $PYTHON"; exit 1; }
[ -f "$PROJECT_ROOT/.env" ] || { echo "[fatal] .env missing"; exit 1; }

# .env 자동 로드 — cron은 sh 환경이 비어있으니 모든 키(KAKAO/DATA_GO_KR/SUPABASE)를 .env에서 읽음.
# 이래야 cron 재설치 없이 .env 변경만으로 새 키 적용됨.
set -a
# shellcheck disable=SC1091
. "$PROJECT_ROOT/.env"
set +a

# --- 설정 ---
COURT="${COURT:-}"
PAGE_SIZE="${PAGE_SIZE:-50}"
MAX_PAGES="${MAX_PAGES:-}"
DETAIL_LIMIT="${DETAIL_LIMIT:-500}"
PHOTO_LIMIT="${PHOTO_LIMIT:-1000}"
THUMB_LIMIT="${THUMB_LIMIT:-1000}"
MAX_DRAIN_ITERS="${MAX_DRAIN_ITERS:-20}"
TIME_BUDGET="${TIME_BUDGET:-7200}"
export PHOTOS_PER_PROPERTY="${PHOTOS_PER_PROPERTY:-1}"

START_TS=$(date +%s)
budget_left() { echo $((TIME_BUDGET - ($(date +%s) - START_TS))); }

# 단순 1회 step
step() {
  local label="$1"; shift
  if [ "$(budget_left)" -le 0 ]; then
    echo "[skip] '$label' — TIME_BUDGET 소진"
    return
  fi
  local rc=0
  echo ""
  echo "==== $(date -Iseconds) [$label] (budget ${TIME_BUDGET_LEFT:-$(budget_left)}s left) ===="
  "$PYTHON" "$@" || rc=$?
  # 주의: '[ ... ] && echo ...' 단순 패턴은 rc=0 일 때 마지막 expr 이 false 가 되어
  # 함수가 exit 1 로 끝나고 set -e 트리거 → 스크립트 silent kill.
  # if/then/fi 또는 끝에 || true 로 명시.
  if [ "$rc" -ne 0 ]; then
    echo "[warn] step '$label' exited $rc — 다음 step 계속"
  fi
}

# drain 루프 — 출력에서 'ok N' 또는 'updated N' 가 0이거나 'requested 0'이면 종료
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
    # 종결 조건: 'requested': 0  또는  'ok': 0 으로 끝남 또는 candidates: 0
    if echo "$out" | grep -qE "'requested': 0|candidates: 0"; then
      echo "[drain] $label — 처리할 row 없음, 종료"
      return
    fi
  done
  echo "[drain] $label — MAX_DRAIN_ITERS($MAX_DRAIN_ITERS) 도달, 다음 step으로"
}

echo "===== courtauction daily run start: $(date -Iseconds) ====="
echo "log:    $LOG"
echo "python: $PYTHON"
echo "court:  ${COURT:-<all>}  PHOTOS_PER_PROPERTY=$PHOTOS_PER_PROPERTY"
echo "budget: ${TIME_BUDGET}s ($((TIME_BUDGET / 60))분)"

# search 시작 직전 capture — 이 시각 이전 last_synced_at 매물은 close-aged 대상
# (search 한 바퀴 돌면 살아있는 매물은 모두 last_synced_at 갱신됨)
RUN_SINCE_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "since:  $RUN_SINCE_ISO (search 후 이 시각 이전 last_synced_at 매물 → soft delete)"

# 1) 마스터 코드 (5초)
step "masters" crawler/scripts/ingest.py masters

# 2) 검색 (페이징 자동) — 전국이면 ~30분, 특정 법원이면 분 단위
if [ -n "$COURT" ]; then
  step "search ($COURT)" crawler/scripts/ingest.py search \
    --court "$COURT" --page-size "$PAGE_SIZE" \
    ${MAX_PAGES:+--max-pages "$MAX_PAGES"}
else
  step "search (all)"    crawler/scripts/ingest.py search \
    --page-size "$PAGE_SIZE" \
    ${MAX_PAGES:+--max-pages "$MAX_PAGES"}
fi

# 3) detail 백필 — 신규 분 모두 처리할 때까지 drain
drain "backfill-details" crawler/scripts/ingest.py backfill-details \
  --limit "$DETAIL_LIMIT" ${COURT:+--court "$COURT"}

# 4) 사진 base64 → Storage
drain "backfill-photos" crawler/scripts/ingest.py backfill-photos --limit "$PHOTO_LIMIT"

# 5) 썸네일 생성
drain "backfill-thumbs" crawler/scripts/ingest.py backfill-thumbs --limit "$THUMB_LIMIT"

# 6) 좌표/주소 후처리 (한 번이면 끝)
step "backfill-coords" crawler/scripts/ingest.py backfill-coords
step "backfill-addrs"  crawler/scripts/ingest.py backfill-addrs

# 6b) Kakao 역지오코딩 — 도로명 누락 매물 보강 (KAKAO_REST_API_KEY 필요)
if [ -n "${KAKAO_REST_API_KEY:-}" ]; then
  RG_LIMIT="${REVERSE_GEOCODE_LIMIT:-2000}"
  drain "reverse-geocode" crawler/scripts/ingest.py reverse-geocode \
    --limit "$RG_LIMIT" --concurrency 8
else
  echo "[skip] reverse-geocode — KAKAO_REST_API_KEY not set"
fi

# 7) 매각결과 (종결 사건) 수집 — 인근 낙찰 통계 기반
# SALES_DAYS 환경변수로 조회 기간 조정 가능 (기본: 7일 = 어제~오늘 새 매각결과)
SALES_DAYS="${SALES_DAYS:-7}"
SALES_FROM="$(/bin/date -v-${SALES_DAYS}d +%Y%m%d 2>/dev/null || /bin/date -d "${SALES_DAYS} days ago" +%Y%m%d)"
SALES_TO="$(/bin/date +%Y%m%d)"
step "sales-results ($SALES_FROM~$SALES_TO)" crawler/scripts/ingest.py sales-results \
  --bid-from "$SALES_FROM" --bid-to "$SALES_TO"

# 8) 파생 카테고리 (전원주택/도심단독/농가/별장) — 신규 단독·다가구 매물 자동 분류.
#    GEMINI_API_KEY 있으면 룰 미분류 매물에 Gemini Flash Lite 보강 (매물당 ~$0.00004).
if [ -n "${GEMINI_API_KEY:-}" ]; then
  step "backfill-categories (rule+LLM)" crawler/scripts/ingest.py backfill-categories --llm
else
  step "backfill-categories (rule only)" crawler/scripts/ingest.py backfill-categories
fi

# 9) 종결 매물 soft delete — search에서 사라진 매물(낙찰/취하)을 UI에서 자동 제외.
#    deleted_at 채움. list/map query 가 `.is_("deleted_at", "null")` 필터라 자동 적용.
#    raw_responses/사진/detail_result 는 보존 (통계·복구 가능).
step "close-aged" crawler/scripts/ingest.py close-aged --since "$RUN_SINCE_ISO"

# --- 30일 이상 로그 정리 ---
find "$LOG_DIR" -name "daily_*.log" -mtime +30 -delete 2>/dev/null || true

ELAPSED=$(( $(date +%s) - START_TS ))
echo ""
echo "===== courtauction daily run done: $(date -Iseconds) (${ELAPSED}s = $((ELAPSED / 60))분) ====="
