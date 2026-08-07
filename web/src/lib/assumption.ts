// 대항력 임차인 인수액 계산 — 순수 함수 (assumption-calculator.tsx 가 사용).
//
// 공식: 낙찰자 인수액 = 대항력 임차인 보증금 − 임차인이 배당으로 받는 금액
//
// 법리 요점 (구현 근거):
// - 대항력 발생 = 전입신고(+인도) "다음날 0시" → 말소기준권리와 같은 날 전입이면
//   대항력 없음 (근저당은 당일 주간에 효력 발생).
// - 우선변제(확정일자) 순위 기준일 = max(전입 다음날, 확정일자). 이 기준일이
//   말소기준권리 설정일보다 빨라야 선순위 배당.
// - 배당 조건 = 확정일자 보유 + 배당요구종기 내 배당요구. (소액 최우선변제도
//   배당요구는 필요.)
// - 배당 순서(단순화): 경매비용 → 당해세 등 우선 조세 → 소액임차인 최우선변제
//   → 확정일자/저당권 순위배당.
//
// ⚠ 단순화 고지: 임금채권·조세 법정기일 비교(2023 당해세 개정)·다수 임차인·
// 필요비 등은 미반영. 공식 배당표와 다를 수 있으며 참고용.

export type AssumptionInputs = {
  /** 임차인 보증금 (원) */
  deposit: number;
  /** 전입일 YYYY-MM-DD */
  moveInDate: string | null;
  /** 확정일자 YYYY-MM-DD — 없으면 null */
  fixedDate: string | null;
  /** 배당요구종기 내 배당요구 했는가 */
  demandFiled: boolean;
  /** 말소기준권리 설정일 YYYY-MM-DD */
  lienDate: string | null;
  /** 말소기준(선순위) 채권액 (원) — 등기부 채권최고액/청구액 */
  seniorDebt: number;
  /** 당해세 등 우선 조세 (원) — 미상이면 0 */
  taxPriority: number;
  /** 소액임차인 최우선변제 예상액 (원) — 해당 없으면 0 */
  smallPriority: number;
  /** 경매비용 (원) — null 이면 추정식 사용 */
  costOverride: number | null;
};

/** 경매 집행비용 추정 — 감정료·송달료·수수료 등. 실무 어림 200만 + 낙찰가 0.5%. */
export function estimateAuctionCost(bid: number): number {
  return Math.round(2_000_000 + bid * 0.005);
}

/** 전입 다음날 (대항력 발생일) */
function nextDay(iso: string): string {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

/** 대항력 판정 — true/false, 날짜 부족 시 null.
 *  전입 "다음날" 대항력 발생 → 말소기준일과 같은 날 전입이면 false. */
export function hasOpposability(
  moveInDate: string | null, lienDate: string | null,
): boolean | null {
  if (!moveInDate || !lienDate) return null;
  return nextDay(moveInDate) <= lienDate;
}

export type SimulationRow = {
  bid: number;            // 낙찰가
  cost: number;           // 경매비용
  dividend: number;       // 임차인 배당액 (최우선변제 포함)
  assumed: number;        // 낙찰자 인수액
  effective: number;      // 실질 취득원가 = 낙찰가 + 인수액
  tenantFirst: boolean;   // 임차인이 선순위 채권보다 먼저 배당받는가
};

/** 낙찰가 1개에 대한 배당·인수액 시뮬레이션 */
export function simulate(inputs: AssumptionInputs, bid: number): SimulationRow {
  const opposable = hasOpposability(inputs.moveInDate, inputs.lienDate);
  const cost = inputs.costOverride ?? estimateAuctionCost(bid);

  let rem = Math.max(0, bid - cost);
  // 당해세 등 우선 조세 (단순화: 임차인보다 선순위 가정)
  rem -= Math.min(rem, Math.max(0, inputs.taxPriority));

  let dividend = 0;
  // 소액 최우선변제 — 배당요구했을 때만
  if (inputs.demandFiled && inputs.smallPriority > 0) {
    const small = Math.min(rem, inputs.smallPriority, inputs.deposit);
    dividend += small;
    rem -= small;
  }

  // 확정일자 순위배당 — 확정일자 + 배당요구 모두 필요
  let tenantFirst = false;
  if (inputs.demandFiled && inputs.fixedDate) {
    // 우선변제 기준일 = max(전입 다음날, 확정일자)
    const rankDate = inputs.moveInDate
      ? (nextDay(inputs.moveInDate) > inputs.fixedDate
          ? nextDay(inputs.moveInDate) : inputs.fixedDate)
      : inputs.fixedDate;
    // 기준일이 말소기준일보다 "빨라야" 선순위 (같은 날이면 담보권 우선)
    tenantFirst = inputs.lienDate != null && rankDate < inputs.lienDate;
    if (!tenantFirst) {
      rem -= Math.min(rem, Math.max(0, inputs.seniorDebt));
    }
    const rank = Math.min(rem, Math.max(0, inputs.deposit - dividend));
    dividend += rank;
    rem -= rank;
  }

  // 인수액 — 대항력 있을 때만. 판정 불가(null)면 보수적으로 "있음" 취급.
  const assumed = opposable === false ? 0 : Math.max(0, inputs.deposit - dividend);
  return { bid, cost, dividend, assumed, effective: bid + assumed, tenantFirst };
}

/** 낙찰가 시나리오 축 — 최저가~감정가(없으면 최저가 130%) 5구간, 백만 단위 반올림 */
export function scenarioBids(
  minPrice: number | null, appraisal: number | null,
): number[] {
  const lo = minPrice ?? appraisal;
  if (!lo) return [];
  const hi = Math.max(appraisal ?? 0, Math.round(lo * 1.3));
  const n = 5;
  const out: number[] = [];
  for (let i = 0; i < n; i++) {
    const v = lo + ((hi - lo) * i) / (n - 1);
    out.push(Math.round(v / 1_000_000) * 1_000_000);
  }
  return Array.from(new Set(out));
}
