#!/usr/bin/env bash
# courtauction 일일 갱신을 사용자 crontab에 등록/제거.
#
# 사용법:
#   ./install_cron.sh          # 기본 스케줄(매일 04:00 KST)로 등록
#   ./install_cron.sh install  # 동일
#   ./install_cron.sh show     # 현재 등록 상태 확인
#   ./install_cron.sh uninstall  # 제거
#   SCHEDULE="0 5 * * *" ./install_cron.sh   # 다른 시간 (오전 5시)
#   COURT=B000210 ./install_cron.sh           # 특정 법원만 갱신
#
# macOS 주의:
#   - System Settings → Privacy & Security → Full Disk Access 에 'cron' 추가가
#     필요할 수 있음 (특히 sandbox 디렉토리 접근 시).
#   - 노트북이 sleep 상태면 cron이 안 돌아감. 일정 시간을 깨어있는 시간대로 잡으세요.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_SCRIPT="$SCRIPT_DIR/run_daily.sh"
SCHEDULE="${SCHEDULE:-0 4 * * *}"   # 매일 04:00 (시스템 로컬타임)
MARKER="# courtauction-daily"        # 우리가 추가한 line을 식별
# 낙찰 예상가 모델 학습 — 주 1회 (일요일 03:00, 일일 크롤 04:00 전).
# 예측(predict)은 run_daily.sh 가 매일 수행 — 여기선 train+evaluate 만.
TRAIN_SCHEDULE="${TRAIN_SCHEDULE:-0 3 * * 0}"
TRAIN_MARKER="# auction-estimator-train"
PYTHON_BIN="${PYTHON:-/Users/jaemoonyeah/workspace/venv_common/bin/python}"
ESTIMATE_SCRIPT="$SCRIPT_DIR/scripts/estimate.py"

# env 변수 prefix 만들기 (있는 것만)
build_env_prefix() {
  local out=""
  for v in COURT PAGE_SIZE MAX_PAGES DETAIL_ITER_LIMIT PHOTO_LIMIT THUMB_LIMIT \
           MAX_DRAIN_ITERS TIME_BUDGET PHOTOS_PER_PROPERTY SALES_DAYS \
           REVERSE_GEOCODE_LIMIT PYTHON; do
    if [ -n "${!v:-}" ]; then
      out+="${v}=$(printf '%q' "${!v}") "
    fi
  done
  echo "$out"
}

cmd_install() {
  if [ ! -x "$RUN_SCRIPT" ]; then
    chmod +x "$RUN_SCRIPT"
  fi

  local env_prefix
  env_prefix="$(build_env_prefix)"

  # cron entry — bash -lc로 사용자 login 환경 로드 (PATH 등)
  local entry="$SCHEDULE bash -lc '${env_prefix}${RUN_SCRIPT}' $MARKER"

  # 주간 모델 학습 entry — train 후 evaluate (품질 게이트 로그)
  local train_entry="$TRAIN_SCHEDULE bash -lc '$PYTHON_BIN $ESTIMATE_SCRIPT train && $PYTHON_BIN $ESTIMATE_SCRIPT evaluate' $TRAIN_MARKER"

  # 기존 marker 라인 제거 → 새 entry 추가
  local tmp
  tmp="$(mktemp)"
  crontab -l 2>/dev/null | grep -v -e "$MARKER" -e "$TRAIN_MARKER" > "$tmp" || true
  echo "$entry" >> "$tmp"
  echo "$train_entry" >> "$tmp"
  crontab "$tmp"
  rm -f "$tmp"

  echo "[ok] installed"
  echo "  schedule : $SCHEDULE (daily crawl) / $TRAIN_SCHEDULE (estimator train)"
  echo "  command  : $RUN_SCRIPT"
  [ -n "$env_prefix" ] && echo "  env      : $env_prefix"
  echo ""
  echo "현재 crontab 의 우리 entry:"
  crontab -l | grep -e "$MARKER" -e "$TRAIN_MARKER"
}

cmd_uninstall() {
  if ! crontab -l 2>/dev/null | grep -q -e "$MARKER" -e "$TRAIN_MARKER"; then
    echo "[skip] 등록된 entry가 없습니다."
    return 0
  fi
  local tmp
  tmp="$(mktemp)"
  crontab -l 2>/dev/null | grep -v -e "$MARKER" -e "$TRAIN_MARKER" > "$tmp" || true
  crontab "$tmp"
  rm -f "$tmp"
  echo "[ok] uninstalled"
}

cmd_show() {
  echo "user: $(whoami)"
  echo "host: $(hostname)"
  echo "TZ:   ${TZ:-$(date +%Z)}"
  echo ""
  if crontab -l 2>/dev/null | grep -q -e "$MARKER" -e "$TRAIN_MARKER"; then
    echo "[installed]"
    crontab -l | grep -e "$MARKER" -e "$TRAIN_MARKER"
  else
    echo "[not installed]"
  fi
  echo ""
  echo "다음 실행 예상시각 (지정한 SCHEDULE='$SCHEDULE'):"
  python3 -c "
from datetime import datetime, timedelta
# 단순 매일 N시 케이스만 안내 (5필드 풀 파싱은 생략)
parts = '$SCHEDULE'.split()
if len(parts) == 5 and parts[2:5] == ['*','*','*'] and parts[0].isdigit() and parts[1].isdigit():
    m, h = int(parts[0]), int(parts[1])
    now = datetime.now()
    nxt = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if nxt <= now: nxt += timedelta(days=1)
    print(f'  {nxt.isoformat()}')
else:
    print('  (복잡한 스케줄은 https://crontab.guru 에서 확인)')
"
}

case "${1:-install}" in
  install)   cmd_install ;;
  uninstall) cmd_uninstall ;;
  show)      cmd_show ;;
  *)         echo "usage: $0 {install|uninstall|show}"; exit 1 ;;
esac
