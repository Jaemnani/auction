import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { supabase, publicStorageUrl, JP_PHOTO_BUCKET } from "@/lib/supabase";
import { cn } from "@/lib/utils";
import { extractJpArea, extractJpDongHo, type JpDetailProperty } from "@/lib/jp-detail";
import { JpSortableHeader } from "@/components/jp-sortable-header";
import { JpFilterBar } from "@/components/jp-filter-bar";
import {
  type JpFilters as SharedJpFilters, parseJpFilters, buildJpHref,
} from "@/lib/jp-filters";

export const metadata = {
  title: "日本 不動産競売 — BIT",
  description: "BIT(不動産競売物件情報サイト) 物件検索",
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
  detail_result: { properties?: JpDetailProperty[] } | null;
  jp_property_photos: { storage_path: string | null; thumb_path: string | null }[] | null;
  jp_cases: {
    case_no: string | null; case_kind: string | null;
    jp_courts: { code: string | null; name: string | null } | null;
  } | null;
};

type JpFilters = SharedJpFilters;

// 정렬 가능 필드 ↔ DB 컬럼 매핑
const SORT_COLUMNS: Record<string, string> = {
  sale_unit_id: "sale_unit_id",
  sale_cls: "sale_cls",
  price: "sale_standard_price",
  bid_period: "bid_period_start",
  status: "status",
  address: "address_text",
};

const STATUS_BADGE: Record<string, { label: string; tone: string }> = {
  period_bid: { label: "期間入札", tone: "bg-blue-100 text-blue-700 border-blue-200" },
  special_sale: { label: "特別売却", tone: "bg-amber-100 text-amber-700 border-amber-200" },
  reval_pending: { label: "評価再調整", tone: "bg-purple-100 text-purple-700 border-purple-200" },
  re_bid: { label: "再入札", tone: "bg-cyan-100 text-cyan-700 border-cyan-200" },
  closed: { label: "終結", tone: "bg-zinc-100 text-zinc-700 border-zinc-200" },
  aborted: { label: "中止", tone: "bg-rose-100 text-rose-700 border-rose-200" },
};

async function fetchJp(filters: JpFilters): Promise<{ rows: JpRow[]; count: number; courts: { code: string; name: string }[]; prefs: { code: string; name: string }[] }> {
  // 매물
  const from = (filters.page - 1) * filters.page_size;
  const to = from + filters.page_size - 1;

  let q = supabase
    .from("jp_properties")
    .select(
      "sale_unit_id, sale_cls, sale_cls_label, sale_standard_price, bid_deposit, address_text, " +
      "bid_period_start, bid_period_end, yen_10k_trap, status, search_row, " +
      "detail_result, " +
      "jp_property_photos(storage_path, thumb_path), " +
      "jp_cases!inner(case_no, case_kind, jp_courts!inner(code, name))",
      // estimated는 selective filter (pref+sale_cls 등 조합) 시 0으로 추정되는 버그.
      // 일본 데이터셋은 ~1.2k건이라 exact 비용 무시 가능.
      { count: "exact" },
    );
  if (filters.pref) q = q.eq("prefecture_code", filters.pref);
  if (filters.sale_cls) q = q.eq("sale_cls", filters.sale_cls);
  if (filters.status) q = q.eq("status", filters.status);
  if (filters.court) q = q.eq("jp_cases.jp_courts.code", filters.court);
  if (filters.case_kind) q = q.eq("jp_cases.case_kind", filters.case_kind);
  if (filters.q) {
    // 注意: 元は [(令和|平成|...)] と character-class で書かれていたが
    // [] 内 alternation は単一文字マッチ → "(" だけでも一致する偽陽性。
    // 正しいのは alternation group。
    if (/(令和|平成|\(ケ\)|\(ヌ\))/.test(filters.q)) {
      q = q.ilike("jp_cases.case_no", `%${filters.q}%`);
    } else {
      q = q.ilike("address_text", `%${filters.q}%`);
    }
  }
  if (filters.price_min != null) q = q.gte("sale_standard_price", filters.price_min);
  if (filters.price_max != null) q = q.lte("sale_standard_price", filters.price_max);
  if (filters.yen_10k === "1") q = q.eq("yen_10k_trap", true);
  if (filters.with_geo === "1") {
    q = q.not("longitude", "is", null).not("latitude", "is", null);
  }
  // has_pdf 는 detail_result.has_three_set_pdf jsonb path — postgrest JSON path 지원
  if (filters.has_pdf === "1") {
    q = q.eq("detail_result->>has_three_set_pdf", "true");
  }
  if (filters.derived && filters.derived.length > 0) {
    q = q.overlaps("derived_category", filters.derived);
  }

  // 정렬 — sort/dir이 있으면 그것 사용. 없으면 입찰기간 빠른 순.
  const sortCol = filters.sort ? SORT_COLUMNS[filters.sort] : null;
  if (sortCol && !sortCol.includes("(")) {
    q = q.order(sortCol, {
      ascending: filters.dir !== "desc",
      nullsFirst: false,
    });
  } else {
    q = q.order("bid_period_start", { ascending: true, nullsFirst: false });
  }
  q = q.range(from, to);

  const { data, error, count } = await q;
  if (error) {
    console.error("jp_properties fetch failed:", error.message);
    return { rows: [], count: 0, courts: [], prefs: [] };
  }

  const [courtsRes, prefsRes] = await Promise.all([
    supabase.from("jp_courts").select("code, name").order("code"),
    supabase.from("jp_prefectures").select("code, name").order("code"),
  ]);

  return {
    rows: (data || []) as unknown as JpRow[],
    count: count ?? 0,
    courts: (courtsRes.data || []) as { code: string; name: string }[],
    prefs: (prefsRes.data || []) as { code: string; name: string }[],
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
  { phase: "1", label: "BIT 偵察 + 物件フロー", done: true },
  { phase: "2", label: "スキーマ(jp_*) + マイグレーション", done: true },
  { phase: "3", label: "クライアント + 検索パーサ", done: true },
  { phase: "4", label: "詳細パーサ + backfill (3種価格·売却期日·物件明細)", done: true },
  { phase: "5", label: "/jp リスト + 詳細ページ", done: true },
  { phase: "6", label: "写真セルフホスト (jp-auction-photos)", done: true },
  { phase: "7", label: "全国47都道府県 取込", done: true },
  { phase: "8", label: "三点セット PDF · 座標 · マップ", done: true },
];

// has_three_set_pdf 통계 (전체·보유) — 필터 토글 옆 비율 표시용.
// head:true 로 row 없이 count 만 가져옴 — ISR 캐시(revalidate=300)에 합산.
async function fetchPdfStats(): Promise<{ total: number; withPdf: number }> {
  const [t, w] = await Promise.all([
    supabase.from("jp_properties").select("sale_unit_id", { count: "exact", head: true }),
    supabase.from("jp_properties").select("sale_unit_id", { count: "exact", head: true })
      .eq("detail_result->>has_three_set_pdf", "true"),
  ]);
  return { total: t.count ?? 0, withPdf: w.count ?? 0 };
}

export default async function JpListingPage(props: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await props.searchParams;
  const filters = parseJpFilters(sp);
  const [{ rows, count, courts, prefs }, pdfStats] = await Promise.all([
    fetchJp(filters),
    fetchPdfStats(),
  ]);
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
          <Badge variant="secondary" className="text-xs">全国取込済 · {count}件</Badge>
          <Badge variant="outline" className="text-xs">詳細パーサ検証済</Badge>
        </div>
        <h1 className="text-2xl font-bold tracking-tight">🇯🇵 日本 不動産競売</h1>
        <p className="text-sm text-muted-foreground">
          BIT(<a href="https://www.bit.courts.go.jp" target="_blank" rel="noopener noreferrer"
                 className="text-primary hover:underline">不動産競売物件情報サイト</a>)
          の物件。事件番号をクリックすると詳細ページへ。
        </p>
        <div className="flex flex-wrap gap-2 pt-2">
          <Link href="/jp/map" className="text-sm rounded-md border bg-card hover:bg-muted px-3 py-1.5">
            🗺️ 地図で見る
          </Link>
          <Link href="/jp/about" className="text-sm rounded-md border bg-card hover:bg-muted px-3 py-1.5">
            🇰🇷 vs 🇯🇵 比較 / ロードマップ
          </Link>
        </div>
      </section>

      {/* 필터 — 목록·지도 공통 컴포넌트 */}
      <JpFilterBar action="/jp" filters={filters} prefs={prefs} courts={courts} pdfStats={pdfStats} />

      {/* リスト */}
      <Card>
        <CardHeader className="flex flex-row items-baseline justify-between">
          <CardTitle className="text-base">📋 物件一覧</CardTitle>
          <span className="text-xs text-muted-foreground">
            全 {count}件 · {filters.page} / {totalPages} ページ
          </span>
        </CardHeader>
        <CardContent className="p-0">
          {rows.length === 0 ? (
            <div className="p-6 text-sm text-muted-foreground text-center">
              条件に一致する物件はありません。{" "}
              <Link href="/jp" className="text-primary hover:underline">フィルタをリセット</Link>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[80px]">写真</TableHead>
                  <TableHead className="w-[200px]">
                    <JpSortableHeader field="sale_unit_id" label="事件番号 · 裁判所" />
                  </TableHead>
                  <TableHead className="w-[80px]">
                    <JpSortableHeader field="sale_cls" label="種別" />
                  </TableHead>
                  <TableHead className="w-[140px] text-right">
                    <JpSortableHeader field="price" label="売却基準" align="right" />
                  </TableHead>
                  <TableHead className="w-[120px]">面積</TableHead>
                  <TableHead className="w-[100px]">号室/棟</TableHead>
                  <TableHead className="w-[180px]">
                    <JpSortableHeader field="bid_period" label="入札期間" />
                  </TableHead>
                  <TableHead className="w-[100px]">
                    <JpSortableHeader field="status" label="状態" />
                  </TableHead>
                  <TableHead>
                    <JpSortableHeader field="address" label="所在地" />
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => {
                  const courtName = (r.jp_cases?.jp_courts?.name ?? "").replace("地方裁判所", "地裁");
                  const caseNo = r.jp_cases?.case_no ?? r.sale_unit_id;
                  const status = r.status ? STATUS_BADGE[r.status] : null;
                  const thumb = thumbUrl(r);
                  const area = extractJpArea(r.detail_result?.properties);
                  const dongHo = extractJpDongHo(r.detail_result?.properties);
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
                      <TableCell className="text-xs font-mono">{area ?? "—"}</TableCell>
                      <TableCell className="text-xs">{dongHo ?? "—"}</TableCell>
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
            全 <strong>{count.toLocaleString()}</strong>件 · {filters.page} / {totalPages} ページ
          </div>
          <div className="flex items-center gap-1">
            <Link href={buildJpHref("/jp", filters, { page: 1 })}
                  className={linkCls(false, filters.page <= 1)}
                  aria-label="最初のページ">«</Link>
            <Link href={buildJpHref("/jp", filters, { page: filters.page - 1 })}
                  className={linkCls(false, filters.page <= 1)}
                  aria-label="前のページ">‹</Link>
            {Array.from(
              { length: Math.min(5, totalPages) },
              (_, i) => Math.max(1, Math.min(totalPages - 4, filters.page - 2)) + i,
            ).filter((p) => p >= 1 && p <= totalPages).map((p) => (
              <Link key={p} href={buildJpHref("/jp", filters, { page: p })}
                    className={linkCls(p === filters.page)}
                    aria-label={`${p}ページ`}
                    aria-current={p === filters.page ? "page" : undefined}>{p}</Link>
            ))}
            <Link href={buildJpHref("/jp", filters, { page: filters.page + 1 })}
                  className={linkCls(false, filters.page >= totalPages)}
                  aria-label="次のページ">›</Link>
            <Link href={buildJpHref("/jp", filters, { page: totalPages })}
                  className={linkCls(false, filters.page >= totalPages)}
                  aria-label="最後のページ">»</Link>
          </div>
        </div>
      )}

      {/* 진행 상황 (하단) */}
      <Card className="bg-muted/20">
        <CardHeader>
          <CardTitle className="text-base">📍 サイト構築 進行状況</CardTitle>
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
            データ: <code className="text-foreground bg-muted px-1 rounded">jp_properties / jp_cases / jp_courts</code> ·
            取込: <code className="text-foreground bg-muted px-1 rounded">jp_ingest.py</code> ·
            日韓比較: <Link href="/jp/about" className="text-primary hover:underline">/jp/about</Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
