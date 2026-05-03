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
