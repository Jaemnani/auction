import { notFound } from "next/navigation";
import { fetchCodeNames, fetchProperty, photoPublicUrl } from "@/lib/queries";
import { fmtDate, fmtMoney, fmtDiscount, fmtPercent } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { PropertyPhotos } from "@/components/property-photos";
import { PropertyLocation } from "@/components/property-location";

export const dynamic = "force-dynamic";

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

  // 코드 이름 매핑
  const codes = [
    p.usage_lcl_cd, p.usage_mcl_cd, p.usage_scl_cd,
    p.sd_code, p.sgg_code, cs?.court_code,
  ].filter((c): c is string => !!c);
  const names = await fetchCodeNames(codes);

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

  return (
    <div className="space-y-6">
      {/* 헤더 */}
      <div>
        <div className="text-sm text-muted-foreground">
          {courtPlusDept || "-"}
        </div>
        <h1 className="text-2xl font-bold">
          {cs?.case_no} {p.maemul_ser > 1 && <span className="text-muted-foreground">#{p.maemul_ser}</span>}
        </h1>
        <div className="mt-1 text-sm">
          {p.road_addr ? (
            <span className="font-medium">{p.road_addr}</span>
          ) : (
            <>
              {regionParts && <span className="mr-2 text-muted-foreground">{regionParts}</span>}
              <span className="text-muted-foreground">{p.conv_addr ?? "-"}</span>
            </>
          )}
        </div>
        {p.road_addr && p.lot_addr && p.lot_addr !== p.road_addr && (
          <div className="text-xs text-muted-foreground mt-0.5">지번 {p.lot_addr}</div>
        )}
      </div>

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
              ["건물 요약", p.building_summary ?? "-"],
              ["면적 요약", p.area_summary ?? "-"],
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

      {/* 감정평가 요항 */}
      {aeeWevl.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-base">감정평가 요항</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-2">
            {aeeWevl.map((item, i) => (
              <div key={i} className="border-b pb-2 last:border-0">
                <div className="font-medium">
                  {String(item?.aeeEvlMnpntNm ?? `항목 ${i + 1}`)}
                </div>
                <div className="text-muted-foreground whitespace-pre-wrap">
                  {String(item?.aeeEvlMnpntCn ?? "")}
                </div>
              </div>
            ))}
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

function KvGrid({ items }: { items: [string, string][] }) {
  return (
    <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="flex gap-3 border-b last:border-0 py-1">
          <dt className="text-muted-foreground w-28 shrink-0">{k}</dt>
          <dd className="break-words">{v || "-"}</dd>
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
