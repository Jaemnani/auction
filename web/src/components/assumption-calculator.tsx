"use client";

import { useMemo, useState, useSyncExternalStore } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { fmtMoney, fmtDate } from "@/lib/format";
import {
  hasOpposability, simulate, scenarioBids, estimateAuctionCost,
  type AssumptionInputs,
} from "@/lib/assumption";
import {
  getAssumption, saveAssumption, clearAssumption, subscribeAssumptions,
  getAssumptionsVersion, getAssumptionsVersionServer, type AssumptionRecord,
} from "@/lib/assumption-store";

/**
 * 인수액 계산기 (대항력 임차인) — 매각물건명세서 값을 입력하면 낙찰가별
 * 배당액·인수액·실질 취득원가 표를 계산.
 *
 * 자동 프리필: 말소기준권리 후보 일자(등기 최선순위 설정), 낙찰가 축(최저가~감정가).
 * 임차인 보증금·전입일·확정일자·배당요구는 법원 API 가 제공하지 않아
 * 매각물건명세서 PDF(공식 사이트)에서 확인 후 입력해야 한다.
 */
export function AssumptionCalculator({
  propertyId, appraisal, minPrice, lienDate, lienType, demandDeadline, officialUrl,
}: {
  /** 계산 결과를 로컬 저장할 키 — 지도 팝업이 같은 키로 읽는다 */
  propertyId: string;
  appraisal: number | null;
  minPrice: number | null;
  /** 말소기준권리 후보 일자 (YYYY-MM-DD) — parsePrimaryLien */
  lienDate: string | null;
  lienType: string | null;
  /** 배당요구종기 (YYYY-MM-DD) */
  demandDeadline: string | null;
  officialUrl: string | null;
}) {
  const [open, setOpen] = useState(false);

  // 입력 — 금액은 만원 단위 문자열 (빈 값 허용)
  const [depositMan, setDepositMan] = useState("");
  const [moveIn, setMoveIn] = useState("");
  const [noFixed, setNoFixed] = useState(false);
  const [fixed, setFixed] = useState("");
  const [demandFiled, setDemandFiled] = useState(true);
  const [lien, setLien] = useState(lienDate ?? "");
  const [seniorMan, setSeniorMan] = useState("");
  const [taxMan, setTaxMan] = useState("");
  const [smallMan, setSmallMan] = useState("");
  const [costMan, setCostMan] = useState("");
  const [customBidMan, setCustomBidMan] = useState("");

  const man = (s: string): number => {
    const n = Number(s.replace(/[^\d.]/g, ""));
    return Number.isFinite(n) && n > 0 ? Math.round(n * 10_000) : 0;
  };

  const deposit = man(depositMan);
  const inputs: AssumptionInputs = useMemo(() => ({
    deposit,
    moveInDate: moveIn || null,
    fixedDate: noFixed ? null : (fixed || null),
    demandFiled,
    lienDate: lien || null,
    seniorDebt: man(seniorMan),
    taxPriority: man(taxMan),
    smallPriority: man(smallMan),
    costOverride: costMan ? man(costMan) : null,
  }), [deposit, moveIn, noFixed, fixed, demandFiled, lien, seniorMan, taxMan, smallMan, costMan]);

  const opposable = hasOpposability(inputs.moveInDate, inputs.lienDate);
  const bids = useMemo(() => {
    const base = scenarioBids(minPrice, appraisal);
    const custom = man(customBidMan);
    if (custom > 0 && !base.includes(custom)) {
      return [...base, custom].sort((a, b) => a - b);
    }
    return base;
  }, [minPrice, appraisal, customBidMan]);

  const rows = useMemo(
    () => (deposit > 0 ? bids.map((b) => simulate(inputs, b)) : []),
    [inputs, bids, deposit],
  );

  // 저장 대상 행 — 내 입찰가를 넣었으면 그 행, 아니면 최저가(첫 행).
  const customBid = man(customBidMan);
  const baseRow = rows.find((r) => customBid > 0 && r.bid === customBid) ?? rows[0] ?? null;

  // 저장된 값 (지도 팝업이 읽는 것과 동일 소스). 버전 구독이라 저장·다른 탭 변경에 반응.
  const version = useSyncExternalStore(
    subscribeAssumptions, getAssumptionsVersion, getAssumptionsVersionServer,
  );
  const saved: AssumptionRecord | null = useMemo(
    () => (version < 0 ? null : getAssumption(propertyId)),
    [propertyId, version],
  );

  const doSave = () => {
    if (!baseRow) return;
    saveAssumption(propertyId, { assumed: baseRow.assumed, bid: baseRow.bid, opposable });
  };
  const doClear = () => clearAssumption(propertyId);

  const inputCls =
    "w-full rounded-md border bg-background px-2 py-1 text-sm";

  return (
    <Card>
      <CardHeader className="pb-2">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex w-full items-center justify-between text-left"
        >
          <CardTitle className="text-base">
            인수액 계산기 <span className="text-muted-foreground font-normal text-sm">— 대항력 임차인 보증금 (베타)</span>
          </CardTitle>
          <span className="text-muted-foreground" aria-hidden>{open ? "▾" : "▸"}</span>
        </button>
      </CardHeader>
      {open && (
        <CardContent className="space-y-4 text-sm">
          <div className="rounded-md bg-muted/50 p-3 text-xs space-y-1">
            <div>
              <strong>매각물건명세서</strong>에서 임차인의 <strong>전입일·확정일자·보증금·배당요구 여부</strong>를
              확인해 입력하세요 — 인수 여부의 8할은 명세서가 결정합니다.
              {officialUrl && (
                <>
                  {" "}
                  <a href={officialUrl} target="_blank" rel="noopener noreferrer"
                     className="text-blue-600 hover:underline">
                    공식 사이트에서 명세서 보기 ↗
                  </a>
                </>
              )}
            </div>
            {demandDeadline && (
              <div className="text-muted-foreground">
                배당요구종기: <strong>{fmtDate(demandDeadline)}</strong> — 이 날짜까지 배당요구한 임차인만 배당 참여
              </div>
            )}
            {lienDate && (
              <div className="text-muted-foreground">
                말소기준권리 후보(자동): <strong>{fmtDate(lienDate)}</strong> {lienType ?? ""} — 등기부로 확인 후 필요 시 수정
              </div>
            )}
          </div>

          {/* 입력 그리드 */}
          <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-3">
            <label className="space-y-1">
              <div className="text-xs text-muted-foreground">임차인 보증금 (만원) *</div>
              <input inputMode="numeric" value={depositMan}
                     onChange={(e) => setDepositMan(e.target.value)}
                     placeholder="예: 30000 (3억)" className={inputCls} />
            </label>
            <label className="space-y-1">
              <div className="text-xs text-muted-foreground">전입일</div>
              <input type="date" value={moveIn}
                     onChange={(e) => setMoveIn(e.target.value)} className={inputCls} />
            </label>
            <label className="space-y-1">
              <div className="text-xs text-muted-foreground">말소기준권리 설정일</div>
              <input type="date" value={lien}
                     onChange={(e) => setLien(e.target.value)} className={inputCls} />
            </label>
            <label className="space-y-1">
              <div className="text-xs text-muted-foreground">확정일자</div>
              <input type="date" value={fixed} disabled={noFixed}
                     onChange={(e) => setFixed(e.target.value)}
                     className={inputCls + (noFixed ? " opacity-40" : "")} />
              <div className="flex items-center gap-1 text-xs">
                <input type="checkbox" id="nofixed" checked={noFixed}
                       onChange={(e) => setNoFixed(e.target.checked)} />
                <label htmlFor="nofixed" className="cursor-pointer">확정일자 없음</label>
              </div>
            </label>
            <label className="space-y-1">
              <div className="text-xs text-muted-foreground">배당요구</div>
              <div className="flex items-center gap-1 pt-1.5">
                <input type="checkbox" id="demand" checked={demandFiled}
                       onChange={(e) => setDemandFiled(e.target.checked)} />
                <label htmlFor="demand" className="cursor-pointer text-sm">종기 내 배당요구 함</label>
              </div>
            </label>
            <label className="space-y-1">
              <div className="text-xs text-muted-foreground">선순위 채권액 (만원)</div>
              <input inputMode="numeric" value={seniorMan}
                     onChange={(e) => setSeniorMan(e.target.value)}
                     placeholder="등기 채권최고액" className={inputCls} />
            </label>
            <label className="space-y-1">
              <div className="text-xs text-muted-foreground">당해세 등 우선 조세 (만원)</div>
              <input inputMode="numeric" value={taxMan}
                     onChange={(e) => setTaxMan(e.target.value)}
                     placeholder="미상이면 0" className={inputCls} />
            </label>
            <label className="space-y-1">
              <div className="text-xs text-muted-foreground">소액 최우선변제 (만원)</div>
              <input inputMode="numeric" value={smallMan}
                     onChange={(e) => setSmallMan(e.target.value)}
                     placeholder="해당 없으면 0" className={inputCls} />
            </label>
            <label className="space-y-1">
              <div className="text-xs text-muted-foreground">경매비용 (만원)</div>
              <input inputMode="numeric" value={costMan}
                     onChange={(e) => setCostMan(e.target.value)}
                     placeholder={`자동 (${Math.round(estimateAuctionCost(minPrice ?? appraisal ?? 0) / 10_000).toLocaleString()})`}
                     className={inputCls} />
            </label>
            <label className="space-y-1">
              <div className="text-xs text-muted-foreground">내 입찰가 추가 (만원)</div>
              <input inputMode="numeric" value={customBidMan}
                     onChange={(e) => setCustomBidMan(e.target.value)}
                     placeholder="표에 행 추가" className={inputCls} />
            </label>
          </div>

          {/* 대항력 판정 */}
          <div className="flex flex-wrap items-center gap-2">
            {opposable === true && (
              <Badge variant="outline" className="bg-red-100 text-red-900 border-red-300">
                대항력 있음 — 배당 못 받는 보증금은 낙찰자 인수
              </Badge>
            )}
            {opposable === false && (
              <Badge variant="outline" className="bg-green-50 text-green-900 border-green-300">
                대항력 없음 (전입이 말소기준권리보다 늦음) — 인수액 0
              </Badge>
            )}
            {opposable === null && (
              <Badge variant="outline" className="bg-amber-100 text-amber-900 border-amber-300">
                전입일·말소기준일 입력 시 대항력 자동 판정 (미입력 시 인수 있음으로 보수 계산)
              </Badge>
            )}
            {opposable !== false && !noFixed && !fixed && deposit > 0 && (
              <span className="text-xs text-red-700">
                ⚠ 확정일자 미입력 — &lsquo;없음&rsquo;이 맞다면 배당 0 → 보증금 전액 인수 (최악 케이스)
              </span>
            )}
            {opposable !== false && !demandFiled && deposit > 0 && (
              <span className="text-xs text-red-700">
                ⚠ 배당요구 안 함 — 배당 0 → 보증금 전액 인수 + 임차인 계속 거주 가능
              </span>
            )}
          </div>

          {/* 낙찰가별 표 */}
          {rows.length > 0 ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-right">낙찰가</TableHead>
                    <TableHead className="text-right">임차인 배당액</TableHead>
                    <TableHead className="text-right">인수액</TableHead>
                    <TableHead className="text-right">실질 취득원가</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((r) => (
                    <TableRow key={r.bid}
                              className={baseRow && r.bid === baseRow.bid ? "bg-muted/50" : ""}>
                      <TableCell className="text-right tabular-nums">
                        {fmtMoney(r.bid)}
                        {baseRow && r.bid === baseRow.bid && (
                          <span className="ml-1.5 text-caption-xs text-muted-foreground">기준</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">
                        {fmtMoney(r.dividend)}
                      </TableCell>
                      <TableCell className={"text-right tabular-nums font-semibold " +
                        (r.assumed > 0 ? "text-red-600" : "text-green-700")}>
                        {fmtMoney(r.assumed)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums font-bold">
                        {fmtMoney(r.effective)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              {/* 저장 — 지도 팝업이 이 값을 읽는다 (localStorage, 이 브라우저 한정) */}
              <div className="flex flex-wrap items-center gap-2 pt-3 text-xs">
                <button
                  type="button"
                  onClick={doSave}
                  disabled={!baseRow}
                  className="rounded-md border bg-primary text-primary-foreground px-3 py-1.5 font-medium disabled:opacity-50"
                >
                  기준 인수액을 지도에 표시
                </button>
                {saved && (
                  <>
                    <span className="text-muted-foreground">
                      저장됨: <strong className={saved.assumed > 0 ? "text-red-600" : "text-green-700"}>
                        {fmtMoney(saved.assumed)}
                      </strong> (낙찰가 {fmtMoney(saved.bid)} 기준)
                    </span>
                    <button type="button" onClick={doClear}
                            className="text-muted-foreground underline hover:text-foreground">
                      지우기
                    </button>
                  </>
                )}
                <span className="text-caption-xs text-muted-foreground w-full">
                  이 브라우저에만 저장됩니다 (계정 없음). 지도 팝업의 인수액 줄로 표시되고,
                  저장 안 한 매물은 그 줄이 비워집니다.
                </span>
              </div>
            </div>
          ) : (
            <div className="text-xs text-muted-foreground">
              보증금을 입력하면 낙찰가별(최저가~감정가) 배당액·인수액·실질 취득원가 표가 표시됩니다.
            </div>
          )}

          <div className="text-caption-xs text-muted-foreground border-t pt-2">
            단순화 모델(경매비용 추정 · 당해세/소액변제 수동 입력 · 다수 임차인/임금채권/조세
            법정기일 미반영)이라 공식 배당표와 다를 수 있습니다. 최종 판단 전 매각물건명세서·
            등기부등본·전입세대확인서 원본을 반드시 확인하세요.
          </div>
        </CardContent>
      )}
    </Card>
  );
}
