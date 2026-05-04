"use client";

import { useEffect, useState } from "react";
import { fmtMoney } from "@/lib/format";
import { formatArea, useAreaUnit } from "@/lib/area-unit";

type Deal = {
  거래금액?: string;
  거래유형?: string;
  법정동?: string;
  아파트?: string;
  단지명?: string;
  연?: string | number;
  월?: string | number;
  일?: string | number;
  전용면적?: string | number;
  층?: string | number;
  [k: string]: unknown;
};

export type MolitType =
  | "apt" | "apt_dev" | "apt_resale"
  | "rh" | "sh" | "offi" | "land" | "nrg" | "indu";

type Props = {
  /** 시·군·구 코드 5자리 (예: 11680 강남구) — sd_code + sgg_code */
  lawdCd: string | null;
  /** 매물 유형 — 용도(대/중)에서 자동 추론 */
  type?: MolitType;
};

const TYPE_LABELS: Record<MolitType, string> = {
  apt: "아파트", apt_dev: "아파트 상세", apt_resale: "아파트 분양권",
  rh: "연립/다세대", sh: "단독/다가구", offi: "오피스텔",
  land: "토지", nrg: "상업업무용", indu: "공장/창고",
};

export function MolitDeals({ lawdCd, type = "apt" }: Props) {
  const { unit } = useAreaUnit();
  const [active, setActive] = useState<MolitType>(type);
  const [deals, setDeals] = useState<Deal[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { setActive(type); }, [type]);

  useEffect(() => {
    if (!lawdCd) return;
    setLoading(true); setErr(null);
    const now = new Date();
    const months = Array.from({ length: 6 }, (_, i) => {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}`;
    });

    let cancel = false;
    (async () => {
      const collected: Deal[] = [];
      for (const ym of months) {
        if (cancel) return;
        try {
          const r = await fetch(`/api/molit-deals?type=${active}&lawd_cd=${lawdCd}&deal_ymd=${ym}&num_of_rows=30`);
          if (!r.ok) continue;
          const j = await r.json();
          if (Array.isArray(j.items)) collected.push(...j.items);
          if (collected.length >= 20) break;
        } catch { /* skip */ }
      }
      if (!cancel) {
        setDeals(collected.slice(0, 20));
        setLoading(false);
      }
    })();
    return () => { cancel = true; };
  }, [lawdCd, active]);

  if (!lawdCd) return null;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1">
        {(Object.keys(TYPE_LABELS) as MolitType[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setActive(t)}
            className={
              "rounded px-2 py-0.5 text-[11px] border " +
              (t === active
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-background hover:bg-muted text-muted-foreground")
            }
          >{TYPE_LABELS[t]}</button>
        ))}
      </div>
      <div className="text-xs text-muted-foreground">
        법정동 {lawdCd} · 최근 6개월 · {TYPE_LABELS[active]}
      </div>
      {loading && <div className="text-sm text-muted-foreground">불러오는 중…</div>}
      {err && <div className="text-sm text-red-600">{err}</div>}
      {!loading && deals && deals.length === 0 && (
        <div className="text-sm text-muted-foreground">최근 6개월 거래 없음 또는 유형 불일치</div>
      )}
      {deals && deals.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-muted-foreground">
              <tr className="border-b">
                <th className="text-left py-1">단지/주소</th>
                <th className="text-left py-1">계약일</th>
                <th className="text-right py-1">금액</th>
                <th className="text-right py-1">면적</th>
                <th className="text-right py-1">층</th>
              </tr>
            </thead>
            <tbody>
              {deals.map((d, i) => {
                const won = parseInt(String(d.거래금액 ?? "").replace(/[\s,]/g, ""), 10);
                const date = `${d.연}.${String(d.월).padStart(2, "0")}.${String(d.일).padStart(2, "0")}`;
                return (
                  <tr key={i} className="border-b last:border-0">
                    <td className="py-1">{String(d.아파트 ?? d.단지명 ?? d.법정동 ?? "")}</td>
                    <td className="py-1">{date}</td>
                    <td className="py-1 text-right font-mono">{won ? fmtMoney(won * 10000) : "-"}</td>
                    <td className="py-1 text-right">{formatArea(d.전용면적, unit)}</td>
                    <td className="py-1 text-right">{d.층 ?? "-"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
