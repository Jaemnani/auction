import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { supabase, publicStorageUrl, JP_PHOTO_BUCKET } from "@/lib/supabase";
import { cn } from "@/lib/utils";

export const metadata = {
  title: "일본 부동산 경매 — BIT",
  description: "BIT(不動産競売物件情報サイト) 매물 검색 (도쿄 73건 적재)",
};

export const revalidate = 300;

type JpRow = {
  sale_unit_id: string;
  sale_cls: string | null;
  sale_cls_label: string | null;
  sale_standard_price: number | null;
  bid_deposit: number | null;
  address_text: string | null;
  bid_period_start: string | null;
  bid_period_end: string | null;
  yen_10k_trap: boolean | null;
  status: string | null;
  search_row: { photo_url?: string } | null;
  jp_property_photos: { storage_path: string | null; thumb_path: string | null }[] | null;
  jp_cases: {
    case_no: string | null; case_kind: string | null;
    jp_courts: { code: string | null; name: string | null } | null;
  } | null;
};

type JpFilters = {
  page: number;
  page_size: number;
  sale_cls: string | null;
  status: string | null;
  court: string | null;
  q: string | null;
  price_max: number | null;
};

const DEFAULT_PAGE_SIZE = 20;

const SALE_CLS_OPTIONS = [
  { code: "1", label: "土地" },
  { code: "2", label: "戸建て" },
  { code: "3", label: "マンション" },
  { code: "4", label: "その他" },
];

const STATUS_OPTIONS = [
  { code: "period_bid", label: "期間入札" },
  { code: "special_sale", label: "特別売却" },
  { code: "reval_pending", label: "評価再調整" },
  { code: "re_bid", label: "再入札" },
  { code: "closed", label: "終結" },
  { code: "aborted", label: "中止" },
];

const STATUS_BADGE: Record<string, { label: string; tone: string }> = Object.fromEntries(
  STATUS_OPTIONS.map((s) => [s.code, {
    label: s.label,
    tone: ({
      period_bid: "bg-blue-100 text-blue-700 border-blue-200",
      special_sale: "bg-amber-100 text-amber-700 border-amber-200",
      reval_pending: "bg-purple-100 text-purple-700 border-purple-200",
      re_bid: "bg-cyan-100 text-cyan-700 border-cyan-200",
      closed: "bg-zinc-100 text-zinc-700 border-zinc-200",
      aborted: "bg-rose-100 text-rose-700 border-rose-200",
    } as Record<string, string>)[s.code] ?? "bg-muted text-muted-foreground border-border",
  }])
);

function parseFilters(sp: Record<string, string | string[] | undefined>): JpFilters {
  const get = (k: string): string | null => {
    const v = sp[k];
    if (Array.isArray(v)) return v[0] ?? null;
    return v ?? null;
  };
  const num = (k: string, dflt: number | null = null): number | null => {
    const v = get(k);
    if (v == null) return dflt;
    const n = Number(v);
    return Number.isFinite(n) ? n : dflt;
  };
  return {
    page: Math.max(1, num("page", 1) ?? 1),
    page_size: DEFAULT_PAGE_SIZE,
    sale_cls: get("sale_cls"),
    status: get("status"),
    court: get("court"),
    q: get("q"),
    price_max: num("price_max"),
  };
}

function buildHref(filters: JpFilters, override: Partial<JpFilters>): string {
  const merged = { ...filters, ...override };
  const sp = new URLSearchParams();
  if (merged.page && merged.page !== 1) sp.set("page", String(merged.page));
  if (merged.sale_cls) sp.set("sale_cls", merged.sale_cls);
  if (merged.status) sp.set("status", merged.status);
  if (merged.court) sp.set("court", merged.court);
  if (merged.q) sp.set("q", merged.q);
  if (merged.price_max != null) sp.set("price_max", String(merged.price_max));
  const qs = sp.toString();
  return qs ? `/jp?${qs}` : "/jp";
}

async function fetchJp(filters: JpFilters): Promise<{ rows: JpRow[]; count: number; courts: { code: string; name: string }[] }> {
  // 매물
  const from = (filters.page - 1) * filters.page_size;
  const to = from + filters.page_size - 1;

  let q = supabase
    .from("jp_properties")
    .select(
      "sale_unit_id, sale_cls, sale_cls_label, sale_standard_price, bid_deposit, address_text, " +
      "bid_period_start, bid_period_end, yen_10k_trap, status, search_row, " +
      "jp_property_photos(storage_path, thumb_path), " +
      "jp_cases!inner(case_no, case_kind, jp_courts!inner(code, name))",
      { count: "estimated" },
    );
  if (filters.sale_cls) q = q.eq("sale_cls", filters.sale_cls);
  if (filters.status) q = q.eq("status", filters.status);
  if (filters.court) q = q.eq("jp_cases.jp_courts.code", filters.court);
  if (filters.q) {
    // 주소 또는 사건번호 키워드
    if (/[(令和|平成|\(ケ\)|\(ヌ\))]/.test(filters.q)) {
      q = q.ilike("jp_cases.case_no", `%${filters.q}%`);
    } else {
      q = q.ilike("address_text", `%${filters.q}%`);
    }
  }
  if (filters.price_max != null) {
    q = q.lte("sale_standard_price", filters.price_max);
  }

  q = q
    .order("bid_period_start", { ascending: true, nullsFirst: false })
    .range(from, to);

  const { data, error, count } = await q;
  if (error) {
    console.error("jp_properties fetch failed:", error.message);
    return { rows: [], count: 0, courts: [] };
  }

  // 법원 마스터 (필터 셀렉트용)
  const courtsRes = await supabase
    .from("jp_courts")
    .select("code, name")
    .order("code");

  return {
    rows: (data || []) as unknown as JpRow[],
    count: count ?? 0,
    courts: (courtsRes.data || []) as { code: string; name: string }[],
  };
}

function fmtJpy(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString("ja-JP") + "円";
}

function bitImageUrl(p: string | undefined | null): string | null {
  if (!p) return null;
  if (p.startsWith("http")) return p;
  return `https://www.bit.courts.go.jp${p}`;
}

function thumbUrl(row: JpRow): string | null {
  // 자체 호스팅 썸네일 우선, 없으면 BIT 직접
  const ph = row.jp_property_photos?.[0];
  if (ph?.thumb_path) return publicStorageUrl(JP_PHOTO_BUCKET, ph.thumb_path);
  if (ph?.storage_path) return publicStorageUrl(JP_PHOTO_BUCKET, ph.storage_path);
  return bitImageUrl(row.search_row?.photo_url);
}

const ROADMAP = [
  { phase: "1", label: "BIT 정찰 + 매물 흐름", done: true },
  { phase: "2", label: "스키마(jp_*) + 마이그레이션", done: true },
  { phase: "3", label: "클라이언트 + 검색 파서 (도쿄 73건)", done: true },
  { phase: "4", label: "상세 파서 + backfill (3종 가격·매각기일·物件 fields)", done: true },
  { phase: "5", label: "/jp 리스트 + 상세 페이지", done: true },
  { phase: "6", label: "사진 자체 호스팅 (jp-auction-photos 버킷)", done: false },
  { phase: "7", label: "전국 47도도부현 풀 적재", done: false },
  { phase: "8", label: "三点セット PDF · 좌표 · 지도", done: false },
];

export default async function JpListingPage(props: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await props.searchParams;
  const filters = parseFilters(sp);
  const { rows, count, courts } = await fetchJp(filters);
  const totalPages = Math.max(1, Math.ceil(count / filters.page_size));

  const linkCls = (active: boolean, disabled?: boolean) =>
    cn(
      buttonVariants({ variant: active ? "default" : "outline", size: "sm" }),
      "h-8 min-w-8",
      disabled && "pointer-events-none opacity-50",
    );

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      <section className="rounded-lg border bg-card p-6 space-y-2">
        <div className="flex flex-wrap gap-2">
          <Badge variant="secondary" className="text-xs">도쿄 적재 완료 · {count}건</Badge>
          <Badge variant="outline" className="text-xs">상세 파서 검증</Badge>
          <Badge variant="outline" className="text-xs">전국 풀 적재 / 사진 자체 호스팅 진행중</Badge>
        </div>
        <h1 className="text-2xl font-bold tracking-tight">🇯🇵 일본 부동산 경매</h1>
        <p className="text-sm text-muted-foreground">
          BIT(<a href="https://www.bit.courts.go.jp" target="_blank" rel="noopener noreferrer"
                 className="text-primary hover:underline">不動産競売物件情報サイト</a>) 매물.
          한국 페이지와 동일 패턴으로 구축. 사건번호 클릭 시 상세 페이지로 이동.
        </p>
        <div className="flex flex-wrap gap-2 pt-2">
          <Link href="/jp/map" className="text-sm rounded-md border bg-card hover:bg-muted px-3 py-1.5">
            🗺️ 지도로 보기
          </Link>
          <Link href="/jp/about" className="text-sm rounded-md border bg-card hover:bg-muted px-3 py-1.5">
            🇰🇷 vs 🇯🇵 비교 / 로드맵
          </Link>
        </div>
      </section>

      {/* 필터 */}
      <Card>
        <CardContent className="p-4">
          <form method="get" action="/jp" className="grid sm:grid-cols-12 gap-2">
            <select name="court" defaultValue={filters.court ?? ""}
                    className="sm:col-span-3 h-9 rounded-md border bg-background px-2 text-sm">
              <option value="">법원 — 전체</option>
              {courts.map((c) => (
                <option key={c.code} value={c.code}>{c.name}</option>
              ))}
            </select>
            <select name="sale_cls" defaultValue={filters.sale_cls ?? ""}
                    className="sm:col-span-2 h-9 rounded-md border bg-background px-2 text-sm">
              <option value="">종별 — 전체</option>
              {SALE_CLS_OPTIONS.map((o) => (
                <option key={o.code} value={o.code}>{o.label}</option>
              ))}
            </select>
            <select name="status" defaultValue={filters.status ?? ""}
                    className="sm:col-span-2 h-9 rounded-md border bg-background px-2 text-sm">
              <option value="">상태 — 전체</option>
              {STATUS_OPTIONS.map((o) => (
                <option key={o.code} value={o.code}>{o.label}</option>
              ))}
            </select>
            <input name="price_max" type="number" placeholder="가격 상한 (円)"
                   defaultValue={filters.price_max ?? ""}
                   className="sm:col-span-2 h-9 rounded-md border bg-background px-2 text-sm" />
            <input name="q" placeholder="주소 / 사건번호"
                   defaultValue={filters.q ?? ""}
                   className="sm:col-span-2 h-9 rounded-md border bg-background px-2 text-sm" />
            <button type="submit"
                    className={cn(buttonVariants({ size: "sm" }), "sm:col-span-1 h-9")}>
              검색
            </button>
          </form>
        </CardContent>
      </Card>

      {/* 리스트 */}
      <Card>
        <CardHeader className="flex flex-row items-baseline justify-between">
          <CardTitle className="text-base">📋 매물 목록</CardTitle>
          <span className="text-xs text-muted-foreground">
            총 {count}건 · {filters.page} / {totalPages} 페이지
          </span>
        </CardHeader>
        <CardContent className="p-0">
          {rows.length === 0 ? (
            <div className="p-6 text-sm text-muted-foreground text-center">
              조건에 맞는 매물이 없습니다.{" "}
              <Link href="/jp" className="text-primary hover:underline">필터 초기화</Link>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[80px]">사진</TableHead>
                  <TableHead className="w-[200px]">사건번호 · 법원</TableHead>
                  <TableHead className="w-[80px]">종별</TableHead>
                  <TableHead className="w-[140px] text-right">売却基準</TableHead>
                  <TableHead className="w-[180px]">入札期間</TableHead>
                  <TableHead className="w-[100px]">상태</TableHead>
                  <TableHead>所在地</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => {
                  const courtName = (r.jp_cases?.jp_courts?.name ?? "").replace("地方裁判所", "地裁");
                  const caseNo = r.jp_cases?.case_no ?? r.sale_unit_id;
                  const status = r.status ? STATUS_BADGE[r.status] : null;
                  const thumb = thumbUrl(r);
                  return (
                    <TableRow key={r.sale_unit_id} className="hover:bg-muted/40">
                      <TableCell className="w-[80px]">
                        <Link href={`/jp/p/${r.sale_unit_id}`}>
                          {thumb ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img src={thumb} alt="" className="w-16 h-12 object-cover rounded border" />
                          ) : (
                            <div className="w-16 h-12 bg-muted rounded border" />
                          )}
                        </Link>
                      </TableCell>
                      <TableCell className="text-xs">
                        <Link href={`/jp/p/${r.sale_unit_id}`} className="text-primary hover:underline font-mono block">
                          {caseNo}
                        </Link>
                        <span className="text-muted-foreground">{courtName}</span>
                        {r.yen_10k_trap && (
                          <Badge variant="destructive" className="ml-1 text-[10px] px-1 py-0">⚠1万</Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-xs">{r.sale_cls_label ?? "—"}</Badge>
                      </TableCell>
                      <TableCell className="text-xs text-right font-mono">
                        {fmtJpy(r.sale_standard_price)}
                      </TableCell>
                      <TableCell className="text-xs font-mono">
                        {r.bid_period_start && r.bid_period_end
                          ? <>{r.bid_period_start}<br/>~ {r.bid_period_end}</>
                          : "—"}
                      </TableCell>
                      <TableCell>
                        {status ? (
                          <span className={`inline-block rounded border px-2 py-0.5 text-[10px] ${status.tone}`}>
                            {status.label}
                          </span>
                        ) : "—"}
                      </TableCell>
                      <TableCell className="text-xs">{r.address_text ?? "—"}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* 페이지네이션 */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <div className="text-xs text-muted-foreground">
            총 <strong>{count.toLocaleString()}</strong>건 · {filters.page} / {totalPages} 페이지
          </div>
          <div className="flex items-center gap-1">
            <Link href={buildHref(filters, { page: 1 })}
                  className={linkCls(false, filters.page <= 1)}>«</Link>
            <Link href={buildHref(filters, { page: filters.page - 1 })}
                  className={linkCls(false, filters.page <= 1)}>‹</Link>
            {Array.from(
              { length: Math.min(5, totalPages) },
              (_, i) => Math.max(1, Math.min(totalPages - 4, filters.page - 2)) + i,
            ).filter((p) => p >= 1 && p <= totalPages).map((p) => (
              <Link key={p} href={buildHref(filters, { page: p })}
                    className={linkCls(p === filters.page)}>{p}</Link>
            ))}
            <Link href={buildHref(filters, { page: filters.page + 1 })}
                  className={linkCls(false, filters.page >= totalPages)}>›</Link>
            <Link href={buildHref(filters, { page: totalPages })}
                  className={linkCls(false, filters.page >= totalPages)}>»</Link>
          </div>
        </div>
      )}

      {/* 진행 상황 (하단) */}
      <Card className="bg-muted/20">
        <CardHeader>
          <CardTitle className="text-base">📍 일본 사이트 구축 진행 상황</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-sm">
          {ROADMAP.map((r) => (
            <div key={r.phase} className="flex items-start gap-2">
              <span className={r.done ? "text-emerald-600" : "text-muted-foreground"}>
                {r.done ? "✅" : "☐"}
              </span>
              <span className={r.done ? "text-foreground" : "text-muted-foreground"}>
                {r.label}
              </span>
            </div>
          ))}
          <p className="text-xs text-muted-foreground pt-2 border-t">
            데이터: <code className="text-foreground bg-muted px-1 rounded">jp_properties / jp_cases / jp_courts</code> ·
            적재: <code className="text-foreground bg-muted px-1 rounded">jp_ingest.py</code> ·
            한·일 차이: <Link href="/jp/about" className="text-primary hover:underline">/jp/about</Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
