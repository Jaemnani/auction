// 지도 팝업 카드의 "라벨 + 값" 행 생성 — 순수 함수 (property-map.tsx 가 사용).
//
// 원칙: 값이 없어도 **줄과 라벨은 항상 남기고 값만 "-"** 로 둔다.
// (이전엔 값 없으면 줄 자체를 렌더 안 해서 "인수액이 안 보인다" 오해가 반복됐음.
//  라벨이 남아야 기능 존재를 알 수 있고 매물마다 카드 높이도 일정하다.)
// 낙찰 완료 매물은 두 항목 모두 개념상 무의미하므로 빈 문자열.

import { fmtMoneyShort } from "./format";
import type { PropertyEstimateBrief } from "./types";
import type { AssumptionRecord } from "./assumption-store";

const DASH = `<span style="color:#a1a1aa">-</span>`;
const ROW_STYLE =
  "display:flex;justify-content:space-between;align-items:baseline;" +
  "color:#71717a;font-size:11px;margin-top:3px";

function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const money = (v: number | null | undefined) => esc(fmtMoneyShort(v ?? null));

function row(label: string, value: string): string {
  return `<div style="${ROW_STYLE}"><span>${label}</span><span>${value}</span></div>`;
}

/** 인수액 — 대항력 임차인 보증금 중 낙찰자가 떠안는 금액.
 *  소스는 상세 계산기에서 저장한 값뿐 (명세서 자동수집 불가 — docs/api_recon.md). */
export function assumedRowHtml(
  asm: AssumptionRecord | undefined | null, isSold: boolean,
): string {
  if (isSold) return "";
  const value = asm
    ? `<strong style="color:${asm.assumed > 0 ? "#dc2626" : "#15803d"};font-size:12px">`
      + `${money(asm.assumed)}</strong>`
      + `<span style="color:#a1a1aa;margin-left:4px">(낙찰 ${money(asm.bid)} 기준)</span>`
    : `${DASH}<span style="color:#d4d4d8;margin-left:4px">(상세에서 계산)</span>`;
  return row("인수액", value);
}

/** 낙찰 예상가 (0022) — region_avg 폴백은 "참고" 표기. */
export function estimateRowHtml(
  est: PropertyEstimateBrief | undefined | null, isSold: boolean,
): string {
  if (isSold) return "";
  const has = est?.estimated_price != null;
  const label = "예상 낙찰가"
    + (has && est.method === "region_avg"
      ? ` <span style="color:#a1a1aa">(참고)</span>` : "");
  const value = has
    ? `<strong style="color:#0f766e;font-size:12px">${money(est.estimated_price)}</strong>`
      + (est.estimated_rate_pct != null
        ? `<span style="color:#a1a1aa;margin-left:4px">(${est.estimated_rate_pct}%)</span>` : "")
    : DASH;
  return row(label, value);
}
