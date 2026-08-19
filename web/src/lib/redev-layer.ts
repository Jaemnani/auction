// 정비사업(재개발·재건축) 구역 레이어 — public/redev/*.json
// (crawler/scripts/redev_layer.py 생성. 정찰 근거는 docs/redev_layer_recon.md)
//
// 자료: 서울시 정비사업 정보몽땅 + 서울 도시공간포털(UPIS). 표시용 사본이며
// 참고용이다. 지역(시도) 단위 파일이라 지도가 그 지역일 때만 받는다.

export type RedevRegion = {
  code: string;   // 시도코드 앞 2자리 (11=서울)
  name: string;
  bbox: [number, number, number, number]; // [minLng, minLat, maxLng, maxLat]
  file: string;
  count: number;
};

export type RedevIndex = {
  source: string;
  source_url: string;
  note: string;
  updated: string;
  regions: RedevRegion[];
};

/** 사업 단계 enum — crawler/src/redevelopment/phases.py 의 PHASES 와 값·순서 동일. */
export const REDEV_PHASE_ORDER = [
  "planned", "designated", "committee", "union",
  "plan_approved", "disposal", "construction", "completed", "unknown",
] as const;
export type RedevPhase = (typeof REDEV_PHASE_ORDER)[number];

/** 단계별 라벨·색 — 진행이 깊어질수록 붉은 계열, 완료는 녹색. */
export const REDEV_PHASE_STYLE: Record<RedevPhase, { label: string; fill: string; stroke: string }> = {
  planned:       { label: "계획·준비",      fill: "#94a3b8", stroke: "#475569" },
  designated:    { label: "구역지정",       fill: "#0ea5e9", stroke: "#0369a1" },
  committee:     { label: "추진위·조합준비", fill: "#2563eb", stroke: "#1d4ed8" },
  union:         { label: "조합설립인가",    fill: "#7c3aed", stroke: "#5b21b6" },
  plan_approved: { label: "사업시행인가",    fill: "#d97706", stroke: "#92400e" },
  disposal:      { label: "관리처분인가",    fill: "#ea580c", stroke: "#9a3412" },
  construction:  { label: "이주·철거·착공",  fill: "#dc2626", stroke: "#991b1b" },
  completed:     { label: "준공·완료",      fill: "#16a34a", stroke: "#166534" },
  unknown:       { label: "단계 미확인",    fill: "#a1a1aa", stroke: "#71717a" },
};

export function redevPhaseKey(v: unknown): RedevPhase {
  return REDEV_PHASE_ORDER.includes(v as RedevPhase) ? (v as RedevPhase) : "unknown";
}

const INDEX_URL = "/redev/index.json";

let indexCache: RedevIndex | null = null;
const fileCache = new Map<string, unknown>();

export async function loadRedevIndex(): Promise<RedevIndex | null> {
  if (indexCache) return indexCache;
  try {
    const r = await fetch(INDEX_URL);
    if (!r.ok) return null;
    indexCache = (await r.json()) as RedevIndex;
    return indexCache;
  } catch {
    return null; // 레이어만 없을 뿐 지도 본체엔 영향 없어야 한다
  }
}

/** 지도 화면(bounds)과 겹치는 지역들. 경계 걸침 대비 여유를 준다. */
export function redevRegionsInView(
  index: RedevIndex,
  view: { west: number; south: number; east: number; north: number },
  pad = 0.1,
): RedevRegion[] {
  return index.regions.filter((r) => {
    const [w, s, e, n] = r.bbox;
    return !(e + pad < view.west || w - pad > view.east
      || n + pad < view.south || s - pad > view.north);
  });
}

export async function loadRedevGeoJson(r: RedevRegion): Promise<unknown | null> {
  const hit = fileCache.get(r.code);
  if (hit) return hit;
  try {
    const res = await fetch(r.file);
    if (!res.ok) return null;
    const gj = await res.json();
    fileCache.set(r.code, gj);
    return gj;
  } catch {
    return null;
  }
}
