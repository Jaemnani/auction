"""주소 → 좌표 정지오코딩 (Kakao Local) + 파일 캐시.

부산·경기 정비사업 API 는 좌표 없이 주소만 주므로 대표 위치 점 표시용으로
지오코딩한다. build 마다 재호출하지 않도록 결과(실패 포함)를 파일 캐시.

정밀도 등급을 함께 반환한다 — 소멸 지번("~번지 일원" 등)은 필지 단위가 안
잡혀서 동 단위로 폴백하는데, 그 사실을 숨기지 않고 feature 에 표기한다
(날조 금지 — 동 중심점을 정확한 위치처럼 보이게 하지 않는다).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import httpx

CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "redev_geocode_cache.json"

_API = "https://dapi.kakao.com/v2/local/search/address.json"
_MIN_INTERVAL_S = 0.12
_last_call = 0.0

_cache: dict[str, dict] | None = None


def _load_cache() -> dict[str, dict]:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_PATH.read_text())
        except (OSError, ValueError):
            _cache = {}
    return _cache


def save_cache() -> None:
    if _cache is not None:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(_cache, ensure_ascii=False, indent=0))


def clean_address(addr: str) -> str:
    """API 주소 표기의 부가 텍스트 제거 — '번지 일원', '외 N필지', 상세층 등."""
    s = (addr or "").strip()
    s = s.split(",")[0]                                # "…대로 6, 3층(구서동)" → 앞부분
    s = re.sub(r"\([^)]*\)", " ", s)                   # 괄호 주기
    s = re.sub(r"(번지)?\s*(일원|일대|외\s*\d*\s*필지?)\s*$", "", s)
    s = re.sub(r"번지\s*$", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _query(client: httpx.Client, api_key: str, q: str) -> tuple[float, float] | None:
    global _last_call
    for attempt in range(3):
        wait = _MIN_INTERVAL_S - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
        try:
            r = client.get(_API, params={"query": q},
                           headers={"Authorization": f"KakaoAK {api_key}"}, timeout=15)
            r.raise_for_status()
            break
        except (httpx.TransportError, httpx.HTTPStatusError):
            # keep-alive 연결이 서버측에서 끊기는 경우가 있어 짧게 쉬고 재시도
            if attempt == 2:
                raise
            time.sleep(1.0 * (attempt + 1))
    docs = r.json().get("documents", [])
    if not docs:
        return None
    return float(docs[0]["x"]), float(docs[0]["y"])


def geocode(client: httpx.Client, addr: str, *, api_key: str | None = None,
            ) -> dict | None:
    """주소 → {lng, lat, precision}. 실패 시 None (실패도 캐시).

    precision: "parcel"(정제 주소 그대로) / "dong"(지번 소멸 등으로 동 단위 폴백).
    """
    api_key = api_key or os.environ.get("KAKAO_REST_API_KEY")
    if not api_key:
        raise RuntimeError("KAKAO_REST_API_KEY env required")
    q = clean_address(addr)
    if not q:
        return None
    cache = _load_cache()
    if q in cache:
        hit = cache[q]
        return hit or None
    result: dict | None = None
    pt = _query(client, api_key, q)
    if pt:
        result = {"lng": pt[0], "lat": pt[1], "precision": "parcel"}
    else:
        # 지번 소멸(재건축 완료로 대지 개편 등) — 지번을 떼고 동/도로명까지로 폴백
        fallback = re.sub(r"\s+\d+[-\d]*\s*$", "", q)
        if fallback != q and len(fallback.split()) >= 2:
            pt = _query(client, api_key, fallback)
            if pt:
                result = {"lng": pt[0], "lat": pt[1], "precision": "dong"}
    cache[q] = result or {}
    return result
