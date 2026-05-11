#!/usr/bin/env bash
# BIT 일일 갱신을 사용자 crontab에 등록/제거.
#
# 사용법:
#   ./install_jp_cron.sh                # 기본 스케줄(매일 05:30 로컬)로 등록
#   ./install_jp_cron.sh install        # 동일
#   ./install_jp_cron.sh show
#   ./install_jp_cron.sh uninstall
#   SCHEDULE="0 6 * * *" ./install_jp_cron.sh
#   PREFECTURES=13,27 ./install_jp_cron.sh   # 특정 도도부현만
#
# macOS 주의:
#   - 노트북 sleep 시 cron 미실행 — 깨어있을 시간대로 설정
#   - 한국(run_daily.sh)과 시간 차이 둬서 동시 실행 충돌 피함

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_SCRIPT="$SCRIPT_DIR/run_jp_daily.sh"
SCHEDULE="${SCHEDULE:-30 5 * * *}"   # 매일 05:30 (한국은 04:00 기본 → 시간 분리)
MARKER="# bit-jp-daily"

build_env_prefix() {
  local out=""
  for v in PREFECTURES PAGE_SIZE MAX_PAGES DETAIL_LIMIT PHOTO_LIMIT \
           MAX_DRAIN_ITERS TIME_BUDGET PYTHON; do
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
  local entry="$SCHEDULE bash -lc '${env_prefix}${RUN_SCRIPT}' $MARKER"

  local tmp
  tmp="$(mktemp)"
  crontab -l 2>/dev/null | grep -v "$MARKER" > "$tmp" || true
  echo "$entry" >> "$tmp"
  crontab "$tmp"
  rm -f "$tmp"

  echo "[ok] installed"
  echo "  schedule : $SCHEDULE"
  echo "  command  : $RUN_SCRIPT"
  [ -n "$env_prefix" ] && echo "  env      : $env_prefix"
  echo ""
  echo "현재 crontab 의 BIT entry:"
  crontab -l | grep "$MARKER"
}

cmd_uninstall() {
  if ! crontab -l 2>/dev/null | grep -q "$MARKER"; then
    echo "[skip] 등록된 entry가 없습니다."
    return 0
  fi
  local tmp
  tmp="$(mktemp)"
  crontab -l 2>/dev/null | grep -v "$MARKER" > "$tmp" || true
  crontab "$tmp"
  rm -f "$tmp"
  echo "[ok] uninstalled"
}

cmd_show() {
  echo "user: $(whoami)"
  echo "host: $(hostname)"
  echo "TZ:   ${TZ:-$(date +%Z)}"
  echo ""
  if crontab -l 2>/dev/null | grep -q "$MARKER"; then
    echo "[installed]"
    crontab -l | grep "$MARKER"
  else
    echo "[not installed]"
  fi
}

case "${1:-install}" in
  install)   cmd_install ;;
  uninstall) cmd_uninstall ;;
  show)      cmd_show ;;
  *)         echo "usage: $0 {install|uninstall|show}"; exit 1 ;;
esac
