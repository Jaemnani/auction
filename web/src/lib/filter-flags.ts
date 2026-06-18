// 비활성화된 필터 — 데이터 오분류/미완으로 사용자 노출 차단.
// 근거: 라이브 DB 검증(crawler/scripts/verify_filters.py) + 적대적 리뷰.
// UI(filter-sidebar)는 "준비중"으로 비활성 표시, 서버(queries.applyFilters)는 무시.
// 추후 risk_flags.py 룰 수정 + `ingest.py backfill-risk-flags --force` 후 재활성화.

/** 오분류(주로 과오탐)로 비활성 처리된 risk_flags 코드. */
export const DISABLED_RISK_FLAGS: ReadonlySet<string> = new Set([
  "farm_land",     // lcl=20000(건물) 전체 오태깅 — 실측 건물 5531건 / 실제 토지 0건
  "forest_only",   // usage_mcl_cd 의 "30" 부분문자열 오매칭 (13000/23000 등)
  "senior_tenant", // "대항력" 포함만 검사 → "대항력 없음"(안전)도 매칭
  "stopped",       // csBaseInfo 전체 텍스트의 "중지" 등 무관어 오매칭 (공사중지 등)
  "tiny_area",     // area_summary 의 최솟값 사용 → 대형 토지+소형 건물이 초소형으로
  "new_villa",     // 라벨은 "신축" 이나 연도 없으면 누락 (키워드 미구현)
  "claim_90",      // 청구>감정 흔함 → 임계 노이즈, 과다 제외
]);

/** 파생 카테고리 필터 활성 여부 — 현재 derived_category 데이터 0건이라 비활성. */
export const DERIVED_FILTER_ENABLED = false;
