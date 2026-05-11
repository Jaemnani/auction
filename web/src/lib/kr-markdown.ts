// 한국 매물 상세 → Markdown 변환.

import type { PropertyDetail } from "./types";
import { fmtDate, fmtMoney, fmtDiscount, fmtPercent } from "./format";

type Row = PropertyDetail;

function safe(v: string | null | undefined): string {
  return v ?? "—";
}

export function buildKrMarkdown(
  p: Row,
  names: Record<string, string>,
  photoUrls: string[],
  siteOrigin = "https://auction-seven-omega.vercel.app",
): string {
  const cs = p.cases;
  const lines: string[] = [];

  const usageParts = [p.usage_lcl_cd, p.usage_mcl_cd, p.usage_scl_cd]
    .map((c) => c && names[c]).filter(Boolean) as string[];
  const usageLabel = usageParts.length > 0 ? usageParts.join(" › ") : "—";

  const sdName = p.sd_code ? names[p.sd_code] : null;
  const sggName = p.sgg_code ? names[p.sgg_code] : null;
  const regionParts = [sdName, sggName].filter(Boolean).join(" ");

  const courtName = cs?.courts?.name ?? (cs?.court_code ? names[cs.court_code] : null);
  const dept = cs?.jdbn_name ?? "";
  const courtPlusDept = [courtName, dept].filter(Boolean).join(" · ");

  const pricePct = p.appraisal_amount && p.min_sale_price
    ? Math.round((p.min_sale_price / p.appraisal_amount) * 100)
    : null;

  lines.push(`# 🇰🇷 ${cs?.case_no ?? p.docid ?? "매물 상세"}${p.maemul_ser > 1 ? ` #${p.maemul_ser}` : ""}`);
  lines.push("");
  if (p.docid) lines.push(`> Generated from ${siteOrigin}/p/${encodeURIComponent(p.docid)}`);
  lines.push("");

  // 메타
  lines.push("## 메타");
  lines.push(`- **사건번호**: \`${cs?.case_no ?? "—"}\`${p.maemul_ser > 1 ? ` #${p.maemul_ser}` : ""}`);
  lines.push(`- **사건명**: ${safe(cs?.case_name)}`);
  lines.push(`- **법원·경매계**: ${courtPlusDept || "—"}`);
  lines.push(`- **접수일**: ${fmtDate(cs?.receipt_date ?? null)}`);
  lines.push(`- **용도**: ${usageLabel}`);
  lines.push("");

  // 주소
  lines.push("## 주소");
  if (p.road_addr) lines.push(`- **도로명**: ${p.road_addr}`);
  if (p.lot_addr) lines.push(`- **지번**: ${p.lot_addr}`);
  if (regionParts) lines.push(`- **행정 구역**: ${regionParts}`);
  if (p.conv_addr) lines.push(`- **표시 주소**: ${p.conv_addr}`);
  if (p.longitude != null && p.latitude != null) {
    lines.push(`- **좌표**: \`${p.latitude}, ${p.longitude}\``);
    lines.push(`  - [Naver 지도](https://map.naver.com/v5/?c=${p.longitude},${p.latitude},18,0,0,0,dh)`);
    lines.push(`  - [Google 지도](https://www.google.com/maps?q=${p.latitude},${p.longitude}&z=18)`);
  }
  lines.push("");

  // 가격
  lines.push("## 가격");
  lines.push(`| 항목 | 값 |`);
  lines.push(`|---|---:|`);
  lines.push(`| 감정가 | ${fmtMoney(p.appraisal_amount)} |`);
  lines.push(`| 최저매각가 | ${fmtMoney(p.min_sale_price)}${pricePct != null ? ` (감정가의 ${pricePct}%)` : ""} |`);
  lines.push(`| 매각가율 | ${fmtPercent(p.min_sale_price, p.appraisal_amount)} |`);
  lines.push(`| 할인율 | ${fmtDiscount(p.min_sale_price, p.appraisal_amount)} |`);
  lines.push(`| 유찰횟수 | ${p.fail_count != null ? `${p.fail_count}회` : "—"} |`);
  lines.push(`| 매각기일 | ${fmtDate(p.sale_date)} |`);
  lines.push(`| 매각결정기일 | ${fmtDate(p.sale_decision_date)} |`);
  lines.push("");

  // 건물·면적
  if (p.building_summary || p.area_summary) {
    lines.push("## 건물·면적");
    if (p.building_summary) lines.push(`- **건물 요약**: ${p.building_summary}`);
    if (p.area_summary) lines.push(`- **면적 요약**: ${p.area_summary}`);
    lines.push("");
  }

  // 매각기일 이력
  const sd = (p.property_sale_dates ?? []).slice().sort((a, b) => a.seq - b.seq);
  if (sd.length > 0) {
    lines.push("## 매각기일 이력");
    lines.push(`| 회차 | 기일 | 장소 | 최저가 | 결과 |`);
    lines.push(`|---:|---|---|---:|---|`);
    for (const s of sd) {
      lines.push(
        `| ${s.seq} | ${fmtDate(s.sale_date)} ${s.hour ?? ""} | ${safe(s.place)} | ${fmtMoney(s.min_price)} | ${s.result_cd ?? "—"} |`
      );
    }
    lines.push("");
  }

  // 감정평가 요항
  const aeeWevl = (((p.detail_result ?? {}) as Record<string, unknown>).aeeWevlMnpntLst ?? []) as Array<Record<string, unknown>>;
  if (aeeWevl.length > 0) {
    lines.push("## 감정평가 요항");
    for (const item of aeeWevl) {
      const ctt = String(item?.aeeWevlMnpntCtt ?? "").trim();
      const itmCd = String(item?.aeeWevlMnpntItmCd ?? "");
      if (!ctt || ctt === "-." || ctt === "-") continue;
      lines.push(`### 항목 ${itmCd}`);
      for (const line of ctt.split(/\n/)) {
        if (line.trim()) lines.push(`> ${line.trim()}`);
      }
      lines.push("");
    }
  }

  // 사진
  if (photoUrls.length > 0) {
    lines.push("## 사진");
    for (const u of photoUrls) lines.push(`- ${u}`);
    lines.push("");
  }

  // 원본
  lines.push("## 원본");
  if (cs?.case_no && cs?.court_code) {
    lines.push(`- **법원경매정보 (courtauction.go.kr)**: 사건번호 \`${cs.case_no}\`, 법원 \`${cs.court_code}\``);
  }
  if (p.docid) lines.push(`- **본 사이트 상세**: ${siteOrigin}/p/${encodeURIComponent(p.docid)}`);
  lines.push("");
  lines.push(`---`);
  lines.push(`Exported from auction-seven-omega.vercel.app · 데이터는 공식 사이트(courtauction.go.kr)를 우선 확인하세요`);

  return lines.join("\n");
}
