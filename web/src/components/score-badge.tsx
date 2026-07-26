import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { PropertyScoreBrief } from "@/lib/types";

/** 매수 안전도(0023) 점수대 → 라벨/색. 지도 팝업(HTML 문자열)과 색을 맞춤. */
export function scoreBand(score: number): {
  label: string;
  cls: string;
  hex: string;
} {
  if (score >= 80)
    return { label: "안전", cls: "bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-900", hex: "#059669" };
  if (score >= 65)
    return { label: "양호", cls: "bg-lime-100 text-lime-700 border-lime-200 dark:bg-lime-950/40 dark:text-lime-300 dark:border-lime-900", hex: "#65a30d" };
  if (score >= 45)
    return { label: "주의", cls: "bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900", hex: "#d97706" };
  return { label: "위험", cls: "bg-red-100 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-900", hex: "#dc2626" };
}

const CONF_NOTE: Record<PropertyScoreBrief["confidence"], string> = {
  high: "",
  medium: "건물 연식 정보 부족",
  low: "상세 미확보 — 정보 부족(점수 잠정)",
};

/**
 * 매수 안전도 배지 — 가격 제외 위험성 점수(0023). 100에 가까울수록 안전.
 * confidence low면 흐리게 + 물음표(정보부족). 미채점(null)이면 렌더 안 함.
 */
export function ScoreBadge({
  score,
  size = "md",
  className = "",
}: {
  score: PropertyScoreBrief | null | undefined;
  size?: "sm" | "md";
  className?: string;
}) {
  if (!score) return null;
  const band = scoreBand(score.score);
  const low = score.confidence === "low";
  const pad = size === "sm" ? "px-1.5 py-0 text-caption-xs" : "px-2 py-0.5 text-xs";
  return (
    <span
      title={`매수 안전도 ${score.score}/100 (가격 제외)${CONF_NOTE[score.confidence] ? " · " + CONF_NOTE[score.confidence] : ""}`}
      className={
        `inline-flex items-center gap-1 rounded-full border font-semibold whitespace-nowrap ` +
        `${band.cls} ${pad} ${low ? "opacity-60" : ""} ${className}`
      }
    >
      <span>{band.label}</span>
      <span className="tabular-nums">{score.score}</span>
      {low && <span className="font-normal opacity-70">?</span>}
    </span>
  );
}

const TIER_CLS: Record<"danger" | "warn" | "info", string> = {
  danger: "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-900",
  warn: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900",
  info: "bg-muted text-muted-foreground border-transparent",
};

/**
 * 매수 안전도 카드 (상세) — 가격 제외 위험성 점수(0023) + 감점 요인.
 * 미채점(null)이면 렌더 안 함. breakdown.top_factors 로 감점 근거 노출.
 */
export function ScoreCard({ score }: { score: PropertyScoreBrief | null | undefined }) {
  if (!score) return null;
  const band = scoreBand(score.score);
  const factors = score.breakdown?.top_factors ?? [];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">매수 안전도 (베타)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-bold tabular-nums" style={{ color: band.hex }}>
            {score.score}
          </span>
          <span className="text-sm text-muted-foreground">/ 100</span>
          <span
            className={`ml-1 inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${band.cls}`}
          >
            {band.label}
          </span>
        </div>
        <p className="text-caption-sm text-muted-foreground">
          가격을 제외한 <b>위험성</b> 기준 — 100에 가까울수록 안전한 매물.
          가격(할인·예상 낙찰가)은 아래 예상가 카드에서 별도로 확인하세요.
          {score.confidence === "low" && " ⚠ 상세정보 미확보로 점수는 잠정치입니다."}
          {score.confidence === "medium" && " (건물 연식 정보 일부 부족)"}
        </p>
        {factors.length > 0 && (
          <div>
            <div className="text-caption-xs text-muted-foreground mb-1.5">주요 감점 요인</div>
            <div className="flex flex-wrap gap-1.5">
              {factors.map((f, i) => (
                <span
                  key={i}
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-caption-xs font-medium ${TIER_CLS[f.tier]}`}
                >
                  {f.label}
                  <span className="tabular-nums opacity-70">−{f.penalty}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
