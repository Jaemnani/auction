"""
BIT (不動産競売物件情報サイト, https://www.bit.courts.go.jp) 크롤러.

한국 courtauction의 일본 대응 사이트. 같은 데이터 모델을 가지지만 별도 테이블
(jp_courts / jp_cases / jp_properties / ...)에 적재.

Status: 1차 구현 완료 (검색 흐름) / 매물 상세 응답 파싱은 미완.
참고: docs/bit_api_recon.md, docs/jp_schema_design.md, docs/jp_market_analysis.md
"""

from .client import (
    BIT_BASE_URL,
    BitClient,
    BitClientConfig,
    BitError,
    BitParseError,
    BitPermanentError,
    BitTransientError,
    parse_search_result,
    parse_detail,
)
from .store import BitStore, BitStoreConfig, JP_PHOTO_BUCKET

__all__ = [
    "BIT_BASE_URL",
    "BitClient",
    "BitClientConfig",
    "BitError",
    "BitParseError",
    "BitPermanentError",
    "BitTransientError",
    "BitStore",
    "BitStoreConfig",
    "JP_PHOTO_BUCKET",
    "parse_search_result",
    "parse_detail",
]
