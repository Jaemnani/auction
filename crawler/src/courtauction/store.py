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


# 용도 코드 정규화 — courtauction이 일부 매물에서 보내는 무효 값을 NULL로.
# 예: 어떤 차량 매물의 lclsUtilCd가 "00000"으로 오면 모든 lcl 필터에 안 잡힘.
# 정상 lcl: 10000(토지) / 20000(건물) / 30000(차량) / 40000(기타).
_INVALID_USAGE = {"00000", "0", ""}

def _usage_code(v: Any) -> str | None:
    s = _str(v)
    if s is None or s in _INVALID_USAGE:
        return None
    return s


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


def _road_addr(row: dict) -> str | None:
    """도로명 전체주소에 건물명(법정동) 결합.

    courtauction은 도로명 본주소(bgPlaceRdAllAddr)와 건물명 부가정보(rdAddrSub)를
    분리해서 준다. 본주소만 쓰면 네이버/카카오 검색이 '길'까지만 잡고 건물을 못 찾는다.
    예: '서울특별시 관악구 남현3길 00039-00000' + '(남현동,씨에스타운)'
        → '서울특별시 관악구 남현3길 39 (남현동, 씨에스타운)'
    """
    base = _clean_addr(row.get("bgPlaceRdAllAddr") or row.get("rdAllAddr"))
    if not base:
        return None
    sub = _str(row.get("rdAddrSub"))
    if sub:
        sub = re.sub(r",\s*", ", ", sub)  # '(동,건물)' → '(동, 건물)'
        if sub not in base:
            base = f"{base} {sub}"
    return base


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


# 증분 크롤 — 검색응답이 담는 변경 신호. 이 값들이 직전과 다르면 "변경됨".
_SIGNAL_INT_FIELDS = (
    "appraisal_amount", "min_sale_price", "current_sale_price", "fail_count",
)
_SIGNAL_DATE_FIELDS = ("sale_date", "sale_decision_date")
_SIGNAL_STR_FIELDS = ("status_cd",)
_SIGNAL_FIELDS = _SIGNAL_INT_FIELDS + _SIGNAL_DATE_FIELDS + _SIGNAL_STR_FIELDS
# detail(detail_result/sale_dates/risk_flags)을 stale로 만드는 변경 — 재경매/상태전이.
# 단순 reprice(current_sale_price)는 검색 컬럼만 갱신되면 충분하므로 제외.
_DETAIL_STALE_TRIGGERS = {"fail_count", "sale_date", "sale_decision_date", "status_cd"}


def _signals_changed(prev: dict, new: dict) -> set[str]:
    """직전 행(prev)과 신규 페이로드(new)의 신호 필드 비교 → 변경된 필드명 집합.
    양쪽 모두 _to_int/_to_date/_str로 정규화 후 비교(numeric vs str, date 표기 차 흡수)."""
    changed: set[str] = set()
    for k in _SIGNAL_INT_FIELDS:
        if _to_int(prev.get(k)) != _to_int(new.get(k)):
            changed.add(k)
    for k in _SIGNAL_DATE_FIELDS:
        if _to_date(prev.get(k)) != _to_date(new.get(k)):
            changed.add(k)
    for k in _SIGNAL_STR_FIELDS:
        if _str(prev.get(k)) != _str(new.get(k)):
            changed.add(k)
    return changed


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
        # 사진 저장소 — MINIO_ENDPOINT 있으면 MinIO, 없으면 Supabase Storage.
        import sys
        from pathlib import Path
        _src = str(Path(__file__).resolve().parent.parent)
        if _src not in sys.path:
            sys.path.insert(0, _src)
        from storage_backend import make_storage  # noqa: E402
        self._storage = make_storage(self.sb)
        # 0016 마이그레이션(last_seen_at 등) 적용 여부 — 미적용이면 구버전 blind upsert 폴백.
        self._incremental = self._probe_incremental()

    def _probe_incremental(self) -> bool:
        try:
            self.sb.table("properties").select("last_seen_at").limit(1).execute()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("증분 컬럼 미감지 → 구버전 blind upsert 사용 (0016 미적용?): %s", e)
            return False

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
            "usage_lcl_cd": _usage_code(row.get("lclsUtilCd")),
            "usage_mcl_cd": _usage_code(row.get("mclsUtilCd")),
            "usage_scl_cd": _usage_code(row.get("sclsUtilCd")),
            # 사이트 한글 분류 — '아파트' '오피스텔' '단독주택' 등 20종.
            # mcl/scl 마스터 부재 우회: search 응답이 직접 한글명 제공.
            "usage_nm": _str(row.get("dspslUsgNm")),
            "sd_code": _str(row.get("daepyoSidoCd")),
            "sgg_code": _str(row.get("daepyoSiguCd") or row.get("daepyoSggCd")),
            "emd_code": _str(row.get("daepyoDongCd") or row.get("daepyoEmdCd")),
            "rd_code": _str(row.get("daepyoRdCd")),
            "lot_no": _str(row.get("daepyoLotno")),
            "conv_addr": _str(row.get("convAddr") or row.get("daepyoAddr")),
            "road_addr": _road_addr(row),
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
                "usage_lcl_cd": _usage_code(r.get("lclsUtilCd")),
                "usage_mcl_cd": _usage_code(r.get("mclsUtilCd")),
                "usage_scl_cd": _usage_code(r.get("sclsUtilCd")),
                "usage_nm": _str(r.get("dspslUsgNm")),
                "sd_code": _str(r.get("daepyoSidoCd")),
                "sgg_code": _str(r.get("daepyoSiguCd") or r.get("daepyoSggCd")),
                "emd_code": _str(r.get("daepyoDongCd") or r.get("daepyoEmdCd")),
                "conv_addr": _str(r.get("convAddr") or r.get("daepyoAddr")),
                "road_addr": _road_addr(r),
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
                "usage_lcl_cd": _usage_code(r.get("lclsUtilCd")),
                "usage_mcl_cd": _usage_code(r.get("mclsUtilCd")),
                "usage_scl_cd": _usage_code(r.get("sclsUtilCd")),
                "usage_nm": _str(r.get("dspslUsgNm")),
                "sd_code": _str(r.get("daepyoSidoCd")),
                "sgg_code": _str(r.get("daepyoSiguCd") or r.get("daepyoSggCd")),
                "emd_code": _str(r.get("daepyoDongCd") or r.get("daepyoEmdCd")),
                "rd_code": _str(r.get("daepyoRdCd")),
                "lot_no": _str(r.get("daepyoLotno")),
                "conv_addr": _str(r.get("convAddr") or r.get("daepyoAddr")),
                "road_addr": _road_addr(r),
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

        now_iso = datetime.utcnow().isoformat()

        # 구버전(0016 미적용) — 기존 blind upsert 유지.
        if not self._incremental:
            return self._blind_upsert_props(deduped)

        # --- 증분: 기존행 1회 배치 read → diff → 미변경(liveness만)/변경·신규(full) 분기 ---
        case_ids = list({p["case_id"] for p in deduped})
        existing_map: dict[tuple[str, int], dict] = {}
        try:
            ex = (
                self.sb.table("properties")
                .select("id, case_id, maemul_ser, appraisal_amount, min_sale_price, "
                        "current_sale_price, fail_count, sale_date, sale_decision_date, "
                        "status_cd")
                .in_("case_id", case_ids)
                .execute()
            )
            for r in ex.data or []:
                existing_map[(r["case_id"], r["maemul_ser"])] = r
        except Exception as e:  # noqa: BLE001
            logger.warning("기존행 배치 read 실패 → 전체 full upsert 폴백: %s", e)
            return self._blind_upsert_props([{**p, "last_seen_at": now_iso} for p in deduped])

        full_upserts: list[dict] = []
        liveness_ids: list[str] = []
        hist_rows: list[dict] = []
        for p in deduped:
            prev = existing_map.get((p["case_id"], p["maemul_ser"]))
            if prev is None:
                # 신규 — full upsert (detail은 detail_synced_at NULL 경로로 자동 수집)
                full_upserts.append({**p, "last_seen_at": now_iso})
                continue
            changed = _signals_changed(prev, p)
            if not changed:
                liveness_ids.append(prev["id"])  # 변경 없음 → liveness만
                continue
            row = {**p, "last_seen_at": now_iso}
            if changed & _DETAIL_STALE_TRIGGERS:  # 재경매/상태전이 → detail 재수집 표시
                row["detail_refresh_requested_at"] = now_iso
            full_upserts.append(row)
            hist_rows.append({
                "property_id": prev["id"],
                "appraisal_amount": _to_int(p.get("appraisal_amount")),
                "min_sale_price": _to_int(p.get("min_sale_price")),
                "current_sale_price": _to_int(p.get("current_sale_price")),
                "fail_count": _to_int(p.get("fail_count")),
                "sale_date": _to_date(p.get("sale_date")),
                "sale_decision_date": _to_date(p.get("sale_decision_date")),
                "status_cd": _str(p.get("status_cd")),
                "reason": "search re-scan detected change",
                "raw": {
                    "prev": {k: prev.get(k) for k in _SIGNAL_FIELDS},
                    "new": {k: p.get(k) for k in _SIGNAL_FIELDS},
                    "changed": sorted(changed),
                },
            })

        if full_upserts:
            self._blind_upsert_props(full_upserts)
        # 미변경 행 — last_seen_at만 bulk update (jsonb/인덱스 갱신 비용 회피)
        for chunk in _chunked(liveness_ids, 500):
            self.sb.table("properties").update(
                {"last_seen_at": now_iso}
            ).in_("id", chunk).execute()
        # 가격/진행 이력 — 실패해도 페이지는 계속 (부가기능)
        if hist_rows:
            try:
                self.sb.table("kr_valuation_history").insert(hist_rows).execute()
            except Exception as e:  # noqa: BLE001
                logger.warning("kr_valuation_history insert 실패(무시): %s", e)

        logger.info(
            "search page: full=%d liveness=%d changed=%d",
            len(full_upserts), len(liveness_ids), len(hist_rows),
        )
        return len(deduped)

    def _blind_upsert_props(self, rows: list[dict]) -> int:
        """properties 일괄 upsert — 작은 chunk(25)로 timeout 회피.
        (search_row jsonb 큼 + GIST/trgm 인덱스 갱신 비용 → 페이지 50 기준 2 round-trip.)"""
        PROP_CHUNK = 25
        for chunk in _chunked(rows, PROP_CHUNK):
            self.sb.table("properties").upsert(
                chunk, on_conflict="case_id,maemul_ser",
                returning="minimal",  # 응답에 row 데이터 포함하지 않음 → 빠름
            ).execute()
        return len(rows)

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

        # risk_flags 계산 — 위 detail + 기존 properties 컬럼 종합
        from .risk_flags import compute_risk_flags  # local import to avoid cycle at module load
        prop_now = (
            self.sb.table("properties")
            .select("appraisal_amount,fail_count,usage_lcl_cd,usage_mcl_cd,usage_nm,area_summary,building_summary")
            .eq("id", property_id)
            .maybe_single()
            .execute()
        )
        p_data = prop_now.data or {}
        risk = compute_risk_flags(
            detail_result=slim_detail,
            appraisal_amount=p_data.get("appraisal_amount"),
            fail_count=p_data.get("fail_count"),
            usage_lcl_cd=p_data.get("usage_lcl_cd"),
            usage_mcl_cd=p_data.get("usage_mcl_cd"),
            usage_nm=p_data.get("usage_nm"),
            area_summary=p_data.get("area_summary"),
            building_summary=p_data.get("building_summary"),
        )

        detail_update = {
            "detail_result": slim_detail,
            "risk_flags": risk,
            "detail_synced_at": datetime.utcnow().isoformat(),
            "last_synced_at": datetime.utcnow().isoformat(),
        }
        # detail 재수집 완료 → stale 플래그 클리어 (단일 진실원천). 0016 적용 시에만.
        if self._incremental:
            detail_update["detail_refresh_requested_at"] = None
        self.sb.table("properties").update(detail_update).eq("id", property_id).execute()

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
                    # 실제 응답 키: dxdyPlcNm / tsLwsDspslPrc / auctnDxdyRsltCd / dspslAmt
                    "place": _str(r.get("dxdyPlcNm") or r.get("dspslPlc")),
                    "min_price": _to_int(r.get("tsLwsDspslPrc") or r.get("lwsDspslPrc")),
                    "result_cd": _str(r.get("auctnDxdyRsltCd") or r.get("dspslRsltCd")),
                    "raw": r,
                })
            self.sb.table("property_sale_dates").upsert(
                sale_rows, on_conflict="property_id,seq",
            ).execute()

        # 사진 목록 — base64는 Storage에 업로드하고 raw에서 제외.
        # 기본은 전체 사진 적재 (self-host MinIO/시놀로지 = 용량 제한 사실상 없음).
        # 환경변수 PHOTOS_PER_PROPERTY로 제한 가능 (0=비저장, N=첫 N장, ""=전체/기본).
        max_per = os.environ.get("PHOTOS_PER_PROPERTY", "")
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
        self._storage.upload(PHOTO_BUCKET, path, blob, content_type)

        # 2) 썸네일 (실패해도 원본은 살아있어야 하므로 try-block)
        try:
            thumb_blob = self._make_thumb(blob)
            self._storage.upload(PHOTO_BUCKET, THUMB_PREFIX + path,
                                 thumb_blob, "image/jpeg")
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
        return self._storage.public_url(PHOTO_BUCKET, storage_path)

    def public_thumb_url(self, storage_path: str) -> str:
        return self._storage.public_url(PHOTO_BUCKET, THUMB_PREFIX + storage_path)

    # ---------- close-aged (종결 매물 soft delete) ----------

    def close_aged(self, since_iso: str) -> int:
        """last_synced_at < since_iso 이고 deleted_at NULL 인 매물을 soft delete.

        매일 search 시작 시점을 since_iso로 받아 — 이번 갱신에서 등장 안 한 매물은
        courtauction 검색에서 사라진 것(낙찰 완료·취하·매각결정 후 종결).
        deleted_at 채움 — 모든 list/map query 가 `.is_("deleted_at", "null")`
        필터를 쓰므로 UI에서 자동 제외 (soft delete, 추후 복구·통계 가능).
        """
        from datetime import datetime, timezone
        # 증분 모드: 미변경 행은 last_synced_at은 안 건드리고 last_seen_at만 갱신하므로
        # liveness 판정은 last_seen_at으로 해야 함 (안 그러면 미변경 행이 전부 오삭제됨).
        col = "last_seen_at" if self._incremental else "last_synced_at"
        # PostgREST 는 기본 1000행에서 잘림(PGRST_DB_MAX_ROWS) → range 로 전량 페이징.
        # (이전엔 단일 select 라 만료 매물이 1000건 넘으면 나머지가 영구히 soft-delete
        #  안 돼 낙찰·취하된 죽은 매물이 UI 에 계속 노출됐음)
        ids: list = []
        offset = 0
        PAGE = 1000
        while True:
            sel = (
                self.sb.table("properties")
                .select("id")
                .lt(col, since_iso)
                .is_("deleted_at", "null")
                .order("id")
                .range(offset, offset + PAGE - 1)
                .execute()
            )
            batch = sel.data or []
            ids.extend(r["id"] for r in batch)
            if len(batch) < PAGE:
                break
            offset += PAGE
        if not ids:
            return 0
        now_iso = datetime.now(timezone.utc).isoformat()
        # 1000건씩 chunk update (PostgREST in_ 길이 제한 회피)
        n = 0
        for i in range(0, len(ids), 1000):
            chunk = ids[i:i + 1000]
            self.sb.table("properties").update(
                {"deleted_at": now_iso}
            ).in_("id", chunk).execute()
            n += len(chunk)
        logger.info("soft-deleted %d aged properties (%s < %s)",
                    n, col, since_iso)
        return n

    def last_search_complete_since(self, since_iso: str) -> bool:
        """since_iso 이후 시작된 search run 중 완주(totals.complete=true)한 게 있나.
        close-aged가 호출 전 확인 — 부분 실행(차단/예산소진)으로 인한 오삭제 방지."""
        try:
            r = (
                self.sb.table("crawl_runs")
                .select("id")
                .eq("job_type", "search")
                .eq("status", "done")
                .eq("totals->>complete", "true")
                .gte("started_at", since_iso)
                .limit(1)
                .execute()
            )
            return bool(r.data)
        except Exception as e:  # noqa: BLE001
            logger.warning("search 완주 확인 실패(보수적으로 미완주 처리): %s", e)
            return False

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
