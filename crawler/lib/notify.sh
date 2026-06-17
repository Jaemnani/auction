#!/usr/bin/env bash
# Discord 크롤 알림 — run_daily.sh / run_jp_daily.sh 가 source 해서 사용.
#
# 환경변수:
#   DISCORD_WEBHOOK_URL   미설정이면 모든 함수가 조용히 no-op (기존 동작 불변).
#   PYTHON                JSON 인코딩용 (없으면 python3 fallback).
#
# 함수:
#   discord_send <content>                          — 메시지 1건 POST
#   discord_digest <log> <rc> <elapsed_s> <label>   — $LOG 파싱해 요약 메시지 발송
#
# 단독 테스트:  DISCORD_WEBHOOK_URL=<url> bash crawler/lib/notify.sh test

# Discord content 길이 상한 (실제 2000자, 여유 두고 1900).
_DISCORD_MAX=1900

# content 문자열을 Discord webhook 으로 전송. URL 없으면 no-op.
# 웹훅 실패가 크롤을 죽이지 않도록 모든 에러를 삼킨다.
discord_send() {
  local content="$1"
  [ -n "${DISCORD_WEBHOOK_URL:-}" ] || return 0
  [ -n "$content" ] || return 0

  local py="${PYTHON:-python3}"
  [ -x "$py" ] || py="python3"

  # 1900자 truncate (한글은 멀티바이트 — 문자 수 기준으로 자르고 표식 추가)
  local payload
  payload=$(printf '%s' "$content" | "$py" -c '
import json, sys
s = sys.stdin.read()
MAX = '"$_DISCORD_MAX"'
if len(s) > MAX:
    s = s[:MAX] + "\n…(잘림)"
sys.stdout.write(json.dumps({"content": s}))
' 2>/dev/null) || return 0
  [ -n "$payload" ] || return 0

  curl -sS --max-time 10 \
    -H "Content-Type: application/json" \
    -X POST "$DISCORD_WEBHOOK_URL" \
    --data "$payload" >/dev/null 2>&1 || true
}

# 런 종료 요약 — $LOG 를 파싱해 상태/소요시간/스텝 totals/경고를 한 메시지로.
#   $1 log_file   $2 exit_rc   $3 elapsed_s   $4 label
discord_digest() {
  local log="$1" rc="${2:-0}" elapsed="${3:-0}" label="${4:-크롤}"
  [ -n "${DISCORD_WEBHOOK_URL:-}" ] || return 0

  # 주의: 'status' 는 zsh 에서 read-only 특수변수 → 'run_state' 사용.
  local has_ipblock="" has_warn="" run_state
  [ -f "$log" ] && grep -q "\[IP-BLOCKED\]" "$log" 2>/dev/null && has_ipblock=1
  [ -f "$log" ] && grep -q "\[warn\] step" "$log" 2>/dev/null && has_warn=1

  if [ -n "$has_ipblock" ]; then
    run_state="⚠️ IP차단으로 조기종료"
  elif [ "$rc" -ne 0 ]; then
    run_state="❌ 실패 (exit $rc)"
  elif [ -n "$has_warn" ]; then
    run_state="⚠️ 완료 (일부 스텝 경고)"
  else
    run_state="✅ 완료"
  fi

  local mins=$(( elapsed / 60 ))
  local host; host=$(hostname 2>/dev/null || echo "?")

  # 스텝별 totals — 각 ingest 명령이 찍는 '[done] …' 라인. 라인당 200자 truncate.
  local steps=""
  if [ -f "$log" ]; then
    steps=$(grep '^\[done\]' "$log" 2>/dev/null | sed 's/^\[done\] *//; s/\(.\{200\}\).*/\1…/' || true)
  fi

  # 경고/스킵 라인
  local warns=""
  if [ -f "$log" ]; then
    warns=$(grep -E '\[warn\] step|\[IP-BLOCKED\]|\[skip\].*TIME_BUDGET' "$log" 2>/dev/null \
              | sed 's/\(.\{180\}\).*/\1…/' || true)
  fi

  local msg
  msg="**${label}** — ${run_state}
🕒 ${mins}분 (${elapsed}s) · 🖥 ${host} · $(date -Iseconds)"
  if [ -n "$steps" ]; then
    msg="${msg}

__스텝 결과__
\`\`\`
${steps}
\`\`\`"
  fi
  if [ -n "$warns" ]; then
    msg="${msg}
__경고/스킵__
\`\`\`
${warns}
\`\`\`"
  fi

  discord_send "$msg"
}

# 단독 실행 시 테스트 메시지 1건.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  if [ "${1:-}" = "test" ]; then
    if [ -z "${DISCORD_WEBHOOK_URL:-}" ]; then
      echo "[notify-test] DISCORD_WEBHOOK_URL 미설정 — no-op (정상). 설정 후 다시 시도하세요."
      exit 0
    fi
    discord_send "✅ **Discord 알림 테스트** — $(hostname 2>/dev/null) · $(date -Iseconds)
크롤 알림 연결이 정상입니다."
    echo "[notify-test] 전송 시도 완료 — Discord 채널을 확인하세요."
  else
    echo "usage: DISCORD_WEBHOOK_URL=<url> bash $0 test"
  fi
fi
