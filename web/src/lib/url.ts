import type { PropertyFilters } from "./types";

const NUM_KEYS = [
  "min_appraisal", "max_appraisal", "min_sale", "max_sale",
  "min_fail", "max_fail", "min_rate", "max_rate", "page", "page_size",
] as const;

export function parseFiltersFromSearchParams(
  raw: Record<string, string | string[] | undefined>,
): PropertyFilters {
  const out: PropertyFilters = {};
  const get = (k: string) => {
    const v = raw[k];
    return Array.isArray(v) ? v[0] : v;
  };
  const str = (k: keyof PropertyFilters) => {
    const v = get(k);
    if (v) (out as Record<string, unknown>)[k] = v;
  };
  const num = (k: keyof PropertyFilters) => {
    const v = get(k);
    if (v && !isNaN(Number(v))) (out as Record<string, unknown>)[k] = Number(v);
  };
  ["q", "court", "sd", "sgg", "usage_lcl", "usage_mcl", "usage_scl",
    "sale_from", "sale_to", "sort", "addr_state"].forEach((k) =>
      str(k as keyof PropertyFilters));
  NUM_KEYS.forEach((k) => num(k));
  // 불리언
  if (get("upcoming_only") === "1" || get("upcoming_only") === "true") {
    out.upcoming_only = true;
  }
  // exclude_flags: 콤마 구분 (URL에서 단일 키 사용해 간결하게)
  const ef = get("exclude_flags");
  if (ef) {
    out.exclude_flags = ef
      .split(",")
      .map((s) => s.trim())
      .filter((s) => /^[a-z_]+$/.test(s));
  }
  // usage_nm: 콤마 구분. 한글 + 영문 + 콤마 허용 (값 자체가 "연립주택,다세대,빌라" 같은 콤마 포함이라
  // | 로 구분. 단일 URL 키 한 줄에 다중 한글 묶음.)
  const un = get("usage_nm");
  if (un) {
    out.usage_nm = un.split("|").map((s) => s.trim()).filter(Boolean);
  }
  // derived: 콤마 구분, 영문/언더스코어만 (코드 화이트리스트)
  const dv = get("derived");
  if (dv) {
    out.derived = dv.split(",").map((s) => s.trim())
      .filter((s) => /^[a-z_]+$/.test(s));
  }
  return out;
}

export function buildHref(
  base: string,
  filters: PropertyFilters,
  patch: Partial<PropertyFilters> = {},
): string {
  const merged = { ...filters, ...patch };
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(merged)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) {
      // usage_nm 값 자체가 콤마 포함("연립주택,다세대,빌라") → '|' 구분.
      // parseFiltersFromSearchParams 와 직렬화 규약 일치시킴 (불일치 시 다중선택 손상).
      if (v.length > 0) params.set(k, v.join(k === "usage_nm" ? "|" : ","));
      continue;
    }
    params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}
