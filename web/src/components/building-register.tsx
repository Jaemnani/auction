"use client";

import { useEffect, useState } from "react";

type Title = {
  name: string; mainPurpose: string; etcPurpose: string; structure: string;
  useApprovalDay: string; groundFloors: string; undergroundFloors: string;
  totalArea: string; archArea: string; platArea: string; bcRat: string; vlRat: string;
  households: string; families: string; hoCnt: string; height: string;
  regKind: string; regGb: string; platPlc: string;
  raw: Record<string, unknown>;
};

type Props = {
  sdCode: string | null;
  sggCode: string | null;
  emdCode: string | null;
  /** 지번 (예: "147" 또는 "127-47") */
  lotNo: string | null;
  /** 산 지번 여부 (lot_addr에 '산' 포함) */
  isMountain?: boolean;
};

const pad4 = (s: string) => s.padStart(4, "0");
const fmtYmd = (s: string) =>
  /^\d{8}$/.test(s) ? `${s.slice(0, 4)}.${s.slice(4, 6)}.${s.slice(6, 8)}` : s || "-";

export function BuildingRegister({ sdCode, sggCode, emdCode, lotNo, isMountain }: Props) {
  const [titles, setTitles] = useState<Title[] | null>(null);
  const [loading, setLoading] = useState(false);

  // 파라미터 도출 — 동(읍면동) 주소는 ri=00 가정으로 동작, 리 주소는 부정확할 수 있음.
  const sigunguCd = sdCode && sggCode ? `${sdCode}${sggCode}` : null;
  const bjdongCd = emdCode ? `${emdCode}00` : null;
  const m = lotNo ? lotNo.match(/^(\d+)(?:-(\d+))?/) : null;
  const bun = m ? pad4(m[1]) : null;
  const ji = m ? pad4(m[2] ?? "0") : "0000";
  const ready = !!(sigunguCd && bjdongCd && bun);

  useEffect(() => {
    if (!ready) return;
    let cancel = false;
    setLoading(true);
    const qs = new URLSearchParams({
      sigungu_cd: sigunguCd!, bjdong_cd: bjdongCd!, bun: bun!, ji,
      plat_gb_cd: isMountain ? "1" : "0",
    });
    fetch(`/api/building-register?${qs}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (!cancel) setTitles(d?.items ?? []); })
      .catch(() => { if (!cancel) setTitles([]); })
      .finally(() => { if (!cancel) setLoading(false); });
    return () => { cancel = true; };
  }, [ready, sigunguCd, bjdongCd, bun, ji, isMountain]);

  if (!ready) return null;
  if (loading) return <div className="text-sm text-muted-foreground">건축물대장 불러오는 중…</div>;
  if (!titles || titles.length === 0) {
    return <div className="text-sm text-muted-foreground">건축물대장 정보 없음 (지번 매칭 실패 가능)</div>;
  }

  // 표제부 첫 항목(총괄/대표) 요약
  const t = titles[0];
  const rows = ([
    ["건물명", t.name],
    ["주용도", [t.mainPurpose, t.etcPurpose].filter(Boolean).join(" / ")],
    ["구조", t.structure],
    ["사용승인일", fmtYmd(t.useApprovalDay)],
    ["층수", [t.groundFloors && `지상 ${t.groundFloors}`, t.undergroundFloors && `지하 ${t.undergroundFloors}`].filter(Boolean).join(" · ")],
    ["연면적", t.totalArea && `${t.totalArea}㎡`],
    ["건축면적", t.archArea && `${t.archArea}㎡`],
    ["대지면적", t.platArea && `${t.platArea}㎡`],
    ["건폐율 / 용적률", [t.bcRat && `${t.bcRat}%`, t.vlRat && `${t.vlRat}%`].filter(Boolean).join(" / ")],
    ["세대/가구/호", [t.households && `${t.households}세대`, t.families && `${t.families}가구`, t.hoCnt && `${t.hoCnt}호`].filter(Boolean).join(" · ")],
    ["대장구분", [t.regKind, t.regGb].filter(Boolean).join(" / ")],
  ] as Array<[string, string]>).filter(([, v]) => v && String(v).trim());

  return (
    <div className="space-y-2 text-sm">
      <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1">
        {rows.map(([k, v]) => (
          <div key={k} className="flex gap-3 border-b last:border-0 py-1">
            <dt className="text-muted-foreground w-28 shrink-0">{k}</dt>
            <dd className="break-words">{v}</dd>
          </div>
        ))}
      </dl>
      {titles.length > 1 && (
        <div className="text-caption-xs text-muted-foreground">표제부 {titles.length}건 중 대표 1건 표시</div>
      )}
      <div className="text-caption-xs text-muted-foreground">출처: 건축HUB 건축물대장 (국토교통부)</div>
    </div>
  );
}
