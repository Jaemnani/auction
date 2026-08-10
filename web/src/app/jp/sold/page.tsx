import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { supabase } from "@/lib/supabase";
import { cn } from "@/lib/utils";

export const metadata = {
  title: "落札結果 — 日本 不動産競売",
  description: "BIT 開札結果（売却価額・入札者数）",
};

export const revalidate = 300;

const PAGE_SIZE = 30;

type JpResultRow = {
  id: string;
  court_code: string;
  case_no: string;
  property_no: string | null;
  open_bid_date: string | null;
  sale_cls_label: string | null;
  sale_price: number | null;
  sale_standard_price: number | null;
  address_text: string | null;
  result_cls: string | null;
  bidder_count: number | null;
  winner_kind: string | null;
};

/** 開札結果 배지 색 — 売却만 강조, 不売·取下는 중립. */
const RESULT_TONE: Record<string, string> = {
  売却: "bg-blue-100 text-blue-700 border-blue-200",
  不売: "bg-zinc-100 text-zinc-600 border-zinc-200",
  取下: "bg-amber-100 text-amber-700 border-amber-200",
};

function fmtJpy(v: number | null): string {
  if (v == null) return "—";
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}億円`;
  if (v >= 1e4) return `${Math.round(v / 1e4).toLocaleString("ja-JP")}万円`;
  return `${v.toLocaleString("ja-JP")}円`;
}

/**
 * 落札結果 목록.
 *
 * jp_sale_results 는 0027 마이그레이션 — 미적용 환경에서도 페이지가 죽지 않도록
 * 조회 실패를 빈 결과로 흡수한다(다른 attach* 헬퍼와 같은 방침).
 */
async function fetchResults(page: number, soldOnly: boolean): Promise<{
  rows: JpResultRow[]; total: number; courts: Record<string, string>; missing: boolean;
}> {
  const from = (page - 1) * PAGE_SIZE;
  let q = supabase
    .from("jp_sale_results")
    .select(
      "id, court_code, case_no, property_no, open_bid_date, sale_cls_label, " +
      "sale_price, sale_standard_price, address_text, result_cls, bidder_count, winner_kind",
      { count: "exact" },
    )
    .order("open_bid_date", { ascending: false, nullsFirst: false })
    .order("case_no", { ascending: true })
    .range(from, from + PAGE_SIZE - 1);
  if (soldOnly) q = q.not("sale_price", "is", null);

  const { data, error, count } = await q;
  if (error) {
    console.error("jp_sale_results fetch failed:", error.message);
    return { rows: [], total: 0, courts: {}, missing: true };
  }
  const rows = (data || []) as unknown as JpResultRow[];

  const courts: Record<string, string> = {};
  const codes = [...new Set(rows.map((r) => r.court_code))];
  if (codes.length > 0) {
    const { data: cs } = await supabase
      .from("jp_courts").select("code, name").in("code", codes);
    for (const c of (cs || []) as { code: string; name: string }[]) {
      courts[c.code] = c.name;
    }
  }
  return { rows, total: count ?? 0, courts, missing: false };
}

export default async function JpSoldPage(props: PageProps<"/jp/sold">) {
  const sp = await props.searchParams;
  const page = Math.max(1, Number(Array.isArray(sp.page) ? sp.page[0] : sp.page) || 1);
  const soldOnly = (Array.isArray(sp.sold) ? sp.sold[0] : sp.sold) === "1";
  const { rows, total, courts, missing } = await fetchResults(page, soldOnly);
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const href = (p: number, s = soldOnly) =>
    `/jp/sold?page=${p}${s ? "&sold=1" : ""}`;

  return (
    <div className="space-y-4 min-w-0">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">🔨 落札結果</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p className="text-muted-foreground">
            BIT の開札結果です。売却価額（落札価格）・入札者数・落札者資格を確認できます。
          </p>
          <p className="text-caption-sm text-muted-foreground">
            ※ BIT は裁判所ごとに直近の開札期日のみ公開するため、過去分の遡及取得はできません。
          </p>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Link href={href(1, false)}
                  className={cn(buttonVariants({
                    variant: soldOnly ? "outline" : "default", size: "sm",
                  }))}>
              すべて
            </Link>
            <Link href={href(1, true)}
                  className={cn(buttonVariants({
                    variant: soldOnly ? "default" : "outline", size: "sm",
                  }))}>
              売却のみ
            </Link>
          </div>
        </CardContent>
      </Card>

      {missing ? (
        <div className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
          落札結果データはまだ取り込まれていません。
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
          該当する開札結果がありません。
        </div>
      ) : (
        <Card>
          <CardHeader className="flex flex-row items-baseline justify-between">
            <CardTitle className="text-base">開札結果一覧</CardTitle>
            <span className="text-xs text-muted-foreground">
              全 {total.toLocaleString()}件 · {page} / {totalPages} ページ
            </span>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y">
              {rows.map((r) => {
                const tone = (r.result_cls && RESULT_TONE[r.result_cls])
                  || "bg-zinc-100 text-zinc-600 border-zinc-200";
                // 낙찰가/기준가 비율 — 기준가가 0이면 나눗셈 무의미
                const rate = r.sale_price != null && r.sale_standard_price
                  ? Math.round((r.sale_price / r.sale_standard_price) * 100)
                  : null;
                return (
                  <li key={r.id} className="p-3 hover:bg-muted/30 transition">
                    <div className="flex items-start gap-3 min-w-0">
                      <div className="flex-1 min-w-0 space-y-1">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                          <span className="font-mono text-xs">{r.case_no}</span>
                          <span className={`inline-block rounded border px-1.5 py-0 text-caption-xs ${tone}`}>
                            {r.result_cls ?? "—"}
                          </span>
                          {r.sale_cls_label && (
                            <Badge variant="outline" className="text-caption-xs">
                              {r.sale_cls_label}
                            </Badge>
                          )}
                        </div>
                        <div className="text-caption-sm text-muted-foreground">
                          {courts[r.court_code] ?? r.court_code}
                          {r.open_bid_date ? ` · 開札 ${r.open_bid_date}` : ""}
                          {r.property_no ? ` · 物件 ${r.property_no}` : ""}
                        </div>
                        {r.address_text && (
                          <div className="text-xs line-clamp-2">{r.address_text}</div>
                        )}
                        {(r.bidder_count != null || r.winner_kind) && (
                          <div className="text-caption-sm text-muted-foreground">
                            {r.bidder_count != null ? `入札 ${r.bidder_count}人` : ""}
                            {r.bidder_count != null && r.winner_kind ? " · " : ""}
                            {r.winner_kind ?? ""}
                          </div>
                        )}
                      </div>

                      <div className="shrink-0 text-right space-y-0.5 min-w-[96px]">
                        <div className="text-caption-xs text-muted-foreground">売却基準</div>
                        <div className="text-xs">{fmtJpy(r.sale_standard_price)}</div>
                        {r.sale_price != null && (
                          <>
                            <div className="text-caption-xs text-blue-600 pt-1">売却価額</div>
                            <div className="text-sm font-bold text-blue-600">
                              {fmtJpy(r.sale_price)}
                            </div>
                            {rate != null && (
                              <div className="text-caption-xs text-muted-foreground">
                                基準の {rate}%
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
      )}

      {totalPages > 1 && (
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <div className="text-xs text-muted-foreground">
            全 <strong>{total.toLocaleString()}</strong>件 · {page} / {totalPages} ページ
          </div>
          <div className="flex flex-wrap items-center justify-center sm:justify-end gap-1">
            <Link href={href(Math.max(1, page - 1))}
                  className={cn(buttonVariants({ variant: "outline", size: "sm" }),
                    page <= 1 && "pointer-events-none opacity-50")}>‹</Link>
            <Link href={href(Math.min(totalPages, page + 1))}
                  className={cn(buttonVariants({ variant: "outline", size: "sm" }),
                    page >= totalPages && "pointer-events-none opacity-50")}>›</Link>
          </div>
        </div>
      )}
    </div>
  );
}
