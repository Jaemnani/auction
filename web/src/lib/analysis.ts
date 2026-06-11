// 경매 권리분석 헬퍼 — courtauction 응답 텍스트 → 배지/플래그/요약
// 모두 pure function. 입력은 detail_result 안의 평문 텍스트.

export type RiskFlag = {
  level: "danger" | "warn" | "info";
  label: string;
  desc?: string;
};

// 위험 키워드 → 배지 — 입찰 전 반드시 확인
const RISK_PATTERNS: Array<{ re: RegExp; flag: RiskFlag }> = [
  { re: /유치권/, flag: { level: "danger", label: "유치권", desc: "낙찰자가 인수 가능 — 명세서 확인 필수" } },
  { re: /법정지상권/, flag: { level: "danger", label: "법정지상권", desc: "토지·건물 소유자 분리 시 발생" } },
  { re: /분묘기지권/, flag: { level: "danger", label: "분묘기지권", desc: "분묘 소유자가 토지 사용권 주장 가능" } },
  { re: /대지권\s*미등기|대지권없음/, flag: { level: "danger", label: "대지권 미등기", desc: "건물만 낙찰 — 토지 별도 분쟁" } },
  { re: /토지별도등기/, flag: { level: "danger", label: "토지별도등기", desc: "토지 권리관계 별도 검토 필요" } },
  { re: /위반건축물/, flag: { level: "danger", label: "위반건축물", desc: "행정처분/이행강제금 위험" } },
];

// 정보성 키워드 — 참고 표시
const INFO_PATTERNS: Array<{ re: RegExp; flag: RiskFlag }> = [
  { re: /제시외\s*건물/, flag: { level: "warn", label: "제시외 건물 포함" } },
  { re: /일괄매각/, flag: { level: "info", label: "일괄매각" } },
  { re: /개별매각/, flag: { level: "info", label: "개별매각" } },
  { re: /공실/, flag: { level: "info", label: "공실" } },
  { re: /점유자\s*없음/, flag: { level: "info", label: "점유자 없음" } },
];

export function parseRiskFlags(rmk: string | null | undefined): RiskFlag[] {
  if (!rmk) return [];
  const text = String(rmk);
  const out: RiskFlag[] = [];
  for (const p of RISK_PATTERNS) if (p.re.test(text)) out.push(p.flag);
  for (const p of INFO_PATTERNS) if (p.re.test(text)) out.push(p.flag);
  return out;
}

// 매수신청 보증금률 — 일반 10%, 다르면 강조
export function parseDposRate(prchDposRate: unknown): {
  rate: number; isSpecial: boolean;
} | null {
  const r = typeof prchDposRate === "number"
    ? prchDposRate
    : typeof prchDposRate === "string"
      ? Number(prchDposRate)
      : null;
  if (r == null || isNaN(r) || r <= 0) return null;
  return { rate: r, isSpecial: r !== 10 };
}

// 말소기준권리 후보 — tprtyRnkHypthcStngDts에서 첫 번째 권리 추출
// 입력: "1. 2019.08.30 근저당권 / 2. 2020.04.10 근저당권"
// 출력: { date: "2019-08-30", type: "근저당권" }
export function parsePrimaryLien(text: string | null | undefined): {
  date: string;
  type: string;
  raw: string;
  others: string[];
} | null {
  if (!text) return null;
  const items = String(text)
    .split(/\s*\/\s*/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (items.length === 0) return null;

  const parseOne = (s: string) => {
    // "1. 2019.08.30 근저당권" 또는 "1) 2019-08-30 근저당권"
    const m = s.match(/^\s*\d+[.)]?\s*(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\s*(.+?)\s*$/);
    if (!m) return null;
    const [_, y, mo, d, type] = m;
    return {
      date: `${y}-${mo.padStart(2, "0")}-${d.padStart(2, "0")}`,
      type: type.trim(),
      raw: s,
    };
  };
  const first = parseOne(items[0]);
  if (!first) return null;
  return {
    ...first,
    others: items.slice(1).map((s) => parseOne(s)?.raw ?? s),
  };
}

// 사건 진행상태 — 코드 → 한글 매핑 + 심각도
// (코드값은 일부만 알고 있으므로 가능한 추정)
export function parseCaseStatus(
  csProgStatCd: string | null | undefined,
  auctnSuspStatCd: string | null | undefined,
  csProgSuspRsn: string | null | undefined,
): { label: string; level: "ok" | "warn" | "danger"; reason?: string } | null {
  const susp = String(auctnSuspStatCd ?? "").trim();
  if (susp && susp !== "00") {
    return {
      label: "정지/연기/취하",
      level: "danger",
      reason: csProgSuspRsn ?? undefined,
    };
  }
  const prog = String(csProgStatCd ?? "").trim();
  if (!prog) return null;
  // 보유 데이터에서 흔히 본 값
  // 0002100001 = 진행 중 (추정 — 다수 매물에서 관찰됨)
  if (prog.endsWith("0001")) return { label: "진행 중", level: "ok" };
  if (prog.endsWith("0002")) return { label: "변경", level: "warn" };
  if (prog.endsWith("0003")) return { label: "정지", level: "danger" };
  if (prog.endsWith("0004")) return { label: "취하", level: "danger" };
  // 미확인 코드는 "안전(ok/초록)"으로 단정하지 않음 — 사용자가 직접 확인하도록 warn 표시.
  return { label: "상태 미상", level: "warn" };
}

// D-day — 매각기일까지 남은 일수
export function dDay(saleDate: string | null | undefined): number | null {
  if (!saleDate) return null;
  // saleDate 는 KST 달력상 날짜(YYYY-MM-DD). 양쪽 모두 "UTC 자정에 고정한 날짜값"으로
  // 환산해 날짜-단위로만 빼면 서버 타임존과 무관하게 정확. (이전엔 d 에 +09:00 을 넣고
  // 다시 -9h 를 빼 오프셋을 이중 적용 → UTC 서버 자정 부근에서 하루 어긋났음)
  const sale = Date.parse(saleDate + "T00:00:00Z");
  if (isNaN(sale)) return null;
  const nowKst = new Date(Date.now() + 9 * 3600 * 1000); // KST 벽시계
  const todayKst = Date.UTC(
    nowKst.getUTCFullYear(),
    nowKst.getUTCMonth(),
    nowKst.getUTCDate(),
  );
  return Math.round((sale - todayKst) / (24 * 3600 * 1000));
}

export function fmtDDay(n: number | null): string {
  if (n == null) return "";
  if (n < 0) return `D+${-n}`;
  if (n === 0) return "D-day";
  return `D-${n}`;
}

// 매각가율 (최저가/감정가 %)
export function priceRate(min: number | null | undefined, base: number | null | undefined): number | null {
  if (!min || !base || base === 0) return null;
  return Math.round((min / base) * 100);
}

// courtauction.go.kr 사건 상세 deeplink (사건번호 검색 결과 페이지)
// 정확한 hash 패턴이 사이트 변경 가능성 있어, 가장 안정적인 검색 형태로 생성
export function courtauctionLink(courtCode: string, caseNo: string): string {
  // 형식: index.on?device=pc#/PGJ15BM01?cortOfcCd=...&csNo=...
  // 검증 안 됐을 시 사용자가 수동 검색하도록 폴백 제공
  const params = new URLSearchParams({
    cortOfcCd: courtCode,
    csNo: caseNo,
    pgmId: "PGJ15BM01",
  });
  return `https://www.courtauction.go.kr/pgj/index.on?device=pc#/PGJ15BM01?${params.toString()}`;
}
