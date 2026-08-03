// 한국 매물 상세 → Markdown 변환.
// 상세 페이지에 노출되는 정보(낙찰/위험/안전도/예상가/임차인·등기 목록 포함)와
// 최대한 1:1 — 페이지에 섹션이 추가되면 여기도 동기화할 것.

import type { PropertyDetail } from "./types";
import type { PropertyEstimate } from "./queries";
import { fmtDate, fmtMoney, fmtDiscount, fmtPercent } from "./format";
import {
  parseRiskFlags, parseDposRate, parsePrimaryLien, parseCaseStatus, dDay, fmtDDay,
} from "./analysis";
import { AEE_LABELS, DETAIL_FIELD_LABELS } from "./kr-detail-labels";

type Row = PropertyDetail;

function safe(v: string | null | undefined): string {
  return v ?? "—";
}

// 안전도 점수 → 등급명 (score-badge.tsx 색 구간과 동일)
function scoreGrade(score: number): string {
  return score >= 80 ? "안전" : score >= 65 ? "양호" : score >= 45 ? "주의" : "위험";
}

export function buildKrMarkdown(
  p: Row,
  names: Record<string, string>,
  photoUrls: string[],
  estimate: PropertyEstimate | null = null,
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

  // 낙찰 완료 (0018) — 종결 후 30일 유예창 동안 표시
  if (p.final_result === "sold") {
    const soldRate = p.appraisal_amount && p.sold_amount
      ? Math.round((p.sold_amount / p.appraisal_amount) * 100)
      : null;
    lines.push("## 낙찰 완료");
    lines.push(`- **낙찰가**: ${fmtMoney(p.sold_amount ?? null)}${soldRate != null ? ` (감정가의 ${soldRate}%)` : ""}`);
    if (p.sold_date) lines.push(`- **낙찰일**: ${fmtDate(p.sold_date)}`);
    lines.push("");
  }

  // 입찰 전 핵심 정보 — 상세 페이지 PropertyRiskCard와 동일 소스
  {
    const flags = parseRiskFlags(p.rmk);
    const lien = parsePrimaryLien(p.primary_liens);
    const stat = parseCaseStatus(p.case_prog, p.susp_stat, p.susp_rsn);
    const dpos = parseDposRate(p.dpos_rate);
    const d = dDay(p.sale_date);
    const spcRmk = p.spc_rmk && String(p.spc_rmk).trim() && String(p.spc_rmk).trim() !== "-"
      ? String(p.spc_rmk).trim() : null;
    const hasAny = flags.length > 0 || lien || stat || dpos || spcRmk || d != null;
    if (hasAny) {
      lines.push("## 입찰 전 핵심 정보");
      if (d != null) lines.push(`- **매각기일까지**: ${fmtDDay(d)} (${fmtDate(p.sale_date)})`);
      if (stat) lines.push(`- **진행 상태**: ${stat.label}${stat.reason ? ` · ${stat.reason}` : ""}`);
      if (dpos) lines.push(`- **매수신청 보증금**: ${dpos.rate}%${dpos.isSpecial ? " (특별매각조건)" : ""}`);
      if (flags.length > 0) {
        const icon = { danger: "🔴", warn: "🟠", info: "🔵" } as const;
        lines.push(`- **물건 비고 배지**: ${flags.map((f) => `${icon[f.level]} ${f.label}`).join(" · ")}`);
      }
      if (lien) {
        lines.push(`- **말소기준권리 (후보)**: ${lien.date} ${lien.type}${lien.others.length > 0 ? ` (후순위 ${lien.others.length}건)` : ""}`);
        for (const o of lien.others.slice(0, 5)) lines.push(`  - 후순위: ${o}`);
      }
      if (spcRmk) {
        lines.push(`- **물건 특정 비고**:`);
        for (const line of spcRmk.split(/\n/)) if (line.trim()) lines.push(`  > ${line.trim()}`);
      }
      lines.push(`- ※ 자동 추출 — 정확한 권리분석은 매각물건명세서·등기부등본 직접 확인`);
      lines.push("");
    }
  }

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
  if (p.claim_amt != null && Number(p.claim_amt) > 0) {
    const claimPct = p.appraisal_amount
      ? ` (감정가의 ${Math.round(Number(p.claim_amt) / p.appraisal_amount * 100)}%)` : "";
    lines.push(`| 청구금액 | ${fmtMoney(Number(p.claim_amt))}${claimPct} |`);
  }
  lines.push(`| 매각기일 | ${fmtDate(p.sale_date)} |`);
  lines.push(`| 매각결정기일 | ${fmtDate(p.sale_decision_date)} |`);
  lines.push("");

  // 매수 안전도 (0023) — 가격 제외 위험성 점수
  if (p.scores) {
    const sc = p.scores;
    lines.push("## 매수 안전도 (참고)");
    lines.push(`- **점수**: ${sc.score}/100 — ${scoreGrade(sc.score)}${sc.confidence === "low" ? " (⚠ 상세정보 미확보, 잠정치)" : sc.confidence === "medium" ? " (건물 연식 정보 일부 부족)" : ""}`);
    const factors = sc.breakdown?.top_factors ?? [];
    if (factors.length > 0) {
      lines.push(`- **감점 요인**: ${factors.map((f) => `${f.label} (−${f.penalty}점)`).join(" · ")}`);
    }
    lines.push(`- ※ 법적 위험 기반 점수 (가격 매력도 제외) — 입찰 판단은 권리분석 직접 확인 필수`);
    lines.push("");
  }

  // 낙찰 예상가 (0022) — 진행중 매물만
  if (p.final_result !== "sold" && estimate?.estimated_price != null) {
    const e = estimate;
    lines.push("## 낙찰 예상가 (베타)");
    lines.push(`- **예상가**: ${fmtMoney(e.estimated_price)}${e.estimated_rate_pct != null ? ` (감정가의 ${e.estimated_rate_pct}%)` : ""}`);
    if (e.estimated_low != null && e.estimated_high != null) {
      lines.push(`- **범위**: ${fmtMoney(e.estimated_low)} ~ ${fmtMoney(e.estimated_high)}`);
    }
    lines.push(`- **방법**: ${e.method === "model"
      ? `자체 낙찰 데이터 예측 모델${e.model_version ? ` (${e.model_version})` : ""} · 학습 표본 ${e.sample_count ?? 0}건`
      : "지역 평균 매각가율 추정 (모델 표본 부족 — 참고용)"}`);
    lines.push(`- ※ 통계 모델의 추정치이며 실제 낙찰가와 다를 수 있음. 입찰 판단 책임은 이용자에게 있음`);
    lines.push("");
  }

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

  // 감정평가 요항 — 항목 코드를 한글 라벨로 (페이지와 동일)
  const detailRes = (p.detail_result ?? {}) as Record<string, unknown>;
  const aeeWevl = (detailRes.aeeWevlMnpntLst ?? []) as Array<Record<string, unknown>>;
  if (aeeWevl.length > 0) {
    lines.push("## 감정평가 요항");
    aeeWevl.forEach((item, i) => {
      const ctt = String(item?.aeeWevlMnpntCtt ?? "").trim();
      const itmCd = String(item?.aeeWevlMnpntItmCd ?? "");
      if (!ctt || ctt === "-." || ctt === "-") return;
      lines.push(`### ${AEE_LABELS[itmCd] ?? `항목 ${itmCd || i + 1}`}`);
      for (const line of ctt.split(/\n/)) {
        if (line.trim()) lines.push(`> ${line.trim()}`);
      }
      lines.push("");
    });
  }

  // 상세 목록 3종 (임차인/등기·토지 권리/매각대상물) — 페이지 DetailListCard와 동일 소스.
  // 스칼라 필드만, 알려진 키는 한글 라벨.
  const pushDetailList = (title: string, items: Array<Record<string, unknown>>) => {
    const rows = (items ?? []).map((it) =>
      Object.entries(it).filter(([, v]) => v !== null && v !== "" && typeof v !== "object"),
    ).filter((entries) => entries.length > 0);
    if (rows.length === 0) return;
    lines.push(`## ${title}`);
    rows.forEach((entries, i) => {
      lines.push(`${i + 1}. ${entries
        .map(([k, v]) => `**${DETAIL_FIELD_LABELS[k] ?? k}**: ${String(v)}`)
        .join(" · ")}`);
    });
    lines.push("");
  };
  pushDetailList("임차인현황", (detailRes.gdsRletStLtnoLstAll ?? []) as Array<Record<string, unknown>>);
  pushDetailList("등기부 / 토지 권리", (detailRes.rgltLandLstAll ?? []) as Array<Record<string, unknown>>);
  pushDetailList("매각대상물", (detailRes.gdsDspslObjctLst ?? []) as Array<Record<string, unknown>>);

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
