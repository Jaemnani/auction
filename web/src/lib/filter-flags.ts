// 비활성화된 필터 — 데이터 오분류/미완으로 사용자 노출 차단.
// 근거: 라이브 DB 검증(crawler/scripts/verify_filters.py) + 적대적 리뷰.
// UI(filter-sidebar)는 "준비중"으로 비활성 표시, 서버(queries.applyFilters)는 무시.
//
// risk_flags.py 룰 7종 교정 + backfill --force 완료(2026-06-19) → 6종 재활성화.
// 검증: farm_land 건물오태깅 5531→5, stopped=auctnSuspStatCd(887) 정확,
//       forest_only/senior_tenant/tiny_area/claim_90 정상.

/** 아직 비활성 처리된 risk_flags 코드. */
export const DISABLED_RISK_FLAGS: ReadonlySet<string> = new Set([
  "new_villa",     // 룰 교정(신축 키워드) 후에도 라이브 매칭 0건 — 데이터에 신호 없어 무용
]);

// 파생 카테고리 — backfill-categories 완료(2026-06-19, 789행 분류) → 활성화.
// 검증: townhouse 597 / country_house 191 / farm_house 10 / vacation_home 0.

/** 파생 카테고리 필터 활성 여부. */
export const DERIVED_FILTER_ENABLED = true;

/** 활성 섹션 내에서 개별 비활성 처리된 derived 코드. */
export const DISABLED_DERIVED: ReadonlySet<string> = new Set([
  "vacation_home", // 별장/펜션/산장 키워드가 주소에 거의 없어 라이브 매칭 0건
]);
