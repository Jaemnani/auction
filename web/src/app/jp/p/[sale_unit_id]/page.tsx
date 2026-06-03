import Link from "next/link";
import { notFound } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { supabase, publicStorageUrl, JP_PHOTO_BUCKET } from "@/lib/supabase";
import { ExportButtons } from "@/components/export-buttons";
import { buildJpMarkdown } from "@/lib/jp-markdown";

export const revalidate = 300;

type DetailResult = {
  title?: string | null;
  case_no_text?: string | null;
  court_name_text?: string | null;
  prices?: {
    sale_standard_price?: number | null;
    bid_deposit?: number | null;
    purchase_possible_price?: number | null;
  } | null;
  dates?: {
    koji_start?: string | null;
    view_start?: string | null;
    open_bid_date?: string | null;
    sale_decision_date?: string | null;
    bid_period?: { start?: string | null; end?: string | null } | null;
    special_sale_period?: { start?: string | null; end?: string | null } | null;
  } | null;
  properties?: Array<{ head?: string | null; fields?: Record<string, string> | null }> | null;
  photos?: string[] | null;
  latitude?: number | null;
  longitude?: number | null;
  has_three_set_pdf?: boolean;
};

type JpRow = {
  sale_unit_id: string;
  sale_cls_label: string | null;
  status: string | null;
  yen_10k_trap: boolean | null;
  address_text: string | null;
  transit_info: string | null;
  bid_period_start: string | null;
  bid_period_end: string | null;
  open_bid_date: string | null;
  sale_standard_price: number | null;
  bid_deposit: number | null;
  purchase_possible_price: number | null;
  latitude: number | null;
  longitude: number | null;
  search_row: { photo_url?: string } | null;
  jp_property_photos: { seq: number | null; storage_path: string | null; thumb_path: string | null }[] | null;
  detail_result: DetailResult | null;
  jp_cases: { case_no: string | null; case_kind: string | null; case_era: string | null; case_year: number | null; jp_courts: { code: string | null; name: string | null } | null } | null;
};

const STATUS_LABEL: Record<string, { label: string; tone: string }> = {
  period_bid: { label: "期間入札", tone: "bg-blue-100 text-blue-700 border-blue-200" },
  special_sale: { label: "特別売却", tone: "bg-amber-100 text-amber-700 border-amber-200" },
  reval_pending: { label: "評価再調整", tone: "bg-purple-100 text-purple-700 border-purple-200" },
  re_bid: { label: "再入札", tone: "bg-cyan-100 text-cyan-700 border-cyan-200" },
  closed: { label: "終結", tone: "bg-zinc-100 text-zinc-700 border-zinc-200" },
  aborted: { label: "中止", tone: "bg-rose-100 text-rose-700 border-rose-200" },
};

function fmtJpy(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString("ja-JP") + "円";
}

function fmtRange(r: { start?: string | null; end?: string | null } | null | undefined): string {
  if (!r) return "—";
  const s = r.start ?? "?", e = r.end ?? "?";
  if (s === "?" && e === "?") return "—";
  return `${s} ~ ${e}`;
}

function bitImageUrl(path: string | undefined | null): string | null {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  return `https://www.bit.courts.go.jp${path}`;
}

export default async function JpDetailPage({
  params,
}: {
  params: Promise<{ sale_unit_id: string }>;
}) {
  const { sale_unit_id } = await params;

  const { data, error } = await supabase
    .from("jp_properties")
    .select(
      "sale_unit_id, sale_cls_label, status, yen_10k_trap, address_text, transit_info, " +
      "bid_period_start, bid_period_end, open_bid_date, sale_standard_price, bid_deposit, " +
      "purchase_possible_price, latitude, longitude, " +
      "search_row, detail_result, " +
      "jp_property_photos(seq, storage_path, thumb_path), " +
      "jp_cases!inner(case_no, case_kind, case_era, case_year, jp_courts!inner(code, name))"
    )
    .eq("sale_unit_id", sale_unit_id)
    .maybeSingle();

  if (error) {
    console.error("jp detail fetch error:", error.message);
    return notFound();
  }
  if (!data) return notFound();

  const row = data as unknown as JpRow;
  const detail: DetailResult = row.detail_result ?? {};
  const prices = detail.prices ?? {};
  const dates = detail.dates ?? {};
  const properties = detail.properties ?? [];

  // 사진 — 자체 호스팅 우선, 없으면 BIT 직접
  const ownPhotos = (row.jp_property_photos || [])
    .slice()
    .sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))
    .map((p) => p.storage_path ? publicStorageUrl(JP_PHOTO_BUCKET, p.storage_path) : null)
    .filter((u): u is string => Boolean(u));
  const fallbackPhotos = (detail.photos && detail.photos.length > 0)
    ? detail.photos.map(bitImageUrl).filter((u): u is string => Boolean(u))
    : (row.search_row?.photo_url ? [bitImageUrl(row.search_row.photo_url)].filter((u): u is string => Boolean(u)) : []);
  const photoUrls: string[] = ownPhotos.length > 0 ? ownPhotos : fallbackPhotos;

  const status = row.status ? STATUS_LABEL[row.status] : null;
  const courtName = row.jp_cases?.jp_courts?.name ?? "—";
  const caseNo = row.jp_cases?.case_no ?? sale_unit_id;
  const addr = row.address_text;

  // 좌표 우선 외부 지도 링크. 좌표 없으면 주소 검색.
  const lat = row.latitude ?? detail.latitude ?? null;
  const lng = row.longitude ?? detail.longitude ?? null;
  const hasGeo = lat != null && lng != null;
  const googleMap = hasGeo
    ? `https://www.google.com/maps?q=${lat},${lng}&z=18`
    : (addr ? `https://www.google.com/maps/search/${encodeURIComponent(addr)}` : null);
  const naverMap = hasGeo
    ? `https://map.naver.com/v5/?c=${lng},${lat},18,0,0,0,dh`
    : (addr ? `https://map.naver.com/v5/search/${encodeURIComponent(addr)}` : null);
  // OpenStreetMap 인라인 미리보기 (key 불필요)
  const osmEmbed = hasGeo
    ? `https://www.openstreetmap.org/export/embed.html?bbox=${(lng ?? 0) - 0.005},${(lat ?? 0) - 0.003},${(lng ?? 0) + 0.005},${(lat ?? 0) + 0.003}&layer=mapnik&marker=${lat},${lng}`
    : null;

  // Markdown export
  const markdown = buildJpMarkdown({
    sale_unit_id: row.sale_unit_id,
    sale_cls_label: row.sale_cls_label,
    status: row.status,
    yen_10k_trap: row.yen_10k_trap,
    address_text: row.address_text,
    transit_info: row.transit_info,
    sale_standard_price: row.sale_standard_price,
    bid_deposit: row.bid_deposit,
    purchase_possible_price: row.purchase_possible_price,
    latitude: lat,
    longitude: lng,
    case_no: row.jp_cases?.case_no ?? null,
    case_kind: row.jp_cases?.case_kind ?? null,
    court_code: row.jp_cases?.jp_courts?.code ?? null,
    court_name: courtName,
    detail_prices: detail.prices,
    detail_dates: detail.dates,
    detail_properties: detail.properties ?? null,
    has_three_set_pdf: !!detail.has_three_set_pdf,
    photo_urls: photoUrls,
  });
  const mdFilename = `bit_${(row.jp_cases?.case_no ?? row.sale_unit_id)
    .replace(/[^\w\-]+/g, "_")
    .slice(0, 80)}`;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between text-xs">
        <Link href="/jp" className="text-muted-foreground hover:text-primary hover:underline">
          ← 物件一覧
        </Link>
        <ExportButtons markdown={markdown} filename={mdFilename} />
      </div>

      {/* 헤더 */}
      <section className="rounded-lg border bg-card p-6 space-y-3">
        <div className="flex flex-wrap gap-2 items-center">
          <Badge variant="outline" className="text-xs">{row.sale_cls_label ?? "—"}</Badge>
          {status && (
            <span className={`inline-block rounded border px-2 py-0.5 text-xs ${status.tone}`}>
              {status.label}
            </span>
          )}
          {row.yen_10k_trap && (
            <Badge variant="destructive" className="text-xs">⚠ 1万円トラップの疑い</Badge>
          )}
          {detail.has_three_set_pdf && (
            <a href={`/api/jp/pdf/${sale_unit_id}`} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-1 rounded-md bg-emerald-600 text-white px-2.5 py-0.5 text-xs hover:opacity-90">
              📑 三点セット PDF 다운로드
            </a>
          )}
        </div>
        <h1 className="text-2xl font-bold tracking-tight">
          {courtName} <span className="text-muted-foreground font-normal">·</span> {caseNo}
        </h1>
        {addr && (
          <p className="text-sm text-muted-foreground">📍 {addr}</p>
        )}
      </section>

      <div className="grid md:grid-cols-3 gap-4">
        {/* 사진 */}
        <Card className="md:col-span-1">
          <CardHeader>
            <CardTitle className="text-base">사진</CardTitle>
          </CardHeader>
          <CardContent className="p-3">
            {photoUrls.length === 0 ? (
              <div className="aspect-[4/3] bg-muted rounded-md flex items-center justify-center text-sm text-muted-foreground">
                사진 없음
              </div>
            ) : (
              <div className="space-y-2">
                {photoUrls.map((url, i) => (
                  <a key={url + i} href={url} target="_blank" rel="noopener noreferrer">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={url} alt={`物件写真 ${i + 1}`} className="w-full rounded-md border" />
                  </a>
                ))}
              </div>
            )}
            <p className="text-caption-xs text-muted-foreground mt-2">
              {ownPhotos.length > 0
                ? "Supabase Storage セルフホスト"
                : "BIT 元データ直接リンク (取込未完)"}
            </p>
          </CardContent>
        </Card>

        {/* 価格 */}
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">3種価格 + 保証金</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <div className="text-xs text-muted-foreground mb-1">売却基準価額</div>
                <div className="text-2xl font-bold text-amber-600 font-mono">
                  {fmtJpy(prices.sale_standard_price ?? row.sale_standard_price)}
                </div>
                <div className="text-caption-xs text-muted-foreground">裁判所が定めた基準価額</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">買受可能価額</div>
                <div className="text-xl font-semibold font-mono">
                  {fmtJpy(prices.purchase_possible_price ?? row.purchase_possible_price)}
                </div>
                <div className="text-caption-xs text-muted-foreground">買受可能の最低額 (= 基準 × 80%)</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">買受申出保証金</div>
                <div className="text-base font-semibold font-mono">
                  {fmtJpy(prices.bid_deposit ?? row.bid_deposit)}
                </div>
                <div className="text-caption-xs text-muted-foreground">入札保証金 (= 基準 × 20%)</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">鑑定評価額</div>
                <div className="text-base text-muted-foreground font-mono">
                  未取得
                </div>
                <div className="text-caption-xs text-muted-foreground">詳細ページからの追加偵察が必要</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 売却スケジュール */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">📅 売却スケジュール</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid md:grid-cols-2 gap-3 text-sm">
            <div className="flex justify-between rounded-md bg-muted/40 p-3">
              <span className="text-muted-foreground">公示開始日</span>
              <span className="font-mono">{dates.koji_start ?? "—"}</span>
            </div>
            <div className="flex justify-between rounded-md bg-muted/40 p-3">
              <span className="text-muted-foreground">閲覧開始日</span>
              <span className="font-mono">{dates.view_start ?? "—"}</span>
            </div>
            <div className="flex justify-between rounded-md bg-blue-50 border border-blue-200 p-3">
              <span className="text-blue-700 font-medium">入札期間</span>
              <span className="font-mono">{fmtRange(dates.bid_period)}</span>
            </div>
            <div className="flex justify-between rounded-md bg-blue-50 border border-blue-200 p-3">
              <span className="text-blue-700 font-medium">開札期日</span>
              <span className="font-mono">{dates.open_bid_date ?? "—"}</span>
            </div>
            <div className="flex justify-between rounded-md bg-muted/40 p-3">
              <span className="text-muted-foreground">売却決定期日</span>
              <span className="font-mono">{dates.sale_decision_date ?? "—"}</span>
            </div>
            <div className="flex justify-between rounded-md bg-amber-50 border border-amber-200 p-3">
              <span className="text-amber-700 font-medium">特別売却期間</span>
              <span className="font-mono">{fmtRange(dates.special_sale_period)}</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 物件 명세 */}
      {properties.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">🏠 物件明細</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {properties.map((prop, idx) => {
              const fields = prop.fields ?? {};
              const keys = Object.keys(fields);
              if (keys.length === 0) return null;
              return (
                <div key={idx} className="border rounded-md overflow-hidden">
                  {prop.head && (
                    <div className="bg-muted/60 px-3 py-2 text-sm font-semibold">
                      {prop.head}
                    </div>
                  )}
                  <div className="grid sm:grid-cols-2 text-sm">
                    {keys.map((k) => (
                      <div key={k} className="flex border-t first:border-t-0 sm:[&:nth-child(2)]:border-t-0">
                        <div className="w-1/3 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">{k}</div>
                        <div className="flex-1 px-3 py-2 text-xs">{fields[k]}</div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {/* 位置 + 交通 + マップ */}
      {(row.transit_info || addr || hasGeo) && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">🚉 位置 + 交通</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {row.transit_info && (
              <div className="text-sm whitespace-pre-line bg-muted/30 rounded-md p-3">
                {row.transit_info}
              </div>
            )}
            {hasGeo && osmEmbed && (
              <div className="space-y-2">
                <div className="text-xs text-muted-foreground font-mono">
                  座標: {lat}, {lng}
                </div>
                <iframe
                  src={osmEmbed}
                  className="w-full h-[300px] rounded-md border"
                  loading="lazy"
                  title="OpenStreetMap プレビュー"
                />
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              {googleMap && (
                <a href={googleMap} target="_blank" rel="noopener noreferrer"
                   className="text-xs rounded border bg-card hover:bg-muted px-3 py-1.5 inline-block">
                  Google マップ {hasGeo ? "(座標)" : "(住所検索)"} →
                </a>
              )}
              {naverMap && (
                <a href={naverMap} target="_blank" rel="noopener noreferrer"
                   className="text-xs rounded border bg-card hover:bg-muted px-3 py-1.5 inline-block">
                  Naver マップ {hasGeo ? "(座標)" : "(住所検索)"} →
                </a>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* BIT 元データ */}
      <Card className="bg-muted/20">
        <CardContent className="text-xs text-muted-foreground py-4 space-y-1">
          <div>
            <span className="font-medium">BIT 元データ:</span>{" "}
            <a href="https://www.bit.courts.go.jp/" target="_blank" rel="noopener noreferrer"
               className="text-primary hover:underline">bit.courts.go.jp</a>
            {" → 物件詳細は form POST のため直接リンク不可。 "}
            <code className="text-foreground bg-muted px-1 rounded">saleUnitId={sale_unit_id}</code>
            {" / "}
            <code className="text-foreground bg-muted px-1 rounded">courtId={row.jp_cases?.jp_courts?.code ?? "?"}</code>
          </div>
          {detail.has_three_set_pdf && (
            <div>📑 BIT サイトから 三点セット (物件明細書·現況調査報告書·評価書) PDF ダウンロード可能。</div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
