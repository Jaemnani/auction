// 일본 매물 필터 — 목록/지도 페이지에서 공유.

export type JpFilters = {
  page: number;
  page_size: number;
  pref: string | null;          // 도도부현 코드
  court: string | null;          // 법원 코드
  sale_cls: string | null;       // 1=土地 2=戸建て 3=マンション 4=その他
  status: string | null;         // period_bid/special_sale/...
  case_kind: string | null;      // ケ(担保) / ヌ(強制)
  price_min: number | null;      // 売却基準価額 円
  price_max: number | null;
  q: string | null;              // 사건번호 또는 주소 키워드
  yen_10k: "1" | null;           // 1만엔 함정 필터
  has_pdf: "1" | null;           // 三点セット 보유 필터
  with_geo: "1" | null;          // 좌표 있는 매물만 (지도용)
  sort: string | null;
  dir: "asc" | "desc" | null;
};

export const DEFAULT_PAGE_SIZE = 20;

export const SALE_CLS_OPTIONS = [
  { code: "1", label: "土地" },
  { code: "2", label: "戸建て" },
  { code: "3", label: "マンション" },
  { code: "4", label: "その他" },
];

export const STATUS_OPTIONS = [
  { code: "period_bid", label: "期間入札" },
  { code: "special_sale", label: "特別売却" },
  { code: "reval_pending", label: "評価再調整" },
  { code: "re_bid", label: "再入札" },
  { code: "closed", label: "終結" },
  { code: "aborted", label: "中止" },
];

export const CASE_KIND_OPTIONS = [
  { code: "ケ", label: "ケ — 担保不動産 (任意)" },
  { code: "ヌ", label: "ヌ — 強制競売" },
];

export function parseJpFilters(
  sp: Record<string, string | string[] | undefined>,
): JpFilters {
  const get = (k: string): string | null => {
    const v = sp[k];
    if (Array.isArray(v)) return v[0] ?? null;
    return v ?? null;
  };
  const num = (k: string): number | null => {
    const v = get(k);
    if (v == null) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };
  const pageRaw = num("page");
  const dir = get("dir");
  const flag = (k: string): "1" | null => (get(k) === "1" ? "1" : null);
  return {
    page: Math.max(1, pageRaw ?? 1),
    page_size: DEFAULT_PAGE_SIZE,
    pref: get("pref"),
    court: get("court"),
    sale_cls: get("sale_cls"),
    status: get("status"),
    case_kind: get("case_kind"),
    price_min: num("price_min"),
    price_max: num("price_max"),
    q: get("q"),
    yen_10k: flag("yen_10k"),
    has_pdf: flag("has_pdf"),
    with_geo: flag("with_geo"),
    sort: get("sort"),
    dir: dir === "asc" || dir === "desc" ? dir : null,
  };
}

export function buildJpHref(
  base: string,
  filters: JpFilters,
  patch: Partial<JpFilters> = {},
): string {
  const merged = { ...filters, ...patch };
  const sp = new URLSearchParams();
  if (merged.page && merged.page !== 1) sp.set("page", String(merged.page));
  if (merged.pref) sp.set("pref", merged.pref);
  if (merged.court) sp.set("court", merged.court);
  if (merged.sale_cls) sp.set("sale_cls", merged.sale_cls);
  if (merged.status) sp.set("status", merged.status);
  if (merged.case_kind) sp.set("case_kind", merged.case_kind);
  if (merged.price_min != null) sp.set("price_min", String(merged.price_min));
  if (merged.price_max != null) sp.set("price_max", String(merged.price_max));
  if (merged.q) sp.set("q", merged.q);
  if (merged.yen_10k) sp.set("yen_10k", "1");
  if (merged.has_pdf) sp.set("has_pdf", "1");
  if (merged.with_geo) sp.set("with_geo", "1");
  if (merged.sort) sp.set("sort", merged.sort);
  if (merged.dir) sp.set("dir", merged.dir);
  const qs = sp.toString();
  return qs ? `${base}?${qs}` : base;
}
