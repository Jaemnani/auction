// 표시용 포매터
export function fmtMoney(v: number | null | undefined): string {
  if (v == null) return "-";
  if (v >= 1_0000_0000) {
    const eok = Math.floor(v / 1_0000_0000);
    const rest = Math.floor((v % 1_0000_0000) / 10000);
    return rest > 0 ? `${eok}억 ${rest.toLocaleString()}만원` : `${eok}억원`;
  }
  if (v >= 10000) {
    return `${Math.floor(v / 10000).toLocaleString()}만원`;
  }
  return `${v.toLocaleString()}원`;
}

export function fmtMoneyShort(v: number | null | undefined): string {
  if (v == null) return "-";
  if (v >= 1_0000_0000) {
    const eok = v / 1_0000_0000;
    return `${eok.toFixed(eok >= 10 ? 0 : 1)}억`;
  }
  if (v >= 10000) {
    return `${Math.floor(v / 10000).toLocaleString()}만`;
  }
  return v.toLocaleString();
}

export function fmtDate(s: string | null | undefined): string {
  if (!s) return "-";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

export function fmtPercent(min: number | null, base: number | null): string {
  if (!min || !base || base === 0) return "-";
  return `${Math.round((min / base) * 100)}%`;
}

export function fmtDiscount(min: number | null, base: number | null): string {
  if (!min || !base || base === 0) return "-";
  const off = (1 - min / base) * 100;
  return off > 0 ? `▼${Math.round(off)}%` : "-";
}

// ---------- 한국 날짜 (매각기일 기준) ----------
// 매각기일은 법원(한국) 날짜다. 서버는 UTC(Vercel)라 toISOString() 을 그대로 쓰면
// KST 00:00~09:00 구간에서 하루 밀린다 (어제 기일이 "오늘 이후"로 잡히는 등).
// 명세서 공개창 계산은 서버(쿼리)와 클라이언트(안내 문구)가 같은 값을 써야 하므로
// 여기 한 곳에서만 만든다.
const KST_OFFSET_MS = 9 * 60 * 60 * 1000;

function kstDateStr(ms: number): string {
  return new Date(ms + KST_OFFSET_MS).toISOString().slice(0, 10);
}

/** 오늘 (KST, YYYY-MM-DD) */
export function todayKst(): string {
  return kstDateStr(Date.now());
}

/** 오늘 + n일 (KST, YYYY-MM-DD) */
export function plusDaysKst(n: number): string {
  return kstDateStr(Date.now() + n * 86_400_000);
}

/** 매각물건명세서 공개 기간 (일) — 법원은 매각기일 1주 전부터 공개. */
export const SPEC_OPEN_DAYS = 7;

/** 매각물건명세서 공개 시작일 (= 매각기일 − 7일, YYYY-MM-DD). */
export function specOpenFrom(saleDate: string): string {
  return new Date(Date.parse(`${saleDate}T00:00:00Z`) - SPEC_OPEN_DAYS * 86_400_000)
    .toISOString().slice(0, 10);
}

/** 지금 명세서를 열람할 수 있는가 (공개 시작일 ≤ 오늘 ≤ 매각기일).
 *  YYYY-MM-DD 는 사전순 비교가 날짜순과 같아 문자열 비교로 충분. */
export function isSpecOpen(saleDate: string | null | undefined): boolean {
  if (!saleDate) return false;
  const today = todayKst();
  return specOpenFrom(saleDate) <= today && today <= saleDate;
}
