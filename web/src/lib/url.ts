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
      if (v.length > 0) params.set(k, v.join(","));
      continue;
    }
    params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}
