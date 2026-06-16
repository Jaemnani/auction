import { notFound } from "next/navigation";
import nextDynamic from "next/dynamic";
import { fetchCodeNames, fetchProperty, fetchRegionStats, photoPublicUrl } from "@/lib/queries";

// MolitDeals — 클라이언트 fetch 컴포넌트. 청크 분리로 초기 JS 페이로드 축소.
const MolitDeals = nextDynamic(() => import("@/components/molit-deals").then((m) => ({ default: m.MolitDeals })));
import { fmtDate, fmtMoney, fmtDiscount, fmtPercent } from "@/lib/format";
import {
  parseRiskFlags, parseDposRate, parsePrimaryLien,
  parseCaseStatus, dDay, fmtDDay, courtauctionLink,
} from "@/lib/analysis";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { PropertyPhotos } from "@/components/property-photos";
import { PropertyLocation } from "@/components/property-location";
import { AreaText } from "@/components/area-text";
import { ExportButtons } from "@/components/export-buttons";
import { buildKrMarkdown } from "@/lib/kr-markdown";

// detail 페이지는 params(docid) 기반 단건 — ISR로 동시 방문 시 캐시 hit.
// cron이 매일 04:00 갱신하므로 1시간 revalidate가 적절 (지난 캐시 최대 60분).
export const revalidate = 3600;

export default async function PropertyDetail(props: PageProps<"/p/[docid]">) {
  const { docid: rawDocid } = await props.params;
  const docid = decodeURIComponent(rawDocid);
  const p = await fetchProperty(docid);
  if (!p) notFound();

  const cs = p.cases;
  const detail = (p.detail_result ?? {}) as Record<string, unknown>;
  const csBase = (detail.csBaseInfo ?? {}) as Record<string, unknown>;
  const dxdy = (detail.dspslGdsDxdyInfo ?? {}) as Record<string, unknown>;
  const aeeWevl = (detail.aeeWevlMnpntLst ?? []) as Array<Record<string, unknown>>;

  // 코드 이름 매핑.
  // sgg는 sd+code 페어로 정확히 lookup (단순 code 매칭 시 동명 코드 충돌:
  // 예 code=650 → sd=11이면 서초구, sd=41이면 포천시).
  const codes = [
    p.usage_lcl_cd, p.usage_mcl_cd, p.usage_scl_cd,
    p.sd_code, cs?.court_code,
  ].filter((c): c is string => !!c);
  const sggPairs = (p.sd_code && p.sgg_code)
    ? [{ sd_code: p.sd_code, sgg_code: p.sgg_code }]
    : [];
  const names = await fetchCodeNames(codes, sggPairs);

  // 사진 정렬 + URL 변환
  const photos = (p.property_photos ?? [])
    .filter((ph) => !!ph.storage_path)
    .sort((a, b) => a.seq - b.seq)
    .map((ph) => ({
      seq: ph.seq,
      kind: ph.photo_kind_name ?? ph.photo_kind_cd ?? "",
      desc: ph.description ?? "",
      url: photoPublicUrl(ph.storage_path!),
    }));

  // 가격 비율
  const pricePct = p.appraisal_amount && p.min_sale_price
    ? Math.round((p.min_sale_price / p.appraisal_amount) * 100)
    : null;

  // 용도 표기 (대 > 중 > 소)
  const usageParts = [p.usage_lcl_cd, p.usage_mcl_cd, p.usage_scl_cd]
    .map((c) => c && names[c]).filter(Boolean);
  const usageLabel = usageParts.length > 0 ? usageParts.join(" › ") : "-";

  // 주소 (시·도 + 시·군·구) + 표시 주소
  const sdName = p.sd_code ? names[p.sd_code] : null;
  const sggName = p.sgg_code ? names[p.sgg_code] : null;
  const regionParts = [sdName, sggName].filter(Boolean).join(" ");

  // 사건 정보
  const courtName = cs?.courts?.name ?? (cs?.court_code ? names[cs.court_code] : null);
  const dept = cs?.jdbn_name ?? "";
  const courtPlusDept = [courtName, dept].filter(Boolean).join(" · ");

  // Markdown export
  const markdown = buildKrMarkdown(p, names, photos.map((ph) => ph.url));
  const mdFilename = `auction_${(cs?.case_no ?? p.docid ?? "kr")
    .replace(/[^\w\-]+/g, "_")
    .slice(0, 80)}`;

  return (
    <div className="space-y-6">
      {/* 헤더 */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-sm text-muted-foreground">
            {courtPlusDept || "-"}
          </div>
          <h1 className="text-2xl font-bold">
            {cs?.case_no} {p.maemul_ser > 1 && <span className="text-muted-foreground">#{p.maemul_ser}</span>}
          </h1>
        <div className="mt-1 text-sm">
          {/* 주소 우선순위: 도로명 > 지번 > 행정구역. conv_addr은 '[집합건물…㎡]' 같은
              구조 설명이라 주소가 아니므로 주소 줄에 쓰지 않는다 (아래 별도 표시). */}
          {p.road_addr ? (
            <span className="font-medium">{p.road_addr}</span>
          ) : p.lot_addr ? (
            <span className="font-medium">{p.lot_addr}</span>
          ) : regionParts ? (
            <span className="font-medium">{regionParts}</span>
          ) : (
            <span className="text-muted-foreground">주소 정보 없음</span>
          )}
        </div>
        {p.road_addr && p.lot_addr && p.lot_addr !== p.road_addr && (
          <div className="text-xs text-muted-foreground mt-0.5">지번 {p.lot_addr}</div>
        )}
        {p.conv_addr && (
          <div className="text-xs text-muted-foreground mt-0.5">
            <AreaText>{p.conv_addr}</AreaText>
          </div>
        )}
        </div>
        <ExportButtons markdown={markdown} filename={mdFilename} />
      </div>

      {/* 권리분석 요약 카드 — 입찰 전 필독 */}
      <PropertyRiskCard p={p} />

      {/* 사진 그리드 */}
      {photos.length > 0 && <PropertyPhotos photos={photos} />}

      {/* 핵심 지표 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="감정가" value={fmtMoney(p.appraisal_amount)} />
        <Stat
          label="최저매각가"
          value={fmtMoney(p.min_sale_price)}
          sub={pricePct != null ? `감정가의 ${pricePct}%` : undefined}
          highlight
        />
        <Stat
          label="유찰"
          value={p.fail_count != null ? `${p.fail_count}회` : "-"}
          sub={fmtDiscount(p.min_sale_price, p.appraisal_amount) !== "-"
            ? `할인 ${fmtDiscount(p.min_sale_price, p.appraisal_amount).replace("▼", "")}`
            : undefined}
        />
        <Stat label="매각기일" value={fmtDate(p.sale_date)} />
      </div>

      {/* 물건기본내역 */}
      <Card>
        <CardHeader><CardTitle className="text-base">물건기본내역</CardTitle></CardHeader>
        <CardContent>
          <KvGrid
            items={[
              ["사건번호", `${cs?.case_no ?? "-"}${p.maemul_ser > 1 ? ` #${p.maemul_ser}` : ""}`],
              ["사건명", cs?.case_name ?? "-"],
              ["법원·경매계", courtPlusDept || "-"],
              ["접수일", fmtDate(cs?.receipt_date ?? null)],
              ["용도", usageLabel],
              ["주소(행정)", regionParts || "-"],
              ["도로명 주소", p.road_addr ?? "-"],
              ["지번 주소", p.lot_addr ?? "-"],
              ["건물 요약", <AreaText key="b">{p.building_summary ?? "-"}</AreaText>],
              ["면적 요약", <AreaText key="a">{p.area_summary ?? "-"}</AreaText>],
              ["매각결정기일", fmtDate(p.sale_decision_date)],
              ["감정가", fmtMoney(p.appraisal_amount)],
              ["최저매각가", fmtMoney(p.min_sale_price)],
              ["매각가율", fmtPercent(p.min_sale_price, p.appraisal_amount)],
              ["할인율", fmtDiscount(p.min_sale_price, p.appraisal_amount)],
              ["유찰횟수", p.fail_count != null ? `${p.fail_count}회` : "-"],
            ]}
          />
        </CardContent>
      </Card>

      {/* 매각기일 이력 */}
      {p.property_sale_dates?.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-base">매각기일 이력</CardTitle></CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">회차</TableHead>
                  <TableHead>기일</TableHead>
                  <TableHead>장소</TableHead>
                  <TableHead className="text-right">최저가</TableHead>
                  <TableHead>결과</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {p.property_sale_dates
                  .sort((a, b) => a.seq - b.seq)
                  .map((s) => (
                    <TableRow key={s.seq}>
                      <TableCell>{s.seq}</TableCell>
                      <TableCell>{fmtDate(s.sale_date)} {s.hour ?? ""}</TableCell>
                      <TableCell className="text-sm">{s.place ?? "-"}</TableCell>
                      <TableCell className="text-right">{fmtMoney(s.min_price)}</TableCell>
                      <TableCell>
                        {s.result_cd && <Badge variant="outline">{s.result_cd}</Badge>}
                      </TableCell>
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* 감정평가 요항 — 실제 키: aeeWevlMnpntCtt(내용) + aeeWevlMnpntItmCd(항목코드) */}
      {aeeWevl.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-base">감정평가 요항</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-2">
            {aeeWevl.map((item, i) => {
              const itmCd = String(item?.aeeWevlMnpntItmCd ?? "");
              const ctt = String(item?.aeeWevlMnpntCtt ?? "").trim();
              const label = AEE_LABELS[itmCd] ?? `항목 ${itmCd || i + 1}`;
              if (!ctt || ctt === "-." || ctt === "-") return null;
              return (
                <div key={i} className="border-b pb-2 last:border-0">
                  <div className="font-medium">{label}</div>
                  <div className="text-muted-foreground whitespace-pre-wrap">
                    <AreaText>{ctt}</AreaText>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {/* 원본 데이터 (raw) */}
      {(Object.keys(csBase).length > 0 || Object.keys(dxdy).length > 0) && (
        <details>
          <summary className="cursor-pointer text-sm text-muted-foreground py-2">
            원본 응답 키 펼치기
          </summary>
          <div className="space-y-4 mt-2">
            {Object.keys(csBase).length > 0 && (
              <Card>
                <CardHeader><CardTitle className="text-sm">csBaseInfo</CardTitle></CardHeader>
                <CardContent><RawKv obj={csBase} /></CardContent>
              </Card>
            )}
            {Object.keys(dxdy).length > 0 && (
              <Card>
                <CardHeader><CardTitle className="text-sm">dspslGdsDxdyInfo</CardTitle></CardHeader>
                <CardContent><RawKv obj={dxdy} /></CardContent>
              </Card>
            )}
          </div>
        </details>
      )}

      {/* 인근 실거래가 (국토부 OpenAPI) */}
      {p.sd_code && p.sgg_code && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">인근 실거래가 (국토부)</CardTitle>
          </CardHeader>
          <CardContent>
            <MolitDeals
              lawdCd={`${p.sd_code}${p.sgg_code}`}
              type={inferMolitType(p.usage_lcl_cd, p.usage_mcl_cd, p.rmk)}
            />
          </CardContent>
        </Card>
      )}

      {/* 인근 낙찰 통계 — 우리 sale_results 집계 */}
      <NearbyAuctionStats
        sdCode={p.sd_code}
        sggCode={p.sgg_code}
        usageLcl={p.usage_lcl_cd}
        regionLabel={regionParts}
        usageLabel={usageLabel}
        currentRate={pricePct}
      />

      {/* 위치 — 한국 영토 내 좌표일 때만 */}
      {p.longitude != null && p.latitude != null
        && p.longitude >= 124 && p.longitude <= 132.5
        && p.latitude  >= 33  && p.latitude  <= 39 && (
        <Card>
          <CardHeader><CardTitle className="text-base">위치</CardTitle></CardHeader>
          <CardContent>
            <PropertyLocation lng={p.longitude} lat={p.latitude} addr={p.road_addr ?? p.lot_addr} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// 감정평가 요항 항목코드 → 한글 라벨 (한국감정원 표준 16개 항목)
const AEE_LABELS: Record<string, string> = {
  "00083001": "위치 / 인근 환경",
  "00083002": "교통",
  "00083003": "교통",
  "00083004": "주위 환경",
  "00083005": "도로 인접",
  "00083006": "이용 상태",
  "00083007": "공법상 규제",
  "00083008": "이용 상태",
  "00083009": "토지 형상·지세",
  "00083010": "토지 명세",
  "00083011": "도시계획 / 용도지역",
  "00083012": "토지 이용 계획",
  "00083013": "건물 명세",
  "00083014": "건물 명세",
  "00083015": "건물 구조",
  "00083016": "건물 설비",
  "00083017": "부대 설비",
  "00083018": "위반 건축물",
  "00083019": "기타",
  "00083020": "임대 관계",
  "00083021": "임대 관계",
  "00083022": "임대 관계",
  "00083023": "기타 참고사항",
  "00083024": "기타 참고사항",
  "00083025": "임대 관계",
  "00083026": "임대 관계",
  "00083027": "감정평가 의견",
};

// 용도 코드 → MOLIT 실거래가 API 유형 매핑
// courtauction lclsUtilCd (대분류): 10000=토지, 20000=건물, 30000=차량, 40000=기타
// 정확한 mclsUtilCd 매핑은 미해석 → 표준 prefix + dspslGdsRmk 키워드 보조 휴리스틱
import type { MolitType } from "@/components/molit-deals";
function inferMolitType(
  lcl: string | null | undefined,
  mcl: string | null | undefined,
  rmk?: string | null,
): MolitType {
  if (lcl === "10000") return "land";              // 토지
  if (lcl === "30000" || lcl === "40000") return "land";  // 매핑 불가 → 토지로 대체

  // 20000 = 건물군 — 중분류 + 비고 텍스트 휴리스틱
  const text = (rmk ?? "") + (mcl ?? "");
  if (/공장|창고|물류센터|제조시설/.test(text)) return "indu";
  if (/근린생활시설|상가|사무실|업무시설|상업|점포/.test(text)) return "nrg";
  if (/오피스텔/.test(text)) return "offi";
  if (/단독주택|다가구/.test(text)) return "sh";
  if (/연립주택|다세대|빌라/.test(text)) return "rh";
  if (/아파트/.test(text)) return "apt";

  // mcl prefix fallback (정확도 낮음)
  if (mcl) {
    if (mcl.startsWith("201")) return "apt";
    if (mcl.startsWith("202")) return "rh";
    if (mcl.startsWith("203")) return "sh";
    if (mcl.startsWith("204")) return "offi";
    if (mcl.startsWith("205")) return "nrg";
    if (mcl.startsWith("206")) return "indu";
  }
  return "apt"; // 기본 (도시 매물 다수)
}

// 인근 낙찰 통계 — 우리 DB의 sale_results 집계 view에서 가져옴
async function NearbyAuctionStats({
  sdCode, sggCode, usageLcl, regionLabel, usageLabel, currentRate,
}: {
  sdCode: string | null;
  sggCode: string | null;
  usageLcl: string | null;
  regionLabel: string;
  usageLabel: string;
  currentRate: number | null;
}) {
  const s = await fetchRegionStats(sdCode, sggCode, usageLcl);
  if (!s) return null;

  // 현재 매물의 최저가율 vs 평균 매각가율 비교
  const avg = s.avg_sale_rate_pct;
  const compareNote = avg != null && currentRate != null
    ? currentRate < avg
      ? `현재 최저가는 평균 매각가율보다 ${(avg - currentRate).toFixed(0)}%p 낮음 — 잠재 할인`
      : currentRate > avg
        ? `현재 최저가는 평균 매각가율보다 ${(currentRate - avg).toFixed(0)}%p 높음 — 가격 매력 약함`
        : "평균 수준"
    : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">인근 낙찰 통계</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="text-xs text-muted-foreground">
          {regionLabel} · {usageLabel} · 표본 {s.total_count}건 (90일 내 매각 {s.recent_sold_count}건)
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Stat label="평균 매각가율" value={s.avg_sale_rate_pct != null ? `${s.avg_sale_rate_pct}%` : "-"}
                sub={compareNote ?? undefined} highlight />
          <Stat label="매각 / 전체" value={`${s.sold_count} / ${s.total_count}`}
                sub={s.total_count > 0 ? `${Math.round((s.sold_count / s.total_count) * 100)}%` : undefined} />
          <Stat label="평균 응찰자수" value={s.avg_bidder_count != null ? `${s.avg_bidder_count}명` : "-"} />
          <Stat label="평균 유찰" value={s.avg_fail_count_when_sold != null ? `${s.avg_fail_count_when_sold}회` : "-"}
                sub="매각된 건 기준" />
        </div>
        {s.recent_sold_count < 5 && (
          <div className="text-xs text-amber-700">
            ⚠ 최근 90일 매각 표본이 {s.recent_sold_count}건으로 적습니다. 통계 신뢰도가 낮을 수 있습니다.
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// 권리분석 요약 카드 — 입찰 전 위험·진행상태·말소기준권리 한눈에
function PropertyRiskCard({ p }: { p: Awaited<ReturnType<typeof fetchProperty>> }) {
  if (!p) return null;
  const flags = parseRiskFlags(p.rmk);
  const lien = parsePrimaryLien(p.primary_liens);
  const stat = parseCaseStatus(p.case_prog, p.susp_stat, p.susp_rsn);
  const dpos = parseDposRate(p.dpos_rate);
  const d = dDay(p.sale_date);

  const courtCode = p.cases?.court_code ?? "";
  const caseNo = p.cases?.case_no ?? "";
  const officialUrl = courtCode && caseNo ? courtauctionLink(courtCode, caseNo) : null;

  const hasDanger = flags.some((f) => f.level === "danger") || stat?.level === "danger";

  return (
    <Card className={hasDanger ? "border-red-300 bg-red-50/40" : ""}>
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center gap-2">
          {hasDanger && <span className="text-red-600">⚠</span>}
          입찰 전 핵심 정보
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {/* D-day + 진행상태 + 보증금률 */}
        <div className="flex flex-wrap items-center gap-2">
          {d != null && (
            <Badge variant={d <= 7 ? "destructive" : d <= 30 ? "secondary" : "outline"}
                   className="font-mono">
              {fmtDDay(d)} · {fmtDate(p.sale_date)}
            </Badge>
          )}
          {stat && (
            <Badge variant="outline" className={
              stat.level === "danger" ? "bg-red-100 text-red-900 border-red-300"
              : stat.level === "warn" ? "bg-amber-100 text-amber-900 border-amber-300"
              : "bg-green-50 text-green-900 border-green-300"
            }>
              {stat.label}{stat.reason ? ` · ${stat.reason}` : ""}
            </Badge>
          )}
          {dpos && (
            <Badge variant="outline" className={
              dpos.isSpecial ? "bg-yellow-100 text-yellow-900 border-yellow-300" : ""
            }>
              매수신청 보증금 {dpos.rate}%{dpos.isSpecial ? " (특별)" : ""}
            </Badge>
          )}
        </div>

        {/* 위험·정보 배지 */}
        {flags.length > 0 && (
          <div>
            <div className="text-xs text-muted-foreground mb-1">물건 비고</div>
            <div className="flex flex-wrap gap-1.5">
              {flags.map((f, i) => (
                <Badge key={i} variant="outline" className={
                  f.level === "danger" ? "bg-red-100 text-red-900 border-red-300"
                  : f.level === "warn" ? "bg-orange-100 text-orange-900 border-orange-300"
                  : "bg-blue-50 text-blue-900 border-blue-300"
                } title={f.desc}>
                  {f.label}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* 말소기준권리 후보 */}
        {lien && (
          <div className="rounded-md border bg-background p-2.5">
            <div className="text-xs text-muted-foreground mb-1">말소기준권리 (후보)</div>
            <div className="font-mono text-sm">
              <span className="font-semibold">{lien.date}</span>
              <span className="ml-2">{lien.type}</span>
            </div>
            {lien.others.length > 0 && (
              <div className="text-xs text-muted-foreground mt-1">
                ↓ 후순위 {lien.others.length}건
                <ul className="list-disc list-inside font-mono">
                  {lien.others.slice(0, 5).map((o, i) => <li key={i}>{o}</li>)}
                </ul>
              </div>
            )}
            <div className="text-caption-xs text-muted-foreground mt-1.5">
              ※ 자동 추출 — 정확한 권리분석은 매각물건명세서·등기부등본 직접 확인
            </div>
          </div>
        )}

        {/* 청구금액 */}
        {p.claim_amt != null && (
          <div className="text-xs">
            청구금액 <span className="font-mono font-semibold">{fmtMoney(Number(p.claim_amt))}</span>
            {p.appraisal_amount && Number(p.claim_amt) > 0 && (
              <span className="text-muted-foreground ml-1">
                (감정가의 {Math.round(Number(p.claim_amt) / p.appraisal_amount * 100)}%)
              </span>
            )}
          </div>
        )}

        {/* 공식 사이트 딥링크 */}
        {officialUrl && (
          <div className="flex items-center gap-3 pt-1 text-xs">
            <a href={officialUrl} target="_blank" rel="noopener noreferrer"
               className="text-blue-600 hover:underline">
              공식 사이트에서 보기 ↗
            </a>
            <span className="text-muted-foreground">
              매각물건명세서 · 현황조사서 · 감정평가서는 공식 사이트에서 PDF로 제공
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value, sub, highlight }: {
  label: string; value: string; sub?: string; highlight?: boolean;
}) {
  return (
    <div className="rounded-md border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`text-base mt-1 ${highlight ? "font-bold text-primary" : "font-semibold"}`}>
        {value}
      </div>
      {sub && <div className="text-xs text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}

function KvGrid({ items }: { items: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="flex gap-3 border-b last:border-0 py-1">
          <dt className="text-muted-foreground w-28 shrink-0">{k}</dt>
          <dd className="break-words">{v ?? "-"}</dd>
        </div>
      ))}
    </dl>
  );
}

function RawKv({ obj }: { obj: Record<string, unknown> }) {
  const entries = Object.entries(obj).filter(
    ([, v]) => v !== null && v !== "" && typeof v !== "object",
  );
  if (entries.length === 0) {
    return <div className="text-sm text-muted-foreground">데이터 없음</div>;
  }
  return (
    <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1 text-xs">
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <dt className="text-muted-foreground w-32 shrink-0 font-mono">{k}</dt>
          <dd className="break-words">{String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}
