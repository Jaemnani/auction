// 일본 매물 상세 → Markdown 변환.

import type { JpDetailProperty } from "./jp-detail";

type Prices = {
  sale_standard_price?: number | null;
  bid_deposit?: number | null;
  purchase_possible_price?: number | null;
} | null | undefined;

type Dates = {
  koji_start?: string | null;
  view_start?: string | null;
  open_bid_date?: string | null;
  sale_decision_date?: string | null;
  bid_period?: { start?: string | null; end?: string | null } | null;
  special_sale_period?: { start?: string | null; end?: string | null } | null;
} | null | undefined;

export type JpRowForMd = {
  sale_unit_id: string;
  sale_cls_label: string | null;
  status: string | null;
  yen_10k_trap: boolean | null;
  address_text: string | null;
  transit_info: string | null;
  sale_standard_price: number | null;
  bid_deposit: number | null;
  purchase_possible_price: number | null;
  latitude: number | null;
  longitude: number | null;
  case_no: string | null;
  case_kind: string | null;
  court_code: string | null;
  court_name: string | null;
  detail_prices: Prices;
  detail_dates: Dates;
  detail_properties: JpDetailProperty[] | null;
  has_three_set_pdf: boolean;
  photo_urls: string[];
};

const STATUS_LABEL: Record<string, string> = {
  period_bid: "期間入札",
  special_sale: "特別売却",
  reval_pending: "評価再調整",
  re_bid: "再入札",
  closed: "終結",
  aborted: "中止",
};

function fmtJpy(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString("ja-JP") + "円";
}

function fmtRange(r: { start?: string | null; end?: string | null } | null | undefined): string {
  if (!r) return "—";
  if (!r.start && !r.end) return "—";
  return `${r.start ?? "?"} ~ ${r.end ?? "?"}`;
}

export function buildJpMarkdown(row: JpRowForMd, siteOrigin = "https://auction-seven-omega.vercel.app"): string {
  const lines: string[] = [];

  const title = row.case_no
    ? `${row.court_name ?? ""} ${row.case_no}`.trim()
    : `BIT ${row.sale_unit_id}`;
  lines.push(`# 🇯🇵 ${title}`);
  lines.push("");
  lines.push(`> Generated from ${siteOrigin}/jp/p/${row.sale_unit_id}`);
  lines.push("");

  // 메타
  lines.push("## 메타");
  lines.push(`- **사건번호**: \`${row.case_no ?? row.sale_unit_id}\``);
  lines.push(`- **법원**: ${row.court_name ?? "—"}${row.court_code ? ` (courtId=${row.court_code})` : ""}`);
  if (row.case_kind) lines.push(`- **사건 종류**: ${row.case_kind} ${row.case_kind === "ケ" ? "(担保不動産競売)" : row.case_kind === "ヌ" ? "(強制競売)" : ""}`);
  lines.push(`- **종별**: ${row.sale_cls_label ?? "—"}`);
  if (row.status) lines.push(`- **상태**: ${STATUS_LABEL[row.status] ?? row.status}`);
  if (row.yen_10k_trap) lines.push(`- ⚠ **1万円 함정 의심** (売却基準価額 ≤ 100,000円)`);
  if (row.has_three_set_pdf) lines.push(`- 📑 **三点セット PDF 제공** — \`${siteOrigin}/api/jp/pdf/${row.sale_unit_id}\``);
  lines.push(`- **BIT saleUnitId**: \`${row.sale_unit_id}\``);
  lines.push("");

  // 가격
  const p = row.detail_prices ?? {};
  lines.push("## 3종 가격");
  lines.push(`| 항목 | 금액 | 비고 |`);
  lines.push(`|---|---:|---|`);
  lines.push(`| 売却基準価額 | ${fmtJpy(p.sale_standard_price ?? row.sale_standard_price)} | 법원이 정한 기준가 |`);
  lines.push(`| 買受可能価額 | ${fmtJpy(p.purchase_possible_price ?? row.purchase_possible_price)} | 매수 가능 최저가 (= 기준 × 80%) |`);
  lines.push(`| 買受申出保証金 | ${fmtJpy(p.bid_deposit ?? row.bid_deposit)} | 입찰 보증금 (= 기준 × 20%) |`);
  lines.push(`| 鑑定評価額 | (미수집) | 상세 페이지 추가 정찰 필요 |`);
  lines.push("");

  // 매각 일정
  const d = row.detail_dates ?? {};
  lines.push("## 매각 일정");
  lines.push(`- **公示開始日**: ${d.koji_start ?? "—"}`);
  lines.push(`- **閲覧開始日**: ${d.view_start ?? "—"}`);
  lines.push(`- **入札期間**: ${fmtRange(d.bid_period)}`);
  lines.push(`- **開札期日**: ${d.open_bid_date ?? "—"}`);
  lines.push(`- **売却決定期日**: ${d.sale_decision_date ?? "—"}`);
  lines.push(`- **特別売却期間**: ${fmtRange(d.special_sale_period)}`);
  lines.push("");

  // 주소·좌표·교통
  if (row.address_text || row.latitude != null) {
    lines.push("## 위치");
    if (row.address_text) lines.push(`- **所在地**: ${row.address_text}`);
    if (row.latitude != null && row.longitude != null) {
      lines.push(`- **좌표**: \`${row.latitude}, ${row.longitude}\` (WGS84)`);
      lines.push(`  - [Google 지도](https://www.google.com/maps?q=${row.latitude},${row.longitude}&z=18)`);
      lines.push(`  - [OpenStreetMap](https://www.openstreetmap.org/?mlat=${row.latitude}&mlon=${row.longitude}&zoom=18)`);
    }
    if (row.transit_info) {
      lines.push(`- **교통**:`);
      for (const line of row.transit_info.split(/\n/)) {
        if (line.trim()) lines.push(`  - ${line.trim()}`);
      }
    }
    lines.push("");
  }

  // 物件 명세
  const props = row.detail_properties ?? [];
  if (props.length > 0) {
    lines.push("## 物件 명세");
    for (const item of props) {
      const f = item.fields ?? {};
      const keys = Object.keys(f);
      if (keys.length === 0) continue;
      if (item.head) lines.push(`### ${item.head}`);
      lines.push(`| 항목 | 값 |`);
      lines.push(`|---|---|`);
      for (const k of keys) lines.push(`| ${k} | ${f[k]} |`);
      lines.push("");
    }
  }

  // 사진
  if (row.photo_urls.length > 0) {
    lines.push("## 사진");
    for (const u of row.photo_urls) lines.push(`- ${u}`);
    lines.push("");
  }

  // 원본
  lines.push("## 원본");
  lines.push(`- **BIT 사이트**: <https://www.bit.courts.go.jp/>`);
  lines.push(`  - 매물 상세는 form POST 기반이라 직접 링크 불가. 본 사이트 상세 페이지 (${siteOrigin}/jp/p/${row.sale_unit_id}) 사용 권장`);
  lines.push("");
  lines.push(`---`);
  lines.push(`Exported from auction-seven-omega.vercel.app · 데이터는 BIT 사이트 정보를 우선 확인하세요`);

  return lines.join("\n");
}
