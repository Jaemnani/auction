// 인수액 계산 결과 로컬 저장 — 상세 계산기가 쓰고, 지도 팝업이 읽는다.
//
// 명세서(임차인 보증금·전입일·확정일자)는 법원 API 가 제공하지 않고 자동 수집도
// 봇 차단으로 불가(docs/api_recon.md "매각물건명세서" 참조). 따라서 인수액의
// 유일한 소스는 사용자가 명세서를 보고 계산기에 입력해 산출한 값이다.
// 계정 기능이 없으므로 localStorage 에 브라우저-로컬로 보관한다.

const KEY = "auction.assumption.v1";

export type AssumptionRecord = {
  /** 인수액 (원) — 0 이면 "인수 없음"이 확인된 것 (대항력 없음 등) */
  assumed: number;
  /** 그 인수액을 산출한 기준 낙찰가 (원) */
  bid: number;
  /** 대항력 판정 — null 은 판정 불가(보수적으로 인수 있음 계산) */
  opposable: boolean | null;
  /** 저장 시각 ISO */
  savedAt: string;
};

type Store = Record<string, AssumptionRecord>;

function readAll(): Store {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    return parsed && typeof parsed === "object" ? (parsed as Store) : {};
  } catch {
    return {};   // JSON 손상/차단 등 — 저장 없음으로 degrade
  }
}

function writeAll(s: Store): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* quota 초과·프라이빗 모드 — 저장 실패는 무시 (표시만 안 될 뿐) */
  }
  bump();
}

// ---------- 구독 (useSyncExternalStore) ----------
// 저장 시점에 상세 계산기·지도가 함께 갱신되도록 버전 카운터를 노출.
// 스냅샷이 숫자라 참조 안정성 문제 없음. 서버 스냅샷 -1 → hydration 후 0 으로
// 전환되며 클라이언트 값으로 재렌더 (SSR 불일치 없음).
let version = 0;
const listeners = new Set<() => void>();

function bump(): void {
  version += 1;
  for (const l of listeners) l();
}

export function subscribeAssumptions(cb: () => void): () => void {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => { if (e.key === KEY) bump(); };  // 다른 탭
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", onStorage);
  };
}

export const getAssumptionsVersion = (): number => version;
/** 서버/hydration 스냅샷 — 음수면 아직 localStorage 를 읽지 않은 상태 */
export const getAssumptionsVersionServer = (): number => -1;

export function getAssumption(propertyId: string): AssumptionRecord | null {
  return readAll()[propertyId] ?? null;
}

/** 지도 팝업용 — 여러 매물 한 번에 (localStorage 읽기 1회). */
export function getAssumptions(propertyIds: string[]): Record<string, AssumptionRecord> {
  const all = readAll();
  const out: Record<string, AssumptionRecord> = {};
  for (const id of propertyIds) {
    const r = all[id];
    if (r) out[id] = r;
  }
  return out;
}

export function saveAssumption(
  propertyId: string, rec: Omit<AssumptionRecord, "savedAt">,
): void {
  const all = readAll();
  all[propertyId] = { ...rec, savedAt: new Date().toISOString() };
  writeAll(all);
}

export function clearAssumption(propertyId: string): void {
  const all = readAll();
  delete all[propertyId];
  writeAll(all);
}
