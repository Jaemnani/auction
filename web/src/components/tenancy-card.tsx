import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fmtDate, fmtMoney } from "@/lib/format";
import type { PropertyTenancy } from "@/lib/types";

/**
 * 매각물건명세서 임차 사실 카드 (0026 property_tenancy).
 *
 * 값의 출처는 법원 명세서 원문이고, 판정은 보수적이다:
 *  risk    = 대항력 있는 임차인이 있을 수 있음 → 보증금이 인수될 수 있음
 *  none    = 임차인 기재가 없거나 전부 최선순위 이후 → 인수 없음
 *  unknown = 날짜를 못 읽음 → 원문 확인 필요 (인수 없음으로 넘기지 않는다)
 *
 * 미수집이면 렌더하지 않는다 (계산기 카드가 그 자리를 대신함).
 */
export function TenancyCard({ tenancy }: { tenancy: PropertyTenancy | null }) {
  if (!tenancy) return null;

  const v = tenancy.verdict;
  const style = v === "risk"
    ? { border: "border-red-300 bg-red-50/40", label: "인수 위험", cls: "bg-red-600 text-white" }
    : v === "none"
      ? { border: "border-green-300 bg-green-50/30", label: "인수 없음", cls: "bg-green-700 text-white" }
      : { border: "border-amber-300 bg-amber-50/40", label: "판단 불가", cls: "bg-amber-600 text-white" };

  const deposits = tenancy.tenants
    .map((t) => t.deposit)
    .filter((d): d is number => typeof d === "number" && d > 0);
  const maxDeposit = deposits.length > 0 ? Math.max(...deposits) : null;

  return (
    <Card className={style.border}>
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex flex-wrap items-center gap-2">
          임차·인수 분석
          <Badge className={style.cls + " hover:" + style.cls}>{style.label}</Badge>
          <span className="text-xs font-normal text-muted-foreground">
            매각물건명세서 기준 · {fmtDate(tenancy.fetched_at)} 수집
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {v === "risk" && (
          <div className="text-red-800">
            최선순위 설정일보다 앞선 임차인이 있습니다.
            {maxDeposit != null && (
              <> 보증금 <strong>{fmtMoney(maxDeposit)}</strong> 중 배당으로 회수되지 않는
                금액이 <strong>낙찰자에게 인수</strong>될 수 있습니다.</>
            )}
            {" "}아래 계산기에 값을 넣어 낙찰가별 인수액을 확인하세요.
          </div>
        )}
        {v === "none" && (
          <div className="text-green-900">
            대항력 있는 임차인이 확인되지 않았습니다 — 인수액 0으로 봅니다.
          </div>
        )}
        {v === "unknown" && (
          <div className="text-amber-900">
            명세서에서 전입일을 읽지 못했습니다. <strong>인수 없음이라는 뜻이 아닙니다</strong> —
            원문을 직접 확인하세요.
          </div>
        )}

        <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1 text-xs">
          <div className="flex gap-2">
            <dt className="text-muted-foreground w-28 shrink-0">최선순위 설정</dt>
            <dd>{fmtDate(tenancy.lien_date)} {tenancy.lien_kind ?? ""}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-muted-foreground w-28 shrink-0">배당요구종기</dt>
            <dd>{fmtDate(tenancy.demand_deadline)}</dd>
          </div>
        </dl>

        {tenancy.tenants.length > 0 && (
          <div className="rounded-md border bg-background p-2.5">
            <div className="text-xs text-muted-foreground mb-1">
              임차인 {tenancy.tenants.length}명
            </div>
            <ul className="space-y-1.5 text-xs">
              {tenancy.tenants.map((t, i) => (
                <li key={i} className="border-b last:border-0 pb-1.5 last:pb-0">
                  <span className="font-medium">{t.name ?? "성명 미상"}</span>
                  {t.deposit != null && (
                    <span className="ml-2">보증금 <strong>{fmtMoney(t.deposit)}</strong></span>
                  )}
                  {t.deposit == null && (
                    <span className="ml-2 text-muted-foreground">보증금 기재 없음</span>
                  )}
                  {t.raw && (
                    <div className="text-caption-xs text-muted-foreground mt-0.5 break-words">
                      {t.raw}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {tenancy.notes.length > 0 && (
          <ul className="text-caption-xs text-muted-foreground list-disc list-inside">
            {tenancy.notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        )}

        <div className="text-caption-xs text-muted-foreground border-t pt-2">
          명세서 원문에서 자동 추출한 값입니다. 금액이 걸린 판단이므로 입찰 전
          매각물건명세서·등기부등본 원문을 반드시 직접 확인하세요.
        </div>
      </CardContent>
    </Card>
  );
}
