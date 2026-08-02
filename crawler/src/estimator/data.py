"""
낙찰 예상가 — 데이터/피처 레이어.

학습: sale_results(낙찰 완료, sale_amount>0) → 매각가율 타깃.
예측: properties(활성) → 동일 피처.
공통 피처를 한 함수(build_features)로 만들어 학습/예측 스큐 방지.

피처 결측은 그대로 NaN 유지 — LightGBM native 결측 처리로 콜드스타트
(실거래가·건축물대장 미축적) 상태에서도 v0 모델이 동작.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import pandas as pd
from supabase import Client, create_client

logger = logging.getLogger(__name__)

# usage_nm → molit deal_type (지역 시세 피처 매칭용) — molit.store 와 동일 규칙
try:
    from molit.store import usage_nm_to_deal_type
except ImportError:  # sys.path 순서에 따라 (스크립트가 src 를 넣어줌)
    usage_nm_to_deal_type = None  # type: ignore

_AREA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*㎡")


def parse_area_m2(text: object) -> float | None:
    """area_summary('… 84.97㎡ …') → 대표 면적. 복수면 최대값(전유+대지 중 큰 쪽).
    pandas 결측은 NaN(float, truthy)으로 들어오므로 str 외 입력은 None."""
    if not isinstance(text, str) or not text:
        return None
    vals = [float(m) for m in _AREA_RE.findall(text)]
    return max(vals) if vals else None


def _page_all(q_builder, page: int = 1000) -> list[dict[str, Any]]:
    """PostgREST 1000행 상한 우회 — q_builder()가 새 쿼리를 만들어야 함."""
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        r = q_builder().range(offset, offset + page - 1).execute()
        rows = r.data or []
        out.extend(rows)
        if len(rows) < page:
            return out
        offset += page


class EstimatorData:
    def __init__(self) -> None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL / SUPABASE_(SERVICE_)KEY env required")
        self.sb: Client = create_client(url, key)
        self._region_stats: dict[tuple[str, str, str], float] | None = None
        self._molit_price: dict[tuple[str, str], float] | None = None

    # ---------- 보조 lookup ----------

    def region_avg_rate(self) -> dict[tuple[str, str, str], float]:
        """(sd, sgg, usage_lcl) → 평균 매각가율(%). auction_stats_by_region."""
        if self._region_stats is None:
            rows = _page_all(lambda: self.sb.table("auction_stats_by_region")
                             .select("sd_code, sgg_code, usage_lcl_cd, avg_sale_rate_pct")
                             .order("sd_code").order("sgg_code"))
            self._region_stats = {
                (r["sd_code"], r["sgg_code"], r["usage_lcl_cd"] or ""):
                    float(r["avg_sale_rate_pct"])
                for r in rows if r.get("avg_sale_rate_pct") is not None
            }
        return self._region_stats

    def molit_price_latest(self) -> dict[tuple[str, str], float]:
        """(lawd_cd, deal_type) → 최신 분기 ㎡당 중위가(만원). molit_price_by_region.
        표본 3건 미만 분기는 노이즈라 제외."""
        if self._molit_price is None:
            self._molit_price = {}
            try:
                rows = _page_all(lambda: self.sb.table("molit_price_by_region")
                                 .select("lawd_cd, deal_type, quarter_start, "
                                         "deal_count, median_manwon_per_m2")
                                 .order("lawd_cd").order("deal_type")
                                 .order("quarter_start", desc=True))
            except Exception as e:  # noqa: BLE001 — 0020/0022 미적용 시 콜드스타트
                logger.warning("molit_price_by_region 조회 실패(콜드스타트로 진행): %s", e)
                rows = []
            for r in rows:
                key = (r["lawd_cd"], r["deal_type"])
                if key in self._molit_price:
                    continue  # 최신 분기 우선 (desc 정렬)
                if (r.get("deal_count") or 0) >= 3 and r.get("median_manwon_per_m2"):
                    self._molit_price[key] = float(r["median_manwon_per_m2"])
        return self._molit_price

    def building_age_map(self, property_ids: list[str]) -> dict[str, int]:
        """property_id → 준공년도. property_building_register (없으면 빈 dict)."""
        out: dict[str, int] = {}
        CHUNK = 150
        try:
            for i in range(0, len(property_ids), CHUNK):
                r = (self.sb.table("property_building_register")
                     .select("property_id, use_approval_day")
                     .eq("fetch_status", "ok")
                     .in_("property_id", property_ids[i:i + CHUNK])
                     .execute())
                for row in r.data or []:
                    day = row.get("use_approval_day")
                    if day and len(day) >= 4:
                        out[row["property_id"]] = int(day[:4])
        except Exception as e:  # noqa: BLE001 — 0021 미적용 시 콜드스타트
            logger.warning("building_register 조회 실패(콜드스타트로 진행): %s", e)
        return out

    # ---------- 학습 데이터 ----------

    def fetch_training_rows(self) -> pd.DataFrame:
        """sale_results 낙찰 완료 전량 + properties(docid) enrich."""
        rows = _page_all(lambda: self.sb.table("sale_results")
                         .select("docid, court_code, appraisal_amount, min_sale_price, "
                                 "sale_amount, fail_count, sale_date, "
                                 "usage_lcl_cd, usage_mcl_cd, sd_code, sgg_code")
                         .gt("sale_amount", 0).gt("appraisal_amount", 0)
                         .order("sale_date"))
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        # properties enrich — area_summary/usage_nm/id (건축물대장 join 키)
        docids = [d for d in df["docid"].dropna().unique().tolist() if d]
        props: dict[str, dict[str, Any]] = {}
        CHUNK = 150
        for i in range(0, len(docids), CHUNK):
            r = (self.sb.table("properties")
                 .select("id, docid, area_summary, usage_nm")
                 .in_("docid", docids[i:i + CHUNK])
                 .execute())
            for row in r.data or []:
                props[row["docid"]] = row
        df["property_id"] = df["docid"].map(lambda d: (props.get(d) or {}).get("id"))
        df["area_summary"] = df["docid"].map(lambda d: (props.get(d) or {}).get("area_summary"))
        df["usage_nm"] = df["docid"].map(lambda d: (props.get(d) or {}).get("usage_nm"))
        return df

    # ---------- 예측 대상 ----------

    def fetch_active_rows(self, limit: int | None = None) -> pd.DataFrame:
        """활성 매물 (deleted_at null, 감정가 있음)."""
        def q():
            return (self.sb.table("properties")
                    .select("id, docid, appraisal_amount, min_sale_price, fail_count, "
                            "sale_date, usage_lcl_cd, usage_mcl_cd, usage_nm, "
                            "sd_code, sgg_code, area_summary, "
                            "cases:case_id ( court_code )")
                    .is_("deleted_at", "null")
                    .gt("appraisal_amount", 0)
                    .order("id"))
        rows = _page_all(q)
        if limit:
            rows = rows[:limit]
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["court_code"] = df["cases"].map(
            lambda c: (c or {}).get("court_code") if isinstance(c, dict) else None)
        df = df.drop(columns=["cases"])
        df["property_id"] = df["id"]
        return df

    # ---------- 공통 피처 ----------

    FEATURES = [
        "appraisal_amount", "min_rate", "fail_count", "sale_month",
        "area_m2", "building_age", "region_price_m2", "region_avg_rate",
        "usage_lcl_cd", "usage_mcl_cd", "sd_code", "lawd_cd", "court_code",
    ]
    CATEGORICALS = ["usage_lcl_cd", "usage_mcl_cd", "sd_code", "lawd_cd", "court_code"]

    def build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """학습/예측 공용 피처 매트릭스. df 는 fetch_training_rows/fetch_active_rows 출력."""
        out = pd.DataFrame(index=df.index)
        out["appraisal_amount"] = pd.to_numeric(df["appraisal_amount"], errors="coerce")
        min_sale = pd.to_numeric(df.get("min_sale_price"), errors="coerce")
        out["min_rate"] = min_sale / out["appraisal_amount"]
        out["fail_count"] = pd.to_numeric(df.get("fail_count"), errors="coerce")
        out["sale_month"] = pd.to_datetime(
            df.get("sale_date"), errors="coerce").dt.month
        out["area_m2"] = df.get("area_summary").map(parse_area_m2) \
            if "area_summary" in df else float("nan")

        # 건축물대장 연식 (없으면 NaN)
        ids = [i for i in df.get("property_id", pd.Series(dtype=object))
               .dropna().tolist()]
        age_map = self.building_age_map(ids) if ids else {}
        year_now = pd.Timestamp.now().year
        out["building_age"] = df.get("property_id", pd.Series(index=df.index)).map(
            lambda pid: (year_now - age_map[pid]) if pid in age_map else float("nan"))

        # 지역 실거래 ㎡당 중위가 — lawd + usage_nm 유도 deal_type
        prices = self.molit_price_latest()
        lawd = (df["sd_code"].fillna("") + df["sgg_code"].fillna(""))
        if usage_nm_to_deal_type is not None:
            dtype = df.apply(lambda r: usage_nm_to_deal_type(
                r.get("usage_nm"), r.get("usage_lcl_cd")) or "apt", axis=1)
        else:
            dtype = pd.Series("apt", index=df.index)
        out["region_price_m2"] = [
            prices.get((lw, dt), float("nan")) for lw, dt in zip(lawd, dtype)
        ]

        # 지역 평균 매각가율 (기존 통계 view)
        stats = self.region_avg_rate()
        out["region_avg_rate"] = [
            stats.get((sd or "", sg or "", ul or ""), float("nan"))
            for sd, sg, ul in zip(df["sd_code"], df["sgg_code"], df["usage_lcl_cd"])
        ]

        # categorical (문자열 그대로 — 모델 레이어에서 코드화)
        out["usage_lcl_cd"] = df["usage_lcl_cd"].fillna("")
        out["usage_mcl_cd"] = df.get("usage_mcl_cd", pd.Series(index=df.index)).fillna("")
        out["sd_code"] = df["sd_code"].fillna("")
        out["lawd_cd"] = lawd
        out["court_code"] = df.get("court_code", pd.Series(index=df.index)).fillna("")
        return out[self.FEATURES]

    @staticmethod
    def build_target(df: pd.DataFrame) -> pd.Series:
        """매각가율 타깃 — 이상치(0.1 미만 / 3 초과)는 학습에서 제외용 NaN."""
        rate = (pd.to_numeric(df["sale_amount"], errors="coerce")
                / pd.to_numeric(df["appraisal_amount"], errors="coerce"))
        return rate.where((rate >= 0.1) & (rate <= 3.0))

    def segment_counts(self, df: pd.DataFrame) -> dict[tuple[str, str], int]:
        """(sgg_code, usage_lcl_cd) 학습 표본 수 — 신뢰도(sample_count) 표시용."""
        g = df.groupby([df["sgg_code"].fillna(""), df["usage_lcl_cd"].fillna("")])
        return {k: int(v) for k, v in g.size().items()}
