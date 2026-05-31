"""Gemini API 기반 매물 분류기 — Plan 4-6 LLM 보강.

룰 엔진(courtauction/derived_category.py)이 미분류한 단독·다가구 매물 대상.
1차는 텍스트만 (사진 추후 멀티모달 가능).

비용 (gemini-2.5-flash-lite, 2026-06 기준):
  입력 $0.10/M, 출력 $0.40/M
  per request: ~74 input + ~72 output ≈ $0.000036
  384건 1회 백필 ≈ $0.014 (1.4센트)

환경변수:
  GEMINI_API_KEY (필수)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"country_house", "townhouse", "farm_house", "vacation_home"}

CATEGORY_SCHEMA = {
    "type": "object",
    "properties": {
        "categories": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": sorted(VALID_CATEGORIES),
            },
        },
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["categories", "confidence", "reason"],
}

PROMPT_TMPL = """한국 부동산 경매 매물 정보를 보고 derived_category 코드를 부여하세요.

분류 코드 (해당 없으면 빈 배열):
- country_house: 전원주택 — 도시 외곽·전원 분위기 (보통 군 단위)
- townhouse: 도심 단독 — 광역시·인구 50만+ 도심
- farm_house: 농가주택 — 단독 + 농가·축사·농어촌
- vacation_home: 별장·펜션·리조트·산장

매물:
- 용도: {usage_nm}
- 시도: {sd_name}
- 시군구: {sgg_name}
- 도로명: {road_addr}
- 지번: {lot_addr}
- 건물요약: {building_summary}
- 면적: {area_summary}
- 비고: {dspslGdsRmk}

규칙:
- 단독·다가구가 아니거나 정보 부족이면 categories: []
- 한 매물에 여러 카테고리 가능 (예: farm_house + country_house)
- confidence는 분류에 대한 자신도 0~1
- reason은 한 줄 한국어로 근거 명시
"""


@dataclass
class GeminiConfig:
    api_key: str | None = None
    model: str = "gemini-2.5-flash-lite"


class GeminiClassifier:
    def __init__(self, cfg: GeminiConfig | None = None):
        self.cfg = cfg or GeminiConfig()
        api_key = self.cfg.api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY required")
        self.client = genai.Client(api_key=api_key)
        self.input_tokens = 0
        self.output_tokens = 0
        self.requests = 0
        self.errors = 0

    def classify(
        self,
        prop: dict,
        *,
        sd_name: str = "",
        sgg_name: str = "",
        dspslGdsRmk: str = "",
    ) -> dict:
        """매물 1건 분류 호출.

        Returns:
            {"categories": list[str], "confidence": float, "reason": str}
            실패 시 categories=[] + reason 에 에러.
        """
        prompt = PROMPT_TMPL.format(
            usage_nm=prop.get("usage_nm") or "",
            sd_name=sd_name,
            sgg_name=sgg_name,
            road_addr=prop.get("road_addr") or "",
            lot_addr=prop.get("lot_addr") or "",
            building_summary=(prop.get("building_summary") or "")[:300],
            area_summary=prop.get("area_summary") or "",
            dspslGdsRmk=(dspslGdsRmk or "")[:300],
        )
        try:
            r = self.client.models.generate_content(
                model=self.cfg.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CATEGORY_SCHEMA,
                    temperature=0.0,
                ),
            )
            usage = getattr(r, "usage_metadata", None)
            if usage:
                self.input_tokens += getattr(usage, "prompt_token_count", 0) or 0
                self.output_tokens += getattr(usage, "candidates_token_count", 0) or 0
            self.requests += 1

            text = (r.text or "").strip() or "{}"
            out = json.loads(text)
            cats = [c for c in (out.get("categories") or []) if c in VALID_CATEGORIES]
            return {
                "categories": cats,
                "confidence": float(out.get("confidence", 0.5) or 0.5),
                "reason": str(out.get("reason", ""))[:200],
            }
        except Exception as e:
            self.errors += 1
            logger.warning("Gemini classify failed: %s", e)
            return {"categories": [], "confidence": 0.0, "reason": f"error: {e}"}

    def cost_estimate(self) -> dict:
        """2026-06 기준 Gemini 2.5 Flash Lite 단가 ($0.10 / $0.40 per M tokens)."""
        cost = (self.input_tokens * 0.10 + self.output_tokens * 0.40) / 1_000_000
        return {
            "requests": self.requests,
            "errors": self.errors,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(cost, 6),
        }


# ============================================================================
# 일본 BIT 매물 분류기 — bit/derived_category.py 카테고리와 동기화
# ============================================================================

JP_VALID_CATEGORIES = {"bessou", "akiya", "rizoto", "tousho"}

JP_CATEGORY_SCHEMA = {
    "type": "object",
    "properties": {
        "categories": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": sorted(JP_VALID_CATEGORIES),
            },
        },
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["categories", "confidence", "reason"],
}

JP_PROMPT_TMPL = """日本の不動産競売物件の派生カテゴリを分類してください。

カテゴリ (該当なしは空配列):
- bessou: 別荘·山荘·リゾート·別邸
- akiya: 空き家·古民家·中古戸建·廃屋
- rizoto: リゾート地 (北海道·沖縄·軽井沢·箱根·熱海など休養地)
- tousho: 離島 (沖縄県·離島)

物件情報:
- sale_cls: {sale_cls_label} (1=土地 / 2=戸建て / 3=マンション / 4=その他)
- 都道府県: {pref_name} (code={pref_code})
- 住所: {address_text}
- 売却基準価額: {sale_standard_price} 円

ルール:
- 戸建て(sale_cls=2)以外は通常 categories: [] (沖縄=tousho は例外)
- 一つの物件に複数カテゴリ可能 (例: bessou + rizoto)
- confidence は 0~1
- reason は日本語で一行
"""


class GeminiJpClassifier:
    """일본 매물 derived_category 분류기. 한국 GeminiClassifier 와 동일 구조,
    카테고리와 프롬프트만 일본어로."""

    def __init__(self, cfg: GeminiConfig | None = None):
        self.cfg = cfg or GeminiConfig()
        api_key = self.cfg.api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY required")
        self.client = genai.Client(api_key=api_key)
        self.input_tokens = 0
        self.output_tokens = 0
        self.requests = 0
        self.errors = 0

    def classify(self, prop: dict, *, pref_name: str = "") -> dict:
        """일본 매물 1건 분류."""
        prompt = JP_PROMPT_TMPL.format(
            sale_cls_label=prop.get("sale_cls_label") or prop.get("sale_cls") or "",
            pref_name=pref_name,
            pref_code=prop.get("prefecture_code") or "",
            address_text=(prop.get("address_text") or "")[:300],
            sale_standard_price=prop.get("sale_standard_price") or "",
        )
        try:
            r = self.client.models.generate_content(
                model=self.cfg.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=JP_CATEGORY_SCHEMA,
                    temperature=0.0,
                ),
            )
            usage = getattr(r, "usage_metadata", None)
            if usage:
                self.input_tokens += getattr(usage, "prompt_token_count", 0) or 0
                self.output_tokens += getattr(usage, "candidates_token_count", 0) or 0
            self.requests += 1
            text = (r.text or "").strip() or "{}"
            out = json.loads(text)
            cats = [c for c in (out.get("categories") or []) if c in JP_VALID_CATEGORIES]
            return {
                "categories": cats,
                "confidence": float(out.get("confidence", 0.5) or 0.5),
                "reason": str(out.get("reason", ""))[:200],
            }
        except Exception as e:
            self.errors += 1
            logger.warning("Gemini JP classify failed: %s", e)
            return {"categories": [], "confidence": 0.0, "reason": f"error: {e}"}

    def cost_estimate(self) -> dict:
        cost = (self.input_tokens * 0.10 + self.output_tokens * 0.40) / 1_000_000
        return {
            "requests": self.requests,
            "errors": self.errors,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(cost, 6),
        }
