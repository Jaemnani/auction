// 지도 팝업 카드의 "라벨 + 값" 행 생성 — 순수 함수 (property-map.tsx 가 사용).
//
// 원칙: 값이 없어도 **줄과 라벨은 항상 남기고 값만 "-"** 로 둔다.
// (이전엔 값 없으면 줄 자체를 렌더 안 해서 "인수액이 안 보인다" 오해가 반복됐음.
//  라벨이 남아야 기능 존재를 알 수 있고 매물마다 카드 높이도 일정하다.)
// 낙찰 완료 매물은 두 항목 모두 개념상 무의미하므로 빈 문자열.

import { fmtMoneyShort, isSpecOpen, specOpenFrom } from "./format";
import type { PropertyEstimateBrief, PropertyTenancy } from "./types";
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
 *  소스는 상세 계산기에서 저장한 값뿐 (명세서 자동수집 불가 — docs/api_recon.md).
 *
 *  미저장일 때 "-" 옆 안내는 명세서 공개 여부로 갈린다. 헤더에 칩을 더 붙이면
 *  좁은 팝업에서 3개가 줄바꿈되므로, 그 정보가 실제로 필요한 이 줄 안에 둔다
 *  ("-" 가 왜 비었는지와 언제 채울 수 있는지를 같은 자리에서 설명). */
export function assumedRowHtml(
  asm: AssumptionRecord | undefined | null, isSold: boolean,
  saleDate?: string | null,
  tenancy?: PropertyTenancy | null,
): string {
  if (isSold) return "";
  // 명세서에서 자동 추출한 판정이 있으면 그것이 우선 — 사용자가 직접 계산해
  // 저장한 값보다 앞선 근거이고, 저장을 안 한 매물에도 경고가 뜬다.
  if (tenancy && !asm) {
    if (tenancy.verdict === "risk") {
      const deps = tenancy.tenants
        .map((t) => t.deposit)
        .filter((d): d is number => typeof d === "number" && d > 0);
      const amt = deps.length > 0 ? ` 보증금 ${money(Math.max(...deps))}` : "";
      return row("인수액",
        `<strong style="color:#dc2626;font-size:12px">인수 위험</strong>`
        + `<span style="color:#a1a1aa;margin-left:4px">${esc(amt.trim() || "명세서 확인")}</span>`);
    }
    if (tenancy.verdict === "none") {
      return row("인수액",
        `<strong style="color:#15803d;font-size:12px">0</strong>`
        + `<span style="color:#a1a1aa;margin-left:4px">(대항력 임차인 없음)</span>`);
    }
    return row("인수액",
      `${DASH}<span style="color:#d4d4d8;margin-left:4px">(명세서 확인 필요)</span>`);
  }
  if (asm) {
    return row("인수액",
      `<strong style="color:${asm.assumed > 0 ? "#dc2626" : "#15803d"};font-size:12px">`
      + `${money(asm.assumed)}</strong>`
      + `<span style="color:#a1a1aa;margin-left:4px">(낙찰 ${money(asm.bid)} 기준)</span>`);
  }
  const hint = isSpecOpen(saleDate)
    // 지금 명세서를 볼 수 있음 → 바로 계산 가능하다는 신호 (연한 초록 pill)
    ? `<span style="background:#dcfce7;color:#15803d;border-radius:9999px;`
      + `padding:1px 6px;font-size:10px;font-weight:600;margin-left:5px">명세서 공개</span>`
    // 아직 미공개 → 언제부터 가능한지 (기일 7일 전)
    : saleDate
      ? `<span style="color:#d4d4d8;margin-left:5px">${esc(mmdd(specOpenFrom(saleDate)))} 공개</span>`
      : "";
  return row("인수액", `${DASH}${hint}`);
}

/** YYYY-MM-DD → M/D (팝업이 좁아 연도 생략) */
function mmdd(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${Number(m)}/${Number(d)}`;
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
