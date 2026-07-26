"""
estimate.py — 낙찰 예상가 모델 학습/평가/예측 CLI.

서브커맨드:
    train                sale_results 전량으로 quantile 모델 학습 → crawler/data/models/
        --dry-run            피처 매트릭스 shape/결측률만 출력 (학습 안 함)
    evaluate             시간 분할 백테스트 — 마지막 N일 hold-out 의 가율 MAE/가격 MAPE
        --holdout-days N     (기본 60)
    predict              활성 매물 전량 예측 → property_estimates upsert (0022)
        --limit N            상위 N건만 (테스트용)

모델 없거나 세그먼트 표본 부족 시 폴백: auction_stats_by_region 평균 매각가율
(method='region_avg'). 스케줄: predict 는 run_daily.sh 말미(일 1회),
train + evaluate 는 주 1회 cron (install_cron.sh).

환경변수 (.env): SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from estimator import EstimatorData, QuantileModel  # noqa: E402

logger = logging.getLogger(__name__)

# 세그먼트(시군구×용도) 학습 표본이 이 미만이면 모델 대신 region_avg 폴백
MIN_SEGMENT_SAMPLES = 10
# 예측 가율 클리핑 — quantile 회귀 외삽 방어
RATE_CLIP = (0.1, 2.0)


def _prep_training(data: EstimatorData):
    df = data.fetch_training_rows()
    if df.empty:
        return df, None, None
    y = data.build_target(df)
    keep = y.notna()
    df, y = df[keep].reset_index(drop=True), y[keep].reset_index(drop=True)
    X = data.build_features(df).reset_index(drop=True)
    return df, X, y


def _print_matrix_report(X: pd.DataFrame, y: pd.Series) -> None:
    print(f"[matrix] rows={len(X)} features={len(X.columns)}")
    print(f"  target(rate): mean={y.mean():.3f} p10={y.quantile(0.1):.3f} "
          f"p90={y.quantile(0.9):.3f}")
    na = X.isna().mean().sort_values(ascending=False)
    for col, frac in na.items():
        print(f"  {col:18s} 결측 {frac * 100:5.1f}%")


def cmd_train(args: argparse.Namespace) -> None:
    data = EstimatorData()
    started = time.monotonic()
    df, X, y = _prep_training(data)
    if X is None or len(X) < 100:
        print(f"[skip] 학습 표본 부족 ({0 if X is None else len(X)}건 < 100) — "
              f"sales-results 백필 후 재시도")
        return
    _print_matrix_report(X, y)
    if args.dry_run:
        print("[dry-run] 학습 생략")
        return
    model = QuantileModel(EstimatorData.FEATURES, EstimatorData.CATEGORICALS)
    model.train(X, y)
    d = model.save()
    print(f"[done] trained {model.version} on {len(X)} rows → {d} "
          f"({time.monotonic() - started:.0f}s)")


def cmd_evaluate(args: argparse.Namespace) -> None:
    data = EstimatorData()
    df, X, y = _prep_training(data)
    if X is None or len(X) < 200:
        print("[skip] 평가 표본 부족 (<200)")
        return
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=args.holdout_days)).date().isoformat()
    dates = df["sale_date"].fillna("")
    tr, ho = dates < cutoff, dates >= cutoff
    if ho.sum() < 30 or tr.sum() < 100:
        print(f"[skip] 시간 분할 불가 (train={int(tr.sum())} holdout={int(ho.sum())})")
        return
    model = QuantileModel(EstimatorData.FEATURES, EstimatorData.CATEGORICALS,
                          version="eval")
    model.train(X[tr], y[tr])
    pred = model.predict(X[ho])[0.5]
    pred = np.clip(pred, *RATE_CLIP)
    y_ho = y[ho].to_numpy()
    appraisal = pd.to_numeric(df.loc[ho, "appraisal_amount"]).to_numpy()
    mae_rate = float(np.mean(np.abs(pred - y_ho)))
    mape_price = float(np.mean(
        np.abs(pred * appraisal - y_ho * appraisal) / (y_ho * appraisal)))
    # 폴백 베이스라인 — 지역 평균 가율
    base = X.loc[ho, "region_avg_rate"].to_numpy() / 100.0
    base_mask = ~np.isnan(base)
    base_mae = float(np.mean(np.abs(base[base_mask] - y_ho[base_mask]))) \
        if base_mask.any() else float("nan")
    print(f"[eval] holdout {cutoff}~ ({int(ho.sum())}건, train {int(tr.sum())}건)")
    print(f"  모델   가율 MAE {mae_rate:.4f} | 가격 MAPE {mape_price * 100:.1f}%")
    print(f"  베이스 가율 MAE {base_mae:.4f} (지역 평균 폴백, {int(base_mask.sum())}건)")


def cmd_predict(args: argparse.Namespace) -> None:
    data = EstimatorData()
    started = time.monotonic()
    model = QuantileModel.load_latest()
    if model is None:
        print("[warn] 저장된 모델 없음 — 전량 region_avg 폴백으로 예측")

    df = data.fetch_active_rows(limit=args.limit)
    if df.empty:
        print("[done] predict — candidates: 0")
        return
    X = data.build_features(df)

    # 세그먼트 표본 수 (신뢰도) — 학습 데이터 기준
    train_df = data.fetch_training_rows()
    seg = data.segment_counts(train_df) if not train_df.empty else {}
    stats = data.region_avg_rate()

    if model is not None:
        preds = model.predict(X)
        p10 = np.clip(preds[0.1], *RATE_CLIP)
        p50 = np.clip(preds[0.5], *RATE_CLIP)
        p90 = np.clip(preds[0.9], *RATE_CLIP)
    else:
        p10 = p50 = p90 = np.full(len(df), np.nan)

    now_iso = datetime.now(timezone.utc).isoformat()
    payload: list[dict] = []
    n_model = n_fallback = n_skip = 0
    for i, row in df.reset_index(drop=True).iterrows():
        appraisal = float(row["appraisal_amount"])
        sgg_key = (str(row.get("sgg_code") or ""), str(row.get("usage_lcl_cd") or ""))
        samples = seg.get(sgg_key, 0)
        feats = X.iloc[i]
        used = {c: (feats[c] is not None and not pd.isna(feats[c]))
                for c in ("area_m2", "building_age", "region_price_m2",
                          "region_avg_rate")}

        if model is not None and samples >= MIN_SEGMENT_SAMPLES:
            rate, lo, hi = float(p50[i]), float(p10[i]), float(p90[i])
            method = "model"
            n_model += 1
        else:
            avg = stats.get((str(row.get("sd_code") or ""),
                             str(row.get("sgg_code") or ""),
                             str(row.get("usage_lcl_cd") or "")))
            if avg is None:
                n_skip += 1
                continue  # 폴백 근거도 없음 — 예측 미저장
            rate = avg / 100.0
            lo, hi = rate * 0.85, rate * 1.15  # 통계 폴백 — 고정 ±15% 밴드
            method = "region_avg"
            n_fallback += 1

        payload.append({
            "property_id": row["property_id"],
            "estimated_price": round(rate * appraisal),
            "estimated_low": round(lo * appraisal),
            "estimated_high": round(hi * appraisal),
            "estimated_rate_pct": round(rate * 100, 1),
            "method": method,
            "model_version": model.version if (model and method == "model") else None,
            "sample_count": samples,
            "features_used": used,
            "predicted_at": now_iso,
        })

    CHUNK = 200
    try:
        for i in range(0, len(payload), CHUNK):
            data.sb.table("property_estimates").upsert(payload[i:i + CHUNK]).execute()
    except Exception as e:  # noqa: BLE001
        if "42P01" in str(e) or "does not exist" in str(e):
            print("[fatal] property_estimates 테이블 없음 — "
                  "0022_property_estimates.sql 을 NAS psql 로 먼저 적용하세요")
            sys.exit(1)
        raise
    print(f"[done] predict — saved={len(payload)} (model={n_model} "
          f"region_avg={n_fallback} skip={n_skip}) of {len(df)} active "
          f"({time.monotonic() - started:.0f}s)")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(description="낙찰 예상가 모델 학습/평가/예측")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_t = sub.add_parser("train", help="quantile 모델 학습 → data/models/")
    p_t.add_argument("--dry-run", action="store_true",
                     help="피처 매트릭스 리포트만 (학습 생략)")
    p_t.set_defaults(func=cmd_train)

    p_e = sub.add_parser("evaluate", help="시간 분할 백테스트 (hold-out MAE/MAPE)")
    p_e.add_argument("--holdout-days", type=int, default=60)
    p_e.set_defaults(func=cmd_evaluate)

    p_p = sub.add_parser("predict", help="활성 매물 예측 → property_estimates")
    p_p.add_argument("--limit", type=int, default=None, help="상위 N건만 (테스트)")
    p_p.set_defaults(func=cmd_predict)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
