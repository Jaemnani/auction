// detail_result.properties[].fields 의 일본어 키에서 면적·동호수 추출.
// fields 키는 매물 종별마다 다르므로 후보 키를 순차 검색.

export type JpDetailProperty = {
  head?: string | null;
  fields?: Record<string, string> | null;
};

const AREA_KEYS = [
  "土地面積（登記）",
  "土地面積（現況）",
  "床面積（登記）",
  "床面積（現況）",
  "専有面積（登記）",
  "専有面積（現況）",
  // 全角 () 변형
  "土地面積(登記)",
  "床面積(登記)",
  "専有面積(登記)",
];

const DONG_HO_KEYS = ["号室", "建物の名称", "棟番号", "部屋番号"];

function _stripParens(t: string): string {
  // "１０４．９４m 2" 등 BS 파서 결과 정리: " 2" → "²" 표기 통일
  return t.replace(/\bm\s*2\b/g, "㎡").replace(/\s+/g, " ").trim();
}

export function extractJpArea(props: JpDetailProperty[] | null | undefined): string | null {
  if (!props || props.length === 0) return null;
  const parts: string[] = [];
  for (const p of props) {
    const f = p.fields || {};
    for (const k of AREA_KEYS) {
      const v = f[k];
      if (v && v.trim()) {
        parts.push(_stripParens(v));
        break;  // 매물당 하나만
      }
    }
  }
  if (parts.length === 0) return null;
  return parts.join(" / ");
}

export function extractJpDongHo(props: JpDetailProperty[] | null | undefined): string | null {
  if (!props || props.length === 0) return null;
  const parts: string[] = [];
  for (const p of props) {
    const f = p.fields || {};
    for (const k of DONG_HO_KEYS) {
      const v = f[k];
      if (v && v.trim()) {
        parts.push(v.trim());
        break;
      }
    }
  }
  if (parts.length === 0) return null;
  return parts.join(" / ");
}

/** 정렬 가능한 단일 numeric ㎡ 값 (첫 매물 기준). */
export function extractJpAreaM2(props: JpDetailProperty[] | null | undefined): number | null {
  const text = extractJpArea(props);
  if (!text) return null;
  const m = text.match(/([\d.]+)\s*㎡/);
  if (!m) return null;
  const n = Number(m[1]);
  return Number.isFinite(n) ? n : null;
}
