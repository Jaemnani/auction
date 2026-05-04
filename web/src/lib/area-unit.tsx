"use client";

import { createContext, useContext, useEffect, useState } from "react";

export type AreaUnit = "sqm" | "pyeong";

// 1평 = 3.305785㎡ (정확히는 3.3057851239669...)
const SQM_PER_PYEONG = 3.305785;

const STORAGE_KEY = "areaUnit";

const Ctx = createContext<{
  unit: AreaUnit;
  setUnit: (u: AreaUnit) => void;
  toggle: () => void;
}>({
  unit: "sqm",
  setUnit: () => {},
  toggle: () => {},
});

export function AreaUnitProvider({ children }: { children: React.ReactNode }) {
  const [unit, setUnitState] = useState<AreaUnit>("sqm");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY) as AreaUnit | null;
      if (saved === "pyeong" || saved === "sqm") setUnitState(saved);
    } catch { /* ignore */ }
    setHydrated(true);
  }, []);

  const setUnit = (u: AreaUnit) => {
    setUnitState(u);
    try { localStorage.setItem(STORAGE_KEY, u); } catch { /* ignore */ }
  };
  const toggle = () => setUnit(unit === "sqm" ? "pyeong" : "sqm");

  return (
    <Ctx.Provider value={{ unit, setUnit, toggle }}>
      {/* hydration mismatch 방지 — ㎡로 SSR 후 client에서 단위 적용 */}
      <span style={{ display: "contents" }} suppressHydrationWarning>
        {hydrated ? children : children}
      </span>
    </Ctx.Provider>
  );
}

export function useAreaUnit() {
  return useContext(Ctx);
}

/** 텍스트 안 "N㎡" 패턴을 단위에 맞게 치환. sqm이면 그대로. */
export function convertAreaText(
  text: string | null | undefined, unit: AreaUnit,
): string {
  if (!text) return "";
  if (unit === "sqm") return text;
  return text.replace(
    /(\d+(?:[.,]\d+)?)\s*㎡/g,
    (_, n: string) => {
      const sqm = parseFloat(n.replace(/,/g, ""));
      if (isNaN(sqm)) return _;
      const py = sqm / SQM_PER_PYEONG;
      return `${py.toFixed(2)}평`;
    },
  );
}

/** 숫자 ㎡ 값을 단위에 맞게 표기. */
export function formatArea(
  sqm: number | string | null | undefined, unit: AreaUnit,
): string {
  if (sqm == null || sqm === "") return "-";
  const n = typeof sqm === "number" ? sqm : parseFloat(String(sqm));
  if (isNaN(n)) return "-";
  if (unit === "sqm") return `${n}㎡`;
  return `${(n / SQM_PER_PYEONG).toFixed(2)}평`;
}
