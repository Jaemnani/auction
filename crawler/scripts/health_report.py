"""데이터 헬스 리포트 — 파이프라인이 감당되는지 매일 숫자로 판단하는 상황판.

경매 데이터의 3대 요건을 축으로 측정:
  1) 빠질 데이터가 빠지는가 — 종결 처리(close-aged), 기일 지난 잔존 매물
  2) 들어올 데이터가 들어오는가 — 신규 유입, detail 백로그(특히 매각기일 임박분)
  3) 갱신이 제때 되는가 — search 재확인 신선도, 좌표/주소/분류 커버리지

처리량 대비 백로그 소진 전망(crawl_runs 실측)을 함께 계산해 "감당 가능/불가"를
판정한다. 임계 초과 시 '[warn] step' 형식으로 출력 → run_daily의 Discord
다이제스트 경고 섹션에 자동 노출. 마지막에 '[done] health → …' 한 줄 요약.

DB-only(수 초), courtauction 무접촉. 단독 실행:
  SUPABASE_URL=... python crawler/scripts/health_report.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "crawler"))
sys.path.insert(0, str(PROJECT_ROOT / "crawler" / "src"))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from courtauction.store import Store  # noqa: E402

# 판정 임계값 — 초과 시 [warn] 승격
WARN_D7_DETAIL_MISSING = 300     # 매각기일 7일 이내인데 detail 없음
WARN_DRAIN_DAYS = 10             # 백로그 소진 예상일
WARN_PAST_SALE_ACTIVE = 300      # 기일 지났는데 미종결 (close-aged 이상 신호)
WARN_STALE_SEEN_H = 48           # search에서 이 시간 이상 재확인 안 된 활성 매물


def main() -> None:
    store = Store()
    sb = store.sb
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    d7 = (now.date() + timedelta(days=7)).isoformat()
    h24 = (now - timedelta(hours=24)).isoformat()
    h48 = (now - timedelta(hours=WARN_STALE_SEEN_H)).isoformat()

    def count(build) -> int:
        q = sb.table("properties").select("id", count="exact").limit(1)
        res = build(q).execute()
        return res.count or 0

    # ---- 1) 빠질 데이터 ----
    active = count(lambda q: q.is_("deleted_at", "null"))
    closed_24h = count(lambda q: q.not_.is_("deleted_at", "null")
                       .gte("deleted_at", h24))
    # 기일이 지났는데 아직 활성 — 어제 기일은 매각결과 반영 대기라 정상,
    # 이틀 이상 지난 것만 이상 신호로 센다.
    past2 = (now.date() - timedelta(days=2)).isoformat()
    past_sale_active = count(lambda q: q.is_("deleted_at", "null")
                             .lt("sale_date", past2))

    # ---- 2) 들어올 데이터 ----
    new_24h = count(lambda q: q.gte("first_seen_at", h24))
    backlog = count(lambda q: q.is_("deleted_at", "null")
                    .is_("detail_synced_at", "null"))
    backlog_d7 = count(lambda q: q.is_("deleted_at", "null")
                       .is_("detail_synced_at", "null")
                       .gte("sale_date", today).lte("sale_date", d7))
    refresh_pending = count(lambda q: q.is_("deleted_at", "null")
                            .not_.is_("detail_refresh_requested_at", "null"))

    # 처리량 실측 — 최근 7일 backfill_details 런의 ok 합계 / 일수
    day_rate = 0.0
    try:
        runs = (sb.table("crawl_runs").select("started_at, totals")
                .eq("job_type", "backfill_details")
                .gte("started_at", (now - timedelta(days=7)).isoformat())
                .execute().data or [])
        oks = [int((r.get("totals") or {}).get("ok") or 0) for r in runs]
        days = {r["started_at"][:10] for r in runs}
        if days:
            day_rate = sum(oks) / len(days)
    except Exception as e:  # noqa: BLE001 — 리포트가 크롤을 죽이면 안 됨
        print(f"  (crawl_runs 조회 실패 — 처리량 생략: {e})")
    drain_days = (backlog / day_rate) if day_rate > 0 else float("inf")

    # ---- 3) 갱신/커버리지 (활성 매물 기준) ----
    stale_seen = count(lambda q: q.is_("deleted_at", "null")
                       .lt("last_seen_at", h48))
    no_coords = count(lambda q: q.is_("deleted_at", "null")
                      .is_("location", "null"))
    no_addr = count(lambda q: q.is_("deleted_at", "null")
                    .is_("road_addr", "null").is_("lot_addr", "null"))
    # 파생 카테고리 미분류 — 단독 계열 & 건물 물건인데 빈 배열 (가드 제외분은
    # 지분·토지라 빠지는 게 정상. 여기 잡히는 건 재분류 누락 신호)
    uncat = count(lambda q: q.is_("deleted_at", "null")
                  .in_("usage_nm", ["단독주택", "단독주택다가구", "다가구주택"])
                  .eq("derived_category", "{}")
                  .like("conv_addr", "[건물%")
                  .not_.ilike("conv_addr", "%지분%")
                  .not_.ilike("conv_addr", "%분의%")
                  .not_.contains("risk_flags", ["share_sale"]))

    # ---- 출력 ----
    pct = lambda n: f"{n} ({n * 100 // max(active, 1)}%)"  # noqa: E731
    drain_s = "∞" if drain_days == float("inf") else f"{drain_days:.1f}일"
    print(f"""
  [빠짐] 활성 {active:,} · 24h 종결 {closed_24h:,} · 기일 D+2 경과 잔존 {past_sale_active:,}
  [유입] 24h 신규 {new_24h:,} · detail 백로그 {backlog:,} (이 중 D-7 {backlog_d7:,}) · 재수집 대기 {refresh_pending:,}
  [처리량] detail {day_rate:.0f}건/일 (7일 실측) → 백로그 소진 ~{drain_s}
  [갱신] 48h 미재확인 {stale_seen:,} · 좌표 없음 {pct(no_coords)} · 주소 없음 {pct(no_addr)} · 분류 누락 {uncat:,}""")

    # ---- 판정 → [warn] (다이제스트 경고 섹션에 노출) ----
    warns: list[str] = []
    if backlog_d7 > WARN_D7_DETAIL_MISSING:
        warns.append(f"D-7 매물 detail 누락 {backlog_d7:,}건 — 입찰 임박 매물이 반쪽 데이터")
    if drain_days > WARN_DRAIN_DAYS:
        warns.append(f"백로그 소진 {drain_s} — 처리량 부족, 수집 범위 축소 검토"
                     f" (예: 기일 임박·핵심 용도 우선)")
    if past_sale_active > WARN_PAST_SALE_ACTIVE:
        warns.append(f"기일 D+2 경과 활성 {past_sale_active:,}건 — close-aged/매각결과 반영 점검")
    if stale_seen > active * 0.1:
        warns.append(f"48h 미재확인 {stale_seen:,}건(활성의 10%+) — search 완주 실패 의심")
    for w in warns:
        print(f"[warn] step 'health' — {w}")

    verdict = "정상" if not warns else f"주의 {len(warns)}건"
    print(f"[done] health → {verdict} | 활성 {active:,} 신규 {new_24h:,} 종결 {closed_24h:,} "
          f"| 백로그 {backlog:,} (D-7 {backlog_d7:,}) {day_rate:.0f}건/일 소진~{drain_s} "
          f"| 좌표무 {no_coords:,} 주소무 {no_addr:,} 분류누락 {uncat:,}")


if __name__ == "__main__":
    main()
