import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { fmtDate, fmtDiscount, fmtMoneyShort } from "@/lib/format";
import { photoThumbUrl } from "@/lib/queries";
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
      {rows.map((r) => (
        <PropertyRow key={r.id} r={r} usageNames={usageNames} />
      ))}
    </ul>
  );
}

function PropertyRow({ r, usageNames }: { r: Property; usageNames: Record<string, string> }) {
  const ratio = r.appraisal_amount && r.min_sale_price
    ? Math.round((r.min_sale_price / r.appraisal_amount) * 100)
    : null;
  const discount = fmtDiscount(r.min_sale_price, r.appraisal_amount);
  const usage = r.usage_lcl_cd ? usageNames[r.usage_lcl_cd] : null;

  // 썸네일 — 가장 작은 seq의 storage_path
  const thumb = (r.property_photos ?? [])
    .filter((p) => !!p.storage_path)
    .sort((a, b) => a.seq - b.seq)[0];
  const thumbUrl = thumb?.storage_path ? photoThumbUrl(thumb.storage_path) : null;

  const href = r.docid ? `/p/${encodeURIComponent(r.docid)}` : undefined;
  const Wrapper = ({ children }: React.PropsWithChildren) =>
    href
      ? <Link href={href} className="block">{children}</Link>
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
                loading="lazy"
                className="h-full w-full object-cover"
              />
            ) : (
              <span className="text-[10px] text-muted-foreground">사진 없음</span>
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
              {usage && <Badge variant="outline" className="text-[10px]">{usage}</Badge>}
            </div>

            <div className="text-sm font-medium truncate">
              {r.road_addr ?? r.conv_addr ?? "-"}
            </div>

            {r.building_summary && (
              <div className="text-xs text-muted-foreground line-clamp-1">
                {r.building_summary}
              </div>
            )}
            {!r.road_addr && r.conv_addr && (
              <div className="text-[10px] text-amber-600">(도로명 미수집)</div>
            )}

            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
              <span>매각: {fmtDate(r.sale_date)}</span>
              {r.fail_count != null && r.fail_count > 0 && (
                <Badge variant="secondary" className="text-[10px] font-mono">유찰 {r.fail_count}</Badge>
              )}
              {discount !== "-" && (
                <Badge variant="destructive" className="text-[10px]">{discount}</Badge>
              )}
            </div>
          </div>

          {/* 가격 — 우측 정렬 */}
          <div className="shrink-0 text-right space-y-0.5 min-w-[88px]">
            <div className="text-[10px] text-muted-foreground">감정가</div>
            <div className="text-sm">{fmtMoneyShort(r.appraisal_amount)}</div>
            <div className="text-[10px] text-muted-foreground mt-1">최저가</div>
            <div className="text-sm font-bold text-primary">{fmtMoneyShort(r.min_sale_price)}</div>
            {ratio != null && (
              <div className="text-[10px] text-muted-foreground">감정가의 {ratio}%</div>
            )}
          </div>
        </div>
      </Wrapper>
    </li>
  );
}
