import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { fmtDate, fmtDiscount, fmtMoneyShort } from "@/lib/format";
import { photoThumbUrl } from "@/lib/queries";
import { dDay, fmtDDay } from "@/lib/analysis";
import { AreaText } from "@/components/area-text";
import { ScoreBadge } from "@/components/score-badge";
import type { Property } from "@/lib/types";

type Props = { rows: Property[]; usageNames?: Record<string, string> };

export function PropertyTable({ rows, usageNames = {} }: Props) {
  if (rows.length === 0) {
    return (
      <div className="text-center text-muted-foreground py-16 border rounded-md">
        조건에 맞는 매물이 없습니다.
      </div>
    );
  }

  return (
    <ul className="border rounded-md divide-y bg-card">
      {rows.map((r, i) => (
        <PropertyRow key={r.id} r={r} usageNames={usageNames} eager={i === 0} />
      ))}
    </ul>
  );
}

function PropertyRow({ r, usageNames, eager = false }: {
  r: Property; usageNames: Record<string, string>; eager?: boolean;
}) {
  const ratio = r.appraisal_amount && r.min_sale_price
    ? Math.round((r.min_sale_price / r.appraisal_amount) * 100)
    : null;
  const discount = fmtDiscount(r.min_sale_price, r.appraisal_amount);
  const usage = r.usage_lcl_cd ? usageNames[r.usage_lcl_cd] : null;

  // 낙찰 완료 (0018) — 종결 후 30일 유예창에서만 목록에 등장 (status=with_sold/sold_only)
  const isSold = r.final_result === "sold";
  const soldRate = isSold && r.appraisal_amount && r.sold_amount
    ? Math.round((r.sold_amount / r.appraisal_amount) * 100)
    : null;

  // 썸네일 — 가장 작은 seq의 storage_path
  const thumb = (r.property_photos ?? [])
    .filter((p) => !!p.storage_path)
    .sort((a, b) => a.seq - b.seq)[0];
  const thumbUrl = thumb?.storage_path ? photoThumbUrl(thumb.storage_path) : null;

  const href = r.docid ? `/p/${encodeURIComponent(r.docid)}` : undefined;
  const Wrapper = ({ children }: React.PropsWithChildren) =>
    href
      // 상세는 항상 새 창 — 목록의 필터/페이지 상태를 잃지 않게
      ? <Link href={href} target="_blank" rel="noopener noreferrer" className="block">{children}</Link>
      : <>{children}</>;

  return (
    <li className="hover:bg-muted/30 transition">
      <Wrapper>
        <div className="flex items-stretch gap-3 p-3 min-w-0">
          {/* 썸네일 */}
          <div className="shrink-0 w-24 sm:w-32 aspect-[4/3] overflow-hidden rounded border bg-muted/30 flex items-center justify-center">
            {thumbUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={thumbUrl}
                alt=""
                loading={eager ? "eager" : "lazy"}
                fetchPriority={eager ? "high" : "auto"}
                decoding={eager ? "sync" : "async"}
                className="h-full w-full object-cover"
              />
            ) : (
              <span className="text-caption-xs text-muted-foreground">사진 없음</span>
            )}
          </div>

          {/* 본문 — flex-1 + min-w-0로 truncate 작동 */}
          <div className="flex-1 min-w-0 flex flex-col justify-between gap-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
              <span className="font-mono font-semibold text-foreground">
                {r.cases?.case_no ?? "-"}
                {r.maemul_ser > 1 && <span className="text-muted-foreground"> #{r.maemul_ser}</span>}
              </span>
              <span className="text-muted-foreground">·</span>
              <span className="text-muted-foreground truncate">{r.cases?.courts?.name ?? "-"}</span>
              {usage && <Badge variant="outline" className="text-caption-xs">{usage}</Badge>}
              <ScoreBadge score={r.scores} size="sm" />
            </div>

            <div className="text-sm font-medium truncate">
              {r.road_addr ? r.road_addr
                : r.conv_addr ? <AreaText>{r.conv_addr}</AreaText>
                : "-"}
            </div>

            {/* 면적 — area_summary는 ㎡로 들어와 있고 AreaText가 ㎡↔평 토글 처리 */}
            {r.area_summary && (
              <div className="text-xs">
                <span className="text-muted-foreground mr-1">면적</span>
                <span className="font-mono"><AreaText>{r.area_summary}</AreaText></span>
              </div>
            )}
            {/* 동·호수 — building_summary에 "제○동 제○층 제○호" 형식으로 들어있음 */}
            {r.building_summary && (
              <div className="text-xs text-muted-foreground line-clamp-1">
                <span className="mr-1">위치</span>
                <AreaText>{r.building_summary}</AreaText>
              </div>
            )}
            {!r.road_addr && r.conv_addr && (
              <div className="text-caption-xs text-amber-600">(도로명 미수집)</div>
            )}

            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
              {isSold && (
                <Badge className="text-caption-xs bg-blue-600 text-white hover:bg-blue-600">
                  낙찰 {r.sold_date ? fmtDate(r.sold_date) : ""}
                </Badge>
              )}
              <span>매각: {fmtDate(r.sale_date)}</span>
              {(() => {
                if (isSold) return null;  // 종결 매물엔 D-day 무의미
                const d = dDay(r.sale_date);
                if (d == null) return null;
                const cls = d < 0 ? "text-muted-foreground"
                  : d <= 7 ? "text-red-600 font-semibold"
                  : d <= 30 ? "text-amber-600 font-semibold"
                  : "text-foreground";
                return <span className={`text-caption-xs font-mono ${cls}`}>{fmtDDay(d)}</span>;
              })()}
              {r.cases?.claim_amount != null && r.cases.claim_amount > 0 && (
                <span>청구: <span className="font-mono">{fmtMoneyShort(r.cases.claim_amount)}</span></span>
              )}
              {r.fail_count != null && r.fail_count > 0 && (
                <Badge variant="secondary" className="text-caption-xs font-mono">유찰 {r.fail_count}</Badge>
              )}
              {discount !== "-" && (
                <Badge variant="destructive" className="text-caption-xs">{discount}</Badge>
              )}
              {/* 위험·보증금·진행상태 배지는 detail 페이지에 노출
                  (목록 query에서 detail_result JSON path 추출은 17k row × jsonb로 타임아웃) */}
            </div>
          </div>

          {/* 가격 — 우측 정렬. 낙찰 완료면 최저가 대신 낙찰가 강조 */}
          <div className="shrink-0 text-right space-y-0.5 min-w-[88px]">
            <div className="text-caption-xs text-muted-foreground">감정가</div>
            <div className="text-sm">{fmtMoneyShort(r.appraisal_amount)}</div>
            {isSold ? (
              <>
                <div className="text-caption-xs text-blue-600 mt-1">낙찰가</div>
                <div className="text-sm font-bold text-blue-600">{fmtMoneyShort(r.sold_amount ?? null)}</div>
                {soldRate != null && (
                  <div className="text-caption-xs text-muted-foreground">감정가의 {soldRate}%</div>
                )}
              </>
            ) : (
              <>
                <div className="text-caption-xs text-muted-foreground mt-1">최저가</div>
                <div className="text-sm font-bold text-primary">{fmtMoneyShort(r.min_sale_price)}</div>
                {ratio != null && (
                  <div className="text-caption-xs text-muted-foreground">감정가의 {ratio}%</div>
                )}
              </>
            )}
          </div>
        </div>
      </Wrapper>
    </li>
  );
}
