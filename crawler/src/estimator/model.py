"""
낙찰 예상가 — LightGBM quantile 모델 IO.

α=0.1/0.5/0.9 부스터 3개 + meta.json(피처·카테고리 레벨·지표)을
crawler/data/models/estimator_<version>/ 에 저장. 카테고리는 학습 시점 레벨을
meta 에 고정 — 예측 시 미지 레벨은 결측(-1) 처리해 학습/예측 스큐 방지.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "models"
QUANTILES = (0.1, 0.5, 0.9)

LGB_PARAMS = dict(
    objective="quantile",
    metric="quantile",
    learning_rate=0.05,
    num_leaves=31,
    min_data_in_leaf=30,     # 표본 수천 규모 — 과적합 억제
    feature_fraction=0.9,
    bagging_fraction=0.8,
    bagging_freq=1,
    verbose=-1,
)
NUM_ROUNDS = 400


class QuantileModel:
    def __init__(self, features: list[str], categoricals: list[str],
                 version: str | None = None) -> None:
        self.features = features
        self.categoricals = categoricals
        self.version = version or datetime.now(timezone.utc).strftime("v%Y%m%d")
        self.boosters: dict[float, lgb.Booster] = {}
        self.cat_levels: dict[str, list[str]] = {}
        self.meta: dict = {}

    # ---------- 인코딩 ----------

    def _encode(self, X: pd.DataFrame, fit: bool) -> pd.DataFrame:
        X = X.copy()
        for c in self.categoricals:
            if fit:
                self.cat_levels[c] = sorted(x for x in X[c].astype(str).unique() if x)
            levels = {v: i for i, v in enumerate(self.cat_levels.get(c, []))}
            X[c] = X[c].astype(str).map(levels).fillna(-1).astype("int32")
        for c in X.columns:
            if c not in self.categoricals:
                X[c] = pd.to_numeric(X[c], errors="coerce")
        return X

    # ---------- 학습/예측 ----------

    def train(self, X: pd.DataFrame, y: pd.Series) -> None:
        Xe = self._encode(X[self.features], fit=True)
        for q in QUANTILES:
            ds = lgb.Dataset(Xe, label=y,
                             categorical_feature=self.categoricals,
                             free_raw_data=True)
            self.boosters[q] = lgb.train(
                {**LGB_PARAMS, "alpha": q}, ds, num_boost_round=NUM_ROUNDS)
        logger.info("trained %d quantile boosters on %d rows", len(QUANTILES), len(Xe))

    def predict(self, X: pd.DataFrame) -> dict[float, np.ndarray]:
        Xe = self._encode(X[self.features], fit=False)
        return {q: b.predict(Xe) for q, b in self.boosters.items()}

    # ---------- 저장/로드 ----------

    def save(self, metrics: dict | None = None) -> Path:
        d = MODELS_DIR / f"estimator_{self.version}"
        d.mkdir(parents=True, exist_ok=True)
        for q, b in self.boosters.items():
            b.save_model(str(d / f"q{int(q * 100):02d}.txt"))
        meta = {
            "version": self.version,
            "features": self.features,
            "categoricals": self.categoricals,
            "cat_levels": self.cat_levels,
            "quantiles": list(QUANTILES),
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics or {},
        }
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        # latest 포인터 — predict 가 최신 모델을 찾는 단일 진입점
        (MODELS_DIR / "LATEST").write_text(self.version)
        return d

    @classmethod
    def load_latest(cls) -> "QuantileModel | None":
        latest = MODELS_DIR / "LATEST"
        if not latest.exists():
            return None
        version = latest.read_text().strip()
        d = MODELS_DIR / f"estimator_{version}"
        meta_path = d / "meta.json"
        if not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text())
        m = cls(meta["features"], meta["categoricals"], version=meta["version"])
        m.cat_levels = meta["cat_levels"]
        m.meta = meta
        for q in meta["quantiles"]:
            p = d / f"q{int(q * 100):02d}.txt"
            if not p.exists():
                return None
            m.boosters[q] = lgb.Booster(model_file=str(p))
        return m
