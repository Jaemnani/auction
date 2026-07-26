import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fmtMoney } from "@/lib/format";
import { fetchEstimate } from "@/lib/queries";

/**
 * 낙찰 예상가 카드 (서버 컴포넌트) — property_estimates(0022) 배치 예측 결과.
 * method='model': LightGBM quantile 회귀 (범위 = 10~90% 분위)
 * method='region_avg': 지역 평균 매각가율 폴백 (±15% 밴드) — 참고용 경고 표시.
 */
export async function EstimateCard({
  propertyId, appraisalAmount,
}: {
  propertyId: string;
  appraisalAmount: number | null;
}) {
  const e = await fetchEstimate(propertyId);
  if (!e || e.estimated_price == null) return null;

  const lowConfidence = e.method === "region_avg" || (e.sample_count ?? 0) < 30;
  const missing: string[] = [];
  if (e.features_used) {
    const labels: Record<string, string> = {
      area_m2: "면적", building_age: "건물 연식",
      region_price_m2: "지역 실거래 시세", region_avg_rate: "지역 매각가율 통계",
    };
    for (const [k, used] of Object.entries(e.features_used)) {
      if (!used && labels[k]) missing.push(labels[k]);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">낙찰 예상가 (베타)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-2xl font-bold text-primary">
            {fmtMoney(e.estimated_price)}
          </span>
          {e.estimated_low != null && e.estimated_high != null && (
            <span className="text-sm text-muted-foreground">
              범위 {fmtMoney(e.estimated_low)} ~ {fmtMoney(e.estimated_high)}
            </span>
          )}
          {e.estimated_rate_pct != null && appraisalAmount != null && (
            <span className="text-sm text-muted-foreground">
              감정가의 {e.estimated_rate_pct}%
            </span>
          )}
        </div>
        <div className="text-xs text-muted-foreground">
          {e.method === "model"
            ? <>자체 낙찰 데이터 기반 예측 모델{e.model_version ? ` (${e.model_version})` : ""} · 학습 표본 {e.sample_count ?? 0}건 (동일 시군구·용도)</>
            : <>지역 평균 매각가율 기반 추정 (모델 표본 부족)</>}
        </div>
        {lowConfidence && (
          <div className="text-xs text-amber-700">
            ⚠ 표본이 적어 신뢰도가 낮습니다 — 참고용으로만 활용하세요.
          </div>
        )}
        {missing.length > 0 && (
          <div className="text-caption-xs text-muted-foreground">
            미반영 정보: {missing.join(", ")} (데이터 수집 중 — 축적되면 정확도 개선)
          </div>
        )}
        <div className="text-caption-xs text-muted-foreground border-t pt-2">
          본 예상가는 통계 모델의 추정치이며 실제 낙찰가와 다를 수 있습니다.
          입찰 판단의 책임은 이용자에게 있습니다.
        </div>
      </CardContent>
    </Card>
  );
}
