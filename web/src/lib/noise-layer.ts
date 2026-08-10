// 공항 소음등고선 레이어 — public/noise/*.json (crawler/scripts/noise_layer.py 생성).
//
// 자료: 공항소음포털(airportnoise.kr). 표시용 사본이며 참고용이다
// (원 사이트도 "모든 주제도는 참고용" 고지). 근거·라이선스는 docs/airport_noise_layer.md.
//
// 파일이 공항당 100KB~1.2MB 라 **지도가 그 공항 근처일 때만** 받는다.
// 전국 뷰에서 6개를 다 받으면 2.6MB 라 의미 없이 무겁다.

export type NoiseAirport = {
  code: string;
  name: string;
  year: number;
  bbox: [number, number, number, number]; // [minLng, minLat, maxLng, maxLat]
  file: string;
};

export type NoiseIndex = {
  source: string;
  source_url: string;
  note: string;
  airports: NoiseAirport[];
};

/** WECPNL → 색. 소음이 셀수록 붉게. 낮은 등급이 아래 깔리도록 파일이 정렬돼 있다. */
export const ZONE_STYLE: Record<number, { fill: string; stroke: string }> = {
  95: { fill: "#b91c1c", stroke: "#7f1d1d" }, // 제1종
  90: { fill: "#ea580c", stroke: "#9a3412" }, // 제2종
  85: { fill: "#f59e0b", stroke: "#b45309" }, // 제3종 가
  80: { fill: "#eab308", stroke: "#a16207" }, // 제3종 나
  75: { fill: "#84cc16", stroke: "#4d7c0f" }, // 제3종 다
  70: { fill: "#38bdf8", stroke: "#0369a1" }, // 참고(대책지역 밖)
};

const INDEX_URL = "/noise/index.json";

let indexCache: NoiseIndex | null = null;
const fileCache = new Map<string, unknown>();

export async function loadNoiseIndex(): Promise<NoiseIndex | null> {
  if (indexCache) return indexCache;
  try {
    const r = await fetch(INDEX_URL);
    if (!r.ok) return null;
    indexCache = (await r.json()) as NoiseIndex;
    return indexCache;
  } catch {
    return null; // 레이어만 없을 뿐 지도 본체엔 영향 없어야 한다
  }
}

/** 지도 화면(bounds)과 겹치는 공항들. 등고선은 BBOX 밖으로도 퍼지므로 여유를 준다. */
export function airportsInView(
  index: NoiseIndex,
  view: { west: number; south: number; east: number; north: number },
  pad = 0.25,
): NoiseAirport[] {
  return index.airports.filter((a) => {
    const [w, s, e, n] = a.bbox;
    return !(e + pad < view.west || w - pad > view.east
      || n + pad < view.south || s - pad > view.north);
  });
}

export async function loadAirportGeoJson(a: NoiseAirport): Promise<unknown | null> {
  const hit = fileCache.get(a.code);
  if (hit) return hit;
  try {
    const r = await fetch(a.file);
    if (!r.ok) return null;
    const gj = await r.json();
    fileCache.set(a.code, gj);
    return gj;
  } catch {
    return null;
  }
}
