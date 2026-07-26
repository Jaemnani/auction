"""
MOLIT 실거래가·건축물대장 Supabase 적재 레이어.

courtauction Store 와 분리(도메인 다름) — supabase 클라이언트 생성 패턴만 동일.
실거래가는 (deal_type, lawd_cd, deal_ymd) 단위 delete+insert 교체 (자연키 없음),
수집 상태는 molit_fetch_log 로 관리.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from supabase import Client, create_client

logger = logging.getLogger(__name__)

# usage_nm(courtauction 한글 용도명) → MOLIT deal_type.
# 웹 inferMolitType(p/[docid]/page.tsx) 휴리스틱의 서버측 단순화 —
# sgg 단위 수집 유형 결정용이라 매물 단위 정밀도는 불필요.
_USAGE_NM_TO_TYPE: list[tuple[re.Pattern, str]] = [
    (re.compile(r"공장|창고"), "indu"),
    (re.compile(r"근린|상가"), "nrg"),
    (re.compile(r"오피스텔"), "offi"),
    (re.compile(r"단독|다가구"), "sh"),
    (re.compile(r"연립|다세대|빌라"), "rh"),
    (re.compile(r"아파트"), "apt"),
    (re.compile(r"대지|전답|임야"), "land"),
]


def usage_nm_to_deal_type(usage_nm: str | None, usage_lcl_cd: str | None) -> str | None:
    if usage_lcl_cd == "10000":
        return "land"
    if usage_lcl_cd in ("30000", "40000"):  # 차량/기타 — 실거래 대응 없음
        return None
    for pat, t in _USAGE_NM_TO_TYPE:
        if usage_nm and pat.search(usage_nm):
            return t
    return None


class MolitStore:
    def __init__(self) -> None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL / SUPABASE_(SERVICE_)KEY env required")
        self.sb: Client = create_client(url, key)

    # ---------- 수집 대상 도출 ----------

    def active_region_types(self) -> dict[str, set[str]]:
        """활성 매물이 있는 lawd_cd(5자리) → 수집할 deal_type 집합.

        properties(deleted_at null)를 페이징으로 훑어 (sd+sgg)별 용도 유형을 유도.
        apt 는 지역 시세 기준선으로 항상 포함.
        """
        out: dict[str, set[str]] = {}
        offset, PAGE = 0, 1000
        while True:
            r = (self.sb.table("properties")
                 .select("sd_code, sgg_code, usage_lcl_cd, usage_nm")
                 .is_("deleted_at", "null")
                 .not_.is_("sd_code", "null")
                 .not_.is_("sgg_code", "null")
                 .order("id")
                 .range(offset, offset + PAGE - 1)
                 .execute())
            rows = r.data or []
            for row in rows:
                lawd = f"{row['sd_code']}{row['sgg_code']}"
                if len(lawd) != 5:
                    continue
                types = out.setdefault(lawd, {"apt"})
                t = usage_nm_to_deal_type(row.get("usage_nm"), row.get("usage_lcl_cd"))
                if t:
                    types.add(t)
            if len(rows) < PAGE:
                break
            offset += PAGE
        return out

    def fetch_log_map(self) -> dict[tuple[str, str, str], str]:
        """(deal_type, lawd_cd, deal_ymd) → fetched_at ISO. 전량 페이징 로드."""
        out: dict[tuple[str, str, str], str] = {}
        offset, PAGE = 0, 1000
        while True:
            r = (self.sb.table("molit_fetch_log")
                 .select("deal_type, lawd_cd, deal_ymd, fetched_at")
                 .order("deal_type").order("lawd_cd").order("deal_ymd")
                 .range(offset, offset + PAGE - 1)
                 .execute())
            rows = r.data or []
            for row in rows:
                out[(row["deal_type"], row["lawd_cd"], row["deal_ymd"])] = row["fetched_at"]
            if len(rows) < PAGE:
                break
            offset += PAGE
        return out

    # ---------- 실거래가 저장 ----------

    def replace_deals(self, deal_type: str, lawd_cd: str, deal_ymd: str,
                      rows: list[dict[str, Any]]) -> int:
        """(조합) 단위 교체 저장 + fetch_log 갱신."""
        (self.sb.table("molit_deals")
         .delete()
         .eq("deal_type", deal_type).eq("lawd_cd", lawd_cd).eq("deal_ymd", deal_ymd)
         .execute())
        n = 0
        payload = [{**r, "deal_type": deal_type, "lawd_cd": lawd_cd,
                    "deal_ymd": deal_ymd} for r in rows]
        CHUNK = 200
        for i in range(0, len(payload), CHUNK):
            self.sb.table("molit_deals").insert(payload[i:i + CHUNK]).execute()
            n += len(payload[i:i + CHUNK])
        now_iso = datetime.now(timezone.utc).isoformat()
        (self.sb.table("molit_fetch_log")
         .upsert({"deal_type": deal_type, "lawd_cd": lawd_cd, "deal_ymd": deal_ymd,
                  "row_count": n, "fetched_at": now_iso})
         .execute())
        return n

    # ---------- 건축물대장 ----------

    def br_candidates(self, limit: int) -> list[dict[str, Any]]:
        """건축물대장 미수집 활성 건물 매물.

        anti-join 이 PostgREST 로 불가 → 후보 페이지를 뽑고 이미 수집된
        property_id 를 배치 조회로 제외. error 는 30일 지나면 재시도.
        """
        retry_before = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        out: list[dict[str, Any]] = []
        offset, PAGE = 0, 500
        while len(out) < limit:
            r = (self.sb.table("properties")
                 .select("id, sd_code, sgg_code, emd_code, lot_no, lot_addr")
                 .is_("deleted_at", "null")
                 .eq("usage_lcl_cd", "20000")
                 .not_.is_("emd_code", "null")
                 .not_.is_("lot_no", "null")
                 .not_.is_("sd_code", "null")
                 .not_.is_("sgg_code", "null")
                 .order("id")
                 .range(offset, offset + PAGE - 1)
                 .execute())
            rows = r.data or []
            if not rows:
                break
            ids = [row["id"] for row in rows]
            skip: set[str] = set()
            # uuid .in_() 은 150개 초과 시 nginx 414 (close_aged 실측과 동일 임계)
            for i in range(0, len(ids), 150):
                ex = (self.sb.table("property_building_register")
                      .select("property_id, fetch_status, fetched_at")
                      .in_("property_id", ids[i:i + 150])
                      .execute())
                for e in ex.data or []:
                    if e["fetch_status"] in ("ok", "not_found"):
                        skip.add(e["property_id"])
                    elif e["fetched_at"] and e["fetched_at"] > retry_before:
                        skip.add(e["property_id"])  # error 30일 미경과
            out.extend(row for row in rows if row["id"] not in skip)
            if len(rows) < PAGE:
                break
            offset += PAGE
        return out[:limit]

    def upsert_br(self, property_id: str, payload: dict[str, Any]) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        self.sb.table("property_building_register").upsert(
            {**payload, "property_id": property_id, "fetched_at": now_iso}
        ).execute()
