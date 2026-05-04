"""
Supabase 적재 레이어.

- masters (courts / regions_sd|sgg|emd / usage_codes) upsert
- search row → cases + properties upsert (자연키: court_code+case_no, case_id+maemul_ser)
- detail dma_result → properties.detail_result + property_sale_dates + property_photos
- csPicLst[].picFile (base64) → Supabase Storage(`auction-photos`) 업로드 + storage_path 저장
- 모든 upsert는 멱등 — 같은 자연키 재호출 시 last_synced_at만 갱신

기본은 SUPABASE_SERVICE_KEY를 쓰고, 없으면 SUPABASE_KEY(anon).
RLS가 꺼져있어도 anon은 grant에 따라 write가 막힐 수 있으니 적재는 service key 권장.
"""

from __future__ import annotations

import base64
import binascii
import io
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from supabase import Client, create_client

try:
    from PIL import Image  # type: ignore
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

try:
    import pyproj  # type: ignore
    # courtauction은 KATEC (구 한국표준): TM, 중부원점 128°, false E=400000, N=600000, bessel
    _KATEC_PROJ = (
        "+proj=tmerc +lat_0=38 +lon_0=128 +k=0.9999 "
        "+x_0=400000 +y_0=600000 +ellps=bessel "
        "+towgs84=-146.43,507.89,681.46,0,0,0,0 +units=m"
    )
    _KATEC_TO_WGS84 = pyproj.Transformer.from_crs(
        _KATEC_PROJ, "EPSG:4326", always_xy=True,
    )
    _HAS_PYPROJ = True
except Exception:
    _KATEC_TO_WGS84 = None
    _HAS_PYPROJ = False

PHOTO_BUCKET = "auction-photos"
THUMB_PREFIX = "thumbs/"
THUMB_MAX = (320, 240)
THUMB_QUALITY = 80


def katec_to_wgs84(x: Any, y: Any) -> tuple[float, float] | None:
    """KATEC (xCordi, yCordi) → (longitude, latitude). 변환 실패 시 None.

    한국 영토 범위(124°<=lng<=132°, 33°<=lat<=39°)를 벗어나면 None 반환.
    """
    if not _HAS_PYPROJ or _KATEC_TO_WGS84 is None:
        return None
    fx = _to_float(x); fy = _to_float(y)
    if fx is None or fy is None:
        return None
    if fx < 100000 or fy < 100000:  # 0이거나 비정상치
        return None
    lng, lat = _KATEC_TO_WGS84.transform(fx, fy)
    if not (124.0 <= lng <= 132.5 and 33.0 <= lat <= 39.0):
        return None
    return (lng, lat)

logger = logging.getLogger(__name__)


# ---------- helpers ----------

def _to_int(v: Any) -> int | None:
    if v in (None, "", "null"):
        return None
    try:
        return int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> float | None:
    if v in (None, "", "null"):
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _to_date(v: Any) -> str | None:
    """YYYYMMDD or YYYY-MM-DD → ISO date string. 빈/잘못된 값은 None."""
    if v in (None, "", "null"):
        return None
    s = str(v).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    return None


def _str(v: Any) -> str | None:
    if v in (None, ""):
        return None
    return str(v).strip() or None


def _chunked(seq: list, size: int) -> Iterable[list]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _clean_addr(s: Any) -> str | None:
    """courtauction 주소 형식 정리.

    예: '서울특별시 관악구 신림로31가길 00005-00000' → '서울특별시 관악구 신림로31가길 5'
        '서울특별시 동작구 여의대방로36길 00020-00001' → '서울특별시 동작구 여의대방로36길 20-1'
    - 0-padded 숫자 정규화
    - 부번호가 0뿐이면 제거 (5-0 → 5)
    """
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    # 00005 → 5 (단어경계 내 leading zeros)
    s = re.sub(r"\b0+(\d+)", r"\1", s)
    # -0 또는 -0000 처럼 부번호가 0뿐이면 제거
    s = re.sub(r"-0+\b", "", s)
    # 다중 공백 정리
    s = re.sub(r"\s+", " ", s)
    return s.strip() or None


def _lnglat_payload(row: dict) -> dict:
    """search row → {longitude, latitude} payload (KATEC 우선, 실패시 wgs84 정수)."""
    katec = katec_to_wgs84(row.get("xCordi"), row.get("yCordi"))
    if katec:
        return {"longitude": katec[0], "latitude": katec[1]}
    # fallback: 정수로 잘린 wgs84*Cordi (정확도 낮음)
    fx = _to_float(row.get("wgs84Xcordi"))
    fy = _to_float(row.get("wgs84Ycordi"))
    if fx and fy and 124 <= fx <= 132 and 33 <= fy <= 39:
        return {"longitude": fx, "latitude": fy}
    return {}


def _guess_content_type(filename: Any) -> str:
    if not filename or not isinstance(filename, str):
        return "image/jpeg"
    low = filename.lower()
    if low.endswith(".png"): return "image/png"
    if low.endswith(".webp"): return "image/webp"
    if low.endswith(".gif"): return "image/gif"
    return "image/jpeg"


# ---------- store ----------

@dataclass
class StoreConfig:
    url: str
    key: str
    chunk_size: int = 200


class Store:
    """Supabase upsert wrapper. 기본 chunk_size=200으로 분할 호출."""

    def __init__(self, cfg: StoreConfig | None = None) -> None:
        if cfg is None:
            url = os.environ.get("SUPABASE_URL")
            key = (
                os.environ.get("SUPABASE_SERVICE_KEY")
                or os.environ.get("SUPABASE_KEY")
            )
            if not url or not key:
                raise RuntimeError("SUPABASE_URL / SUPABASE_(SERVICE_)KEY env required")
            cfg = StoreConfig(url=url, key=key)
        self.cfg = cfg
        self.sb: Client = create_client(cfg.url, cfg.key)

    # ---------- masters ----------

    def upsert_courts(self, rows: list[dict]) -> int:
        """rows: seed.py masters의 'court' 레코드들 ({prefix, code, name, ...})."""
        out: list[dict] = []
        for r in rows:
            code = _str(r.get("code") or r.get("cortOfcCd"))
            name = _str(r.get("name") or r.get("cortOfcNm"))
            prefix = _str(r.get("prefix"))
            if not code or not name or not prefix:
                continue
            # prefix가 "00079B"면 마지막 글자만 (B/O)
            p = prefix[-1] if prefix and prefix[-1] in ("B", "O") else prefix
            out.append({"code": code, "prefix": p, "name": name, "raw": r})
        return self._upsert_chunked("courts", out, on_conflict="code")

    def upsert_regions_sd(self, rows: list[dict]) -> int:
        out = [
            {"code": _str(r.get("code") or r.get("adongSdCd")),
             "name": _str(r.get("name") or r.get("adongSdNm")),
             "raw": r}
            for r in rows
        ]
        out = [r for r in out if r["code"] and r["name"]]
        return self._upsert_chunked("regions_sd", out, on_conflict="code")

    def upsert_regions_sgg(self, rows: list[dict]) -> int:
        out = []
        for r in rows:
            code = _str(r.get("code") or r.get("adongSggCd"))
            sd_code = _str(r.get("sd_code") or r.get("adongSdCd"))
            name = _str(r.get("name") or r.get("adongSggNm"))
            if not (code and sd_code and name):
                continue
            out.append({"code": code, "sd_code": sd_code, "name": name, "raw": r})
        # 복합키 (sd_code, code) — sgg 3자리는 sd 내에서만 unique
        return self._upsert_chunked("regions_sgg", out, on_conflict="sd_code,code")

    def upsert_regions_emd(self, rows: list[dict]) -> int:
        out = []
        for r in rows:
            code = _str(r.get("code") or r.get("adongEmdCd"))
            sgg_code = _str(r.get("sgg_code") or r.get("adongSggCd"))
            sd_code = _str(r.get("sd_code") or r.get("adongSdCd"))
            name = _str(r.get("name") or r.get("adongEmdNm"))
            if not (code and sgg_code and sd_code and name):
                continue
            out.append({"code": code, "sgg_code": sgg_code,
                        "sd_code": sd_code, "name": name, "raw": r})
        return self._upsert_chunked("regions_emd", out, on_conflict="code")

    def upsert_usage_codes(self, rows: list[dict]) -> int:
        """rows의 type ∈ {usage_lcl, usage_mcl, usage_scl}로 level/parent 결정."""
        out = []
        for r in rows:
            t = r.get("type")
            level = {"usage_lcl": 1, "usage_mcl": 2, "usage_scl": 3}.get(t)
            if not level:
                continue
            code = _str(r.get("code") or r.get("dspslGdsLstUsgCd"))
            name = _str(r.get("name") or r.get("dspslGdsLstUsgNm"))
            if not (code and name):
                continue
            parent = (
                _str(r.get("mcl_code")) if level == 3
                else _str(r.get("lcl_code")) if level == 2
                else None
            )
            out.append({"code": code, "level": level,
                        "parent_code": parent, "name": name, "raw": r})
        return self._upsert_chunked("usage_codes", out, on_conflict="code")

    # ---------- search row → cases + properties ----------

    def upsert_search_row(self, row: dict) -> dict:
        """검색 결과 한 row를 cases + properties로 분리 upsert.

        반환: {"case_id": uuid, "property_id": uuid}.
        """
        court_code = _str(row.get("boCd") or row.get("cortOfcCd"))
        case_no = _str(row.get("srnSaNo"))
        if not court_code or not case_no:
            raise ValueError(f"row missing boCd/srnSaNo: {row}")

        # 1) cases upsert (court_code+case_no UNIQUE)
        case_payload = {
            "court_code": court_code,
            "case_no": case_no,
            "sa_no": _str(row.get("saNo")),
            "case_name": _str(row.get("saMyung") or row.get("csNm")),
            "jdbn_cd": _str(row.get("jdbnCd")),
            "jdbn_name": _str(row.get("jpDeptNm") or row.get("jdbnNm")),
            "tel": _str(row.get("tel")),
            "is_real_estate": True,  # search kind=real_estate라고 가정
            "last_synced_at": datetime.utcnow().isoformat(),
        }
        case_payload = {k: v for k, v in case_payload.items() if v is not None}
        self.sb.table("cases").upsert(
            case_payload, on_conflict="court_code,case_no",
        ).execute()
        case = (
            self.sb.table("cases")
            .select("id")
            .eq("court_code", court_code)
            .eq("case_no", case_no)
            .single()
            .execute()
        )
        case_id = case.data["id"]

        # 2) properties upsert (case_id+maemul_ser UNIQUE)
        maemul_ser = _to_int(row.get("maemulSer")) or 1
        prop_payload = {
            "case_id": case_id,
            "maemul_ser": maemul_ser,
            "mokmul_ser": _to_int(row.get("mokmulSer")),
            "docid": _str(row.get("docid")),
            "appraisal_amount": _to_int(row.get("gamevalAmt")),
            "min_sale_price": _to_int(row.get("minmaePrice")),
            "current_sale_price": _to_int(row.get("currentMaemaePrice")
                                          or row.get("maemaePrice")),
            "fail_count": _to_int(row.get("yuchalCnt")),
            "sale_date": _to_date(row.get("maeGiil")),
            "sale_decision_date": _to_date(row.get("maegyuljGiil")),
            "status_cd": _str(row.get("maemulStatCd") or row.get("statCd")),
            "usage_lcl_cd": _str(row.get("lclsUtilCd")),
            "usage_mcl_cd": _str(row.get("mclsUtilCd")),
            "usage_scl_cd": _str(row.get("sclsUtilCd")),
            "sd_code": _str(row.get("daepyoSidoCd")),
            "sgg_code": _str(row.get("daepyoSiguCd") or row.get("daepyoSggCd")),
            "emd_code": _str(row.get("daepyoDongCd") or row.get("daepyoEmdCd")),
            "rd_code": _str(row.get("daepyoRdCd")),
            "lot_no": _str(row.get("daepyoLotno")),
            "conv_addr": _str(row.get("convAddr") or row.get("daepyoAddr")),
            "road_addr": _clean_addr(row.get("bgPlaceRdAllAddr")
                                     or row.get("rdAllAddr")),
            "lot_addr": _clean_addr(row.get("bgPlaceLotAllAddr")
                                    or row.get("lotAllAddr")),
            "building_summary": _str(row.get("buldList")),
            "area_summary": _str(row.get("areaList")),
            # courtauction의 wgs84*Cordi는 정수로 잘려서 옴 (오차 km 단위)
            # → xCordi/yCordi (KATEC) 변환을 우선 사용
            **(_lnglat_payload(row)),
            "search_row": row,
            "last_synced_at": datetime.utcnow().isoformat(),
        }
        prop_payload = {k: v for k, v in prop_payload.items() if v is not None}
        self.sb.table("properties").upsert(
            prop_payload, on_conflict="case_id,maemul_ser",
        ).execute()
        prop = (
            self.sb.table("properties")
            .select("id")
            .eq("case_id", case_id)
            .eq("maemul_ser", maemul_ser)
            .single()
            .execute()
        )
        return {"case_id": case_id, "property_id": prop.data["id"]}

    def upsert_sale_results(self, rows: list[dict]) -> int:
        """매각결과검색 row → sale_results 테이블에 일괄 upsert.

        search row와 같은 키 구조 + maeAmt(실제 낙찰가) + inqCnt(응찰자 수).
        """
        if not rows:
            return 0
        out: list[dict] = []
        for r in rows:
            docid = _str(r.get("docid"))
            if not docid:
                continue
            payload = {
                "docid": docid,
                "court_code": _str(r.get("boCd") or r.get("cortOfcCd")),
                "case_no": _str(r.get("srnSaNo")),
                "maemul_ser": _to_int(r.get("maemulSer")) or 1,
                "appraisal_amount": _to_int(r.get("gamevalAmt")),
                "min_sale_price": _to_int(r.get("minmaePrice")),
                "sale_amount": _to_int(r.get("maeAmt")),
                "fail_count": _to_int(r.get("yuchalCnt")),
                "bidder_count": _to_int(r.get("inqCnt")),
                "sale_date": _to_date(r.get("maeGiil")),
                "result_status_cd": _str(r.get("mulStatcd")),
                "in_progress_yn": _str(r.get("mulJinYn")),
                "usage_lcl_cd": _str(r.get("lclsUtilCd")),
                "usage_mcl_cd": _str(r.get("mclsUtilCd")),
                "usage_scl_cd": _str(r.get("sclsUtilCd")),
                "sd_code": _str(r.get("daepyoSidoCd")),
                "sgg_code": _str(r.get("daepyoSiguCd") or r.get("daepyoSggCd")),
                "emd_code": _str(r.get("daepyoDongCd") or r.get("daepyoEmdCd")),
                "conv_addr": _str(r.get("convAddr") or r.get("daepyoAddr")),
                "road_addr": _clean_addr(r.get("bgPlaceRdAllAddr") or r.get("rdAllAddr")),
                "building_summary": _str(r.get("buldList")),
                **(_lnglat_payload(r)),
                "raw": r,
                "fetched_at": datetime.utcnow().isoformat(),
            }
            payload = {k: v for k, v in payload.items() if v is not None}
            out.append(payload)
        # docid dedupe (last-wins) within same batch
        seen: dict[str, dict] = {}
        for p in out:
            seen[p["docid"]] = p
        deduped = list(seen.values())
        if not deduped:
            return 0
        for chunk in _chunked(deduped, 50):
            self.sb.table("sale_results").upsert(
                chunk, on_conflict="docid", returning="minimal",
            ).execute()
        return len(deduped)

    def upsert_search_rows(self, rows: list[dict]) -> int:
        """진짜 배치 — 페이지(50개) 전체를 2~3 round-trip으로 처리.

        흐름:
          1) 모든 row에서 (court_code, case_no) 유니크 추출 → cases 일괄 upsert (returning=ids)
          2) 그 응답으로 (court+case_no → case_id) 맵 구성
          3) 모든 row를 properties payload로 변환 → 일괄 upsert
        """
        if not rows:
            return 0

        # 1) cases dedupe + 일괄 upsert
        case_seen: dict[tuple[str, str], dict] = {}
        for r in rows:
            court = _str(r.get("boCd") or r.get("cortOfcCd"))
            case_no = _str(r.get("srnSaNo"))
            if not court or not case_no:
                continue
            payload = {
                "court_code": court,
                "case_no": case_no,
                "sa_no": _str(r.get("saNo")),
                "case_name": _str(r.get("saMyung") or r.get("csNm")),
                "jdbn_cd": _str(r.get("jdbnCd")),
                "jdbn_name": _str(r.get("jpDeptNm") or r.get("jdbnNm")),
                "tel": _str(r.get("tel")),
                "is_real_estate": True,
                "last_synced_at": datetime.utcnow().isoformat(),
            }
            case_seen[(court, case_no)] = {k: v for k, v in payload.items() if v is not None}

        if not case_seen:
            return 0

        case_resp = (
            self.sb.table("cases")
            .upsert(list(case_seen.values()), on_conflict="court_code,case_no")
            .execute()
        )
        # supabase upsert with default returning=representation gives back id+row
        case_map: dict[tuple[str, str], str] = {}
        for c in case_resp.data or []:
            case_map[(c["court_code"], c["case_no"])] = c["id"]

        # supabase가 가끔 inserted/updated row를 모두 안 돌려줌 — 누락 분은 select로 채움
        missing_keys = [k for k in case_seen if k not in case_map]
        if missing_keys:
            for court, case_no in missing_keys:
                r = (
                    self.sb.table("cases").select("id")
                    .eq("court_code", court).eq("case_no", case_no)
                    .single().execute()
                )
                case_map[(court, case_no)] = r.data["id"]

        # 2) properties payload 일괄 구성
        prop_payloads: list[dict] = []
        for r in rows:
            court = _str(r.get("boCd") or r.get("cortOfcCd"))
            case_no = _str(r.get("srnSaNo"))
            if not court or not case_no:
                continue
            case_id = case_map.get((court, case_no))
            if not case_id:
                continue
            maemul_ser = _to_int(r.get("maemulSer")) or 1
            payload = {
                "case_id": case_id,
                "maemul_ser": maemul_ser,
                "mokmul_ser": _to_int(r.get("mokmulSer")),
                "docid": _str(r.get("docid")),
                "appraisal_amount": _to_int(r.get("gamevalAmt")),
                "min_sale_price": _to_int(r.get("minmaePrice")),
                "current_sale_price": _to_int(r.get("currentMaemaePrice")
                                              or r.get("maemaePrice")),
                "fail_count": _to_int(r.get("yuchalCnt")),
                "sale_date": _to_date(r.get("maeGiil")),
                "sale_decision_date": _to_date(r.get("maegyuljGiil")),
                "status_cd": _str(r.get("maemulStatCd") or r.get("statCd")),
                "usage_lcl_cd": _str(r.get("lclsUtilCd")),
                "usage_mcl_cd": _str(r.get("mclsUtilCd")),
                "usage_scl_cd": _str(r.get("sclsUtilCd")),
                "sd_code": _str(r.get("daepyoSidoCd")),
                "sgg_code": _str(r.get("daepyoSiguCd") or r.get("daepyoSggCd")),
                "emd_code": _str(r.get("daepyoDongCd") or r.get("daepyoEmdCd")),
                "rd_code": _str(r.get("daepyoRdCd")),
                "lot_no": _str(r.get("daepyoLotno")),
                "conv_addr": _str(r.get("convAddr") or r.get("daepyoAddr")),
                "road_addr": _clean_addr(r.get("bgPlaceRdAllAddr") or r.get("rdAllAddr")),
                "lot_addr":  _clean_addr(r.get("bgPlaceLotAllAddr") or r.get("lotAllAddr")),
                "building_summary": _str(r.get("buldList")),
                "area_summary":     _str(r.get("areaList")),
                **(_lnglat_payload(r)),
                "search_row": r,
                "last_synced_at": datetime.utcnow().isoformat(),
            }
            prop_payloads.append({k: v for k, v in payload.items() if v is not None})

        if not prop_payloads:
            return 0

        # case_id+maemul_ser 중복 dedupe (last-wins)
        prop_seen: dict[tuple[str, int], dict] = {}
        for p in prop_payloads:
            prop_seen[(p["case_id"], p["maemul_ser"])] = p
        deduped = list(prop_seen.values())

        # 작은 chunk (search_row jsonb 큼 + GIST/trgm 인덱스 갱신 비용)
        # 25개씩 잘라서 timeout 회피 — 페이지(50) 기준 2 round-trip
        PROP_CHUNK = 25
        for chunk in _chunked(deduped, PROP_CHUNK):
            self.sb.table("properties").upsert(
                chunk, on_conflict="case_id,maemul_ser",
                returning="minimal",  # 응답에 row 데이터 포함하지 않음 → 빠름
            ).execute()
        return len(deduped)

    # 단건 호출은 호환용으로 유지
    def upsert_search_rows_loop(self, rows: list[dict]) -> int:
        n = 0
        for r in rows:
            try:
                self.upsert_search_row(r)
                n += 1
            except Exception as e:
                logger.warning("upsert_search_row failed: %s — row=%s", e, r.get("docid"))
        return n

    # ---------- detail dma_result → property fill + sale_dates + photos ----------

    def upsert_detail(self, court_code: str, case_no: str,
                      maemul_ser: int, dma_result: dict) -> str:
        """detail dma_result를 properties.detail_result + sale_dates + photos에 분배.

        반환: property_id.
        """
        # property 찾기 (이미 search 단계에서 upsert돼있어야 함)
        prop = (
            self.sb.table("properties")
            .select("id, case_id, cases!inner(court_code, case_no)")
            .eq("cases.court_code", court_code)
            .eq("cases.case_no", case_no)
            .eq("maemul_ser", maemul_ser)
            .limit(1)
            .execute()
        )
        if not prop.data:
            # search 없이 detail만 들어온 경우 — 최소 정보만으로 case/property 우선 생성
            cs_base = (dma_result.get("csBaseInfo") or {})
            self.sb.table("cases").upsert(
                {
                    "court_code": court_code,
                    "case_no": case_no,
                    "case_name": _str(cs_base.get("csNm")),
                    "is_real_estate": True,
                    "base_info": cs_base,
                    "last_synced_at": datetime.utcnow().isoformat(),
                },
                on_conflict="court_code,case_no",
            ).execute()
            case = (
                self.sb.table("cases").select("id")
                .eq("court_code", court_code).eq("case_no", case_no)
                .single().execute()
            )
            self.sb.table("properties").upsert(
                {"case_id": case["data"]["id"], "maemul_ser": maemul_ser},
                on_conflict="case_id,maemul_ser",
            ).execute()
            prop = (
                self.sb.table("properties")
                .select("id, case_id, cases!inner(court_code, case_no)")
                .eq("cases.court_code", court_code)
                .eq("cases.case_no", case_no)
                .eq("maemul_ser", maemul_ser)
                .limit(1)
                .execute()
            )
        property_id = prop.data[0]["id"]
        case_id = prop.data[0]["case_id"]

        # csBaseInfo는 cases.base_info에 통째 보존
        cs_base = dma_result.get("csBaseInfo") or {}
        if cs_base:
            cs_payload = {
                "base_info": cs_base,
                "claim_amount": _to_int(cs_base.get("clmAmt") or cs_base.get("claimAmt")),
                "receipt_date": _to_date(cs_base.get("rcptYmd") or cs_base.get("rcptDt")),
                "command_date": _to_date(cs_base.get("cmdYmd") or cs_base.get("cmdDt")),
                "last_synced_at": datetime.utcnow().isoformat(),
            }
            cs_payload = {k: v for k, v in cs_payload.items() if v is not None}
            if cs_payload:
                self.sb.table("cases").update(cs_payload).eq("id", case_id).execute()

        # properties.detail_result — 웹에서 쓰는 키만 발췌 (picFile base64 제외)
        # 매각기일/사진은 별도 테이블에 저장되므로 detail_result에서 제외
        slim_detail = {
            "csBaseInfo":         dma_result.get("csBaseInfo"),
            "dspslGdsDxdyInfo":   dma_result.get("dspslGdsDxdyInfo"),
            "aeeWevlMnpntLst":    dma_result.get("aeeWevlMnpntLst"),
            "rgltLandLstAll":     dma_result.get("rgltLandLstAll"),
            "bldSdtrDtlLstAll":   dma_result.get("bldSdtrDtlLstAll"),
            "gdsRletStLtnoLstAll": dma_result.get("gdsRletStLtnoLstAll"),
            "dstrtDemnInfo":      dma_result.get("dstrtDemnInfo"),
            "gdsDspslObjctLst":   dma_result.get("gdsDspslObjctLst"),
            "picDvsIndvdCnt":     dma_result.get("picDvsIndvdCnt"),
        }
        slim_detail = {k: v for k, v in slim_detail.items() if v not in (None, [], {})}
        self.sb.table("properties").update(
            {
                "detail_result": slim_detail,
                "detail_synced_at": datetime.utcnow().isoformat(),
                "last_synced_at": datetime.utcnow().isoformat(),
            }
        ).eq("id", property_id).execute()

        # 매각기일 이력
        sale_lst = dma_result.get("gdsDspslDxdyLst") or []
        if sale_lst:
            sale_rows = []
            for i, r in enumerate(sale_lst, start=1):
                sale_rows.append({
                    "property_id": property_id,
                    "seq": _to_int(r.get("seq") or r.get("dxdySeq")) or i,
                    "sale_date": _to_date(r.get("dxdyYmd") or r.get("saleYmd")
                                          or r.get("dspslYmd")),
                    "hour": _str(r.get("dxdyHm") or r.get("saleHm")),
                    "place": _str(r.get("dspslPlc") or r.get("plc")),
                    "min_price": _to_int(r.get("lwsDspslPrc") or r.get("minPrc")),
                    "result_cd": _str(r.get("dspslRsltCd") or r.get("rsltCd")),
                    "raw": r,
                })
            self.sb.table("property_sale_dates").upsert(
                sale_rows, on_conflict="property_id,seq",
            ).execute()

        # 사진 목록 — base64는 Storage에 업로드하고 raw에서 제외.
        # Supabase 무료 5GB 제한 안에 머물기 위해 매물당 첫 1장(대표사진)만.
        # 환경변수 PHOTOS_PER_PROPERTY로 override 가능 (0=비저장, ""=전체).
        max_per = os.environ.get("PHOTOS_PER_PROPERTY", "1")
        all_pics = dma_result.get("csPicLst") or []
        if max_per == "":
            pics = all_pics
        else:
            try:
                n = int(max_per)
                pics = all_pics[:n] if n > 0 else []
            except ValueError:
                pics = all_pics[:1]
        if pics:
            photo_rows = []
            for i, p in enumerate(pics, start=1):
                seq = _to_int(p.get("cortAuctnPicSeq") or p.get("picSeq") or p.get("seq")) or i
                pic_b64 = p.get("picFile")
                # raw에서 무거운 base64는 빼고 메타만 보존
                raw_meta = {k: v for k, v in p.items() if k != "picFile"}

                storage_path: str | None = None
                content_type = "image/jpeg"
                if pic_b64 and isinstance(pic_b64, str):
                    storage_path = self._photo_storage_path(
                        court_code, case_no, maemul_ser, seq,
                        title=p.get("picTitlNm"),
                    )
                    try:
                        self._upload_photo(
                            storage_path, pic_b64,
                            content_type=_guess_content_type(p.get("picTitlNm")),
                        )
                    except Exception as e:
                        logger.warning("photo upload failed (%s/%s seq=%d): %s",
                                       court_code, case_no, seq, e)
                        storage_path = None

                photo_rows.append({
                    "property_id": property_id,
                    "seq": seq,
                    "photo_kind_cd": _str(p.get("cortAuctnPicDvsCd")),
                    "photo_kind_name": _str(p.get("cortAuctnPicDvsNm")),
                    "description": _str(p.get("picDesc") or p.get("picTitlNm")),
                    "origin_cd": _str(p.get("orgnCd")),
                    "storage_path": storage_path,
                    "raw": raw_meta,
                })
            self.sb.table("property_photos").upsert(
                photo_rows, on_conflict="property_id,seq",
            ).execute()

        return property_id

    # ---------- Storage helpers ----------

    @staticmethod
    def _photo_storage_path(court: str, case_no: str, maemul_ser: int,
                            seq: int, *, title: str | None = None) -> str:
        """Supabase Storage 키는 ASCII만 허용 → '2023타경6292' → '2023-6292'.

        예: B000210/2023-6292/1/01.jpg
        """
        ext = ".jpg"
        if title and isinstance(title, str) and "." in title:
            cand = title.rsplit(".", 1)[-1].lower()
            if cand.isalnum() and len(cand) <= 5:
                ext = "." + cand
        # 한글 등 비-ASCII는 모두 '-'로 치환
        safe = "".join(
            c if (c.isalnum() and ord(c) < 128) or c in "-_." else "-"
            for c in case_no
        )
        # 연속 '-' 정리
        while "--" in safe:
            safe = safe.replace("--", "-")
        safe = safe.strip("-") or "x"
        return f"{court}/{safe}/{maemul_ser}/{seq:02d}{ext}"

    def _upload_photo(self, path: str, b64: str, *,
                      content_type: str = "image/jpeg") -> None:
        """원본 + 썸네일을 함께 Storage에 올린다.

        - path: 원본 키 (예: B000210/2023-6292/1/01.jpg)
        - 썸네일 키: thumbs/{path} (Pillow로 320×240 box-fit, JPEG q=80)
        """
        clean = b64.strip()
        if clean.startswith("data:"):
            clean = clean.split(",", 1)[1]
        try:
            blob = base64.b64decode(clean, validate=False)
        except (binascii.Error, ValueError) as e:
            raise ValueError(f"invalid base64: {e}") from e
        if len(blob) < 100:
            raise ValueError("decoded blob too small (<100 bytes)")

        # 1) 원본
        self.sb.storage.from_(PHOTO_BUCKET).upload(
            path=path,
            file=blob,
            file_options={"content-type": content_type, "upsert": "true"},
        )

        # 2) 썸네일 (실패해도 원본은 살아있어야 하므로 try-block)
        try:
            thumb_blob = self._make_thumb(blob)
            self.sb.storage.from_(PHOTO_BUCKET).upload(
                path=THUMB_PREFIX + path,
                file=thumb_blob,
                file_options={"content-type": "image/jpeg", "upsert": "true"},
            )
        except Exception as e:
            logger.warning("thumb gen/upload failed for %s: %s", path, e)

    @staticmethod
    def _make_thumb(blob: bytes) -> bytes:
        """원본 바이트 → JPEG 썸네일 바이트. Pillow 필수."""
        if not _HAS_PIL:
            raise RuntimeError("Pillow not available — cannot make thumbnail")
        with Image.open(io.BytesIO(blob)) as im:
            im.load()
            # EXIF 회전 보정
            try:
                from PIL import ImageOps  # type: ignore
                im = ImageOps.exif_transpose(im)
            except Exception:
                pass
            if im.mode in ("RGBA", "P", "LA"):
                im = im.convert("RGB")
            im.thumbnail(THUMB_MAX, Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=THUMB_QUALITY,
                    optimize=True, progressive=True)
            return buf.getvalue()

    def public_photo_url(self, storage_path: str) -> str:
        return self.sb.storage.from_(PHOTO_BUCKET).get_public_url(storage_path)

    def public_thumb_url(self, storage_path: str) -> str:
        return self.sb.storage.from_(PHOTO_BUCKET).get_public_url(
            THUMB_PREFIX + storage_path)

    # ---------- crawl runs / dead letters ----------

    def start_run(self, job_type: str, params: dict | None = None) -> str:
        r = self.sb.table("crawl_runs").insert(
            {"job_type": job_type, "params": params or {}, "status": "running"}
        ).execute()
        return r.data[0]["id"]

    def finish_run(self, run_id: str, totals: dict | None = None,
                   *, status: str = "done", error: str | None = None) -> None:
        self.sb.table("crawl_runs").update(
            {"status": status, "totals": totals or {},
             "finished_at": datetime.utcnow().isoformat(), "error": error}
        ).eq("id", run_id).execute()

    # ---------- internal ----------

    def _upsert_chunked(self, table: str, rows: list[dict], *,
                        on_conflict: str) -> int:
        if not rows:
            return 0
        # 같은 chunk 내 중복 conflict key 제거 (last-wins)
        keys = [k.strip() for k in on_conflict.split(",")]
        seen: dict[tuple, dict] = {}
        for r in rows:
            key = tuple(r.get(k) for k in keys)
            seen[key] = r
        deduped = list(seen.values())
        n = 0
        for chunk in _chunked(deduped, self.cfg.chunk_size):
            self.sb.table(table).upsert(chunk, on_conflict=on_conflict).execute()
            n += len(chunk)
        logger.info("upsert %s: %d rows (input=%d, dedup=%d)",
                    table, n, len(rows), len(deduped))
        return n
