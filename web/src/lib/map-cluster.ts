// 지도 좌표 겹침 처리 공용 유틸 (KR/JP 지도 공용).
// 같은 좌표에 여러 매물이 있으면 마커가 포개져 클릭 시 엉뚱한 매물이 잡힘 →
// 좌표별로 묶어 (1) 겹치면 개수 배지 마커, (2) 팝업에 선택 가능한 목록을 노출.

/** 겹친 매물 수를 표시하는 원형 배지 DOM (브라우저 전용 — useEffect 안에서 호출). */
export function makeCountBadgeEl(count: number): HTMLElement {
  const el = document.createElement("div");
  el.textContent = String(count);
  el.setAttribute("aria-label", `이 위치에 ${count}건`);
  el.style.cssText = [
    "width:28px", "height:28px", "border-radius:50%",
    "background:#0f172a", "color:#fff",
    "display:flex", "align-items:center", "justify-content:center",
    "font-size:12px", "font-weight:700", "line-height:1",
    "border:2px solid #fff", "box-shadow:0 1px 4px rgba(0,0,0,.45)",
    "cursor:pointer",
  ].join(";");
  return el;
}

/** rows를 좌표(소수 6자리)로 그룹핑. 반환 순서는 입력 순서 유지. */
export function groupByCoord<T>(
  rows: T[], lng: (r: T) => number, lat: (r: T) => number,
): T[][] {
  const groups = new Map<string, T[]>();
  for (const r of rows) {
    const key = `${lng(r).toFixed(6)},${lat(r).toFixed(6)}`;
    const g = groups.get(key);
    if (g) g.push(r);
    else groups.set(key, [r]);
  }
  return [...groups.values()];
}

/** 팝업 목록에 표시할 최대 항목 수 (초과분은 "외 N건" 안내). */
export const CLUSTER_LIST_MAX = 25;
