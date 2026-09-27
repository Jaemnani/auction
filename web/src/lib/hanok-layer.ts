// 서울 한옥 레이어 — public/hanok/*.json (crawler/scripts/hanok_layer.py 생성).
// 근거·절차·라이선스는 docs/hanok_layer.md.
//
// 레이어 3종:
//   preservation  한옥보전구역 공식 경계 (공고 PDF → 수작업 디지타이징, 공고일 포함)
//   district      지구단위계획구역 중 한옥 밀집 동네 — "대략 범위" 배경일 뿐
//   registry      등록한옥 (주소 지오코딩 대표 위치 점)
// 서울 한정이라 파일이 작다 — 지역 lazy 로드 없이 켤 때 한 번에 받는다.

export const HANOK_LAYER_ORDER = ["preservation", "district", "registry"] as const;
export type HanokLayerKey = (typeof HANOK_LAYER_ORDER)[number];

export type HanokLayerInfo = {
  label: string;
  source: string;
  source_url: string;
  license?: string;
  file: string;
  count: number;
  bbox: [number, number, number, number];
  built: string;
  notice_date?: string; // preservation 만 — 공고일
};

export type HanokIndex = {
  note: string;
  disclaimer: string;
  updated: string;
  layers: Partial<Record<HanokLayerKey, HanokLayerInfo>>;
};

/** 레이어별 색·범례 라벨. 보전구역은 공식 경계라 가장 진하게, 지구단위계획은
 *  배경이라 옅게. 정비사업(단계별 청·적·등색)·소음(황·적색)과 겹치지 않는 색. */
export const HANOK_STYLE: Record<HanokLayerKey, {
  label: string; fill: string; stroke: string; fillOpacity: number; strokeWeight: number;
}> = {
  preservation: { label: "한옥보전구역",       fill: "#db2777", stroke: "#9d174d", fillOpacity: 0.22, strokeWeight: 2 },
  district:     { label: "한옥 동네 대략 범위", fill: "#0d9488", stroke: "#0f766e", fillOpacity: 0.07, strokeWeight: 1 },
  registry:     { label: "등록한옥",           fill: "#44403c", stroke: "#ffffff", fillOpacity: 0.9,  strokeWeight: 1.5 },
};

export const HANOK_DISCLAIMER = "공간정보는 참고용이며 지원 여부는 서울시 심의로 결정됩니다";

export function hanokLayerKey(v: unknown): HanokLayerKey | null {
  return HANOK_LAYER_ORDER.includes(v as HanokLayerKey) ? (v as HanokLayerKey) : null;
}

const INDEX_URL = "/hanok/index.json";

let indexCache: HanokIndex | null = null;
const fileCache = new Map<string, unknown>();

export async function loadHanokIndex(): Promise<HanokIndex | null> {
  if (indexCache) return indexCache;
  try {
    const r = await fetch(INDEX_URL);
    if (!r.ok) return null;
    indexCache = (await r.json()) as HanokIndex;
    return indexCache;
  } catch {
    return null; // 레이어만 없을 뿐 지도 본체엔 영향 없어야 한다
  }
}

export async function loadHanokGeoJson(info: HanokLayerInfo): Promise<unknown | null> {
  const hit = fileCache.get(info.file);
  if (hit) return hit;
  try {
    const res = await fetch(info.file);
    if (!res.ok) return null;
    const gj = await res.json();
    fileCache.set(info.file, gj);
    return gj;
  } catch {
    return null;
  }
}
