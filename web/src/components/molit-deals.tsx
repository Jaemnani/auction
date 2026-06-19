"use client";

import { useEffect, useState } from "react";
import { fmtMoney } from "@/lib/format";
import { formatArea, useAreaUnit } from "@/lib/area-unit";

// API route(/api/molit-deals)가 정규화해 내려주는 형태 — RTMSDataSvc 영문 필드를
// 유형 무관 형태로 매핑한 결과. (route.ts normalizeDeal 참조)
type Deal = {
  name: string;
  umd: string;
  jibun: string;
  year: string;
  month: string;
  day: string;
  amountManwon: number | null;
  area: number | null;
  floor: string | null;
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
      // 6개월 병렬 요청 — 이전 직렬 (for-await) 패턴은 6× latency 누적.
      // allSettled로 부분 실패 허용 (한 월 API 장애도 다른 월 결과는 표시).
      const results = await Promise.allSettled(
        months.map((ym) =>
          fetch(`/api/molit-deals?type=${active}&lawd_cd=${lawdCd}&deal_ymd=${ym}&num_of_rows=30`)
            .then((r) => (r.ok ? r.json() : null))
        ),
      );
      if (cancel) return;
      const collected: Deal[] = [];
      for (const r of results) {
        if (r.status === "fulfilled" && r.value && Array.isArray(r.value.items)) {
          collected.push(...r.value.items);
        }
      }
      setDeals(collected.slice(0, 20));
      setLoading(false);
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
              "rounded px-2 py-0.5 text-caption-sm border " +
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
                const date = d.year
                  ? `${d.year}.${String(d.month).padStart(2, "0")}.${String(d.day).padStart(2, "0")}`
                  : "-";
                return (
                  <tr key={i} className="border-b last:border-0">
                    <td className="py-1">{d.name || d.umd || "-"}</td>
                    <td className="py-1">{date}</td>
                    <td className="py-1 text-right font-mono">
                      {d.amountManwon ? fmtMoney(d.amountManwon * 10000) : "-"}
                    </td>
                    <td className="py-1 text-right">{d.area != null ? formatArea(d.area, unit) : "-"}</td>
                    <td className="py-1 text-right">{d.floor ?? "-"}</td>
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
