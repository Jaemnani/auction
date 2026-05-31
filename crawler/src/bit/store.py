"""
BIT → Supabase 적재 레이어 (jp_* 테이블).

한국 courtauction.store의 일본 대응. 같은 패턴이지만 jp_* 테이블에 적재.

기능:
- upsert_courts / upsert_prefectures / upsert_municipalities
- upsert_search_card  → jp_cases + jp_properties (검색 결과 카드)
- upsert_detail       → jp_properties.detail_result (상세 응답 — 1차는 raw)
- upload_photo        → jp-auction-photos 버킷 + jp_property_photos
"""

from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx
from supabase import Client, create_client

try:
    from PIL import Image  # type: ignore
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

logger = logging.getLogger(__name__)

JP_PHOTO_BUCKET = "jp-auction-photos"
JP_THUMB_PREFIX = "thumbs/"
THUMB_MAX = (320, 240)
THUMB_QUALITY = 80


# ---------- helpers ----------

def _to_int(v: Any) -> int | None:
    if v in (None, "", "null"):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _normalize_address(text: str | None) -> str | None:
    """전각 숫자/하이픈 → 반각, 공백 정규화."""
    if not text:
        return None
    table = str.maketrans({
        "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
        "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
        "－": "-", "ー": "-", "　": " ",
    })
    return text.translate(table).strip()


def _classify_status(card: dict[str, Any]) -> str | None:
    """검색 카드 → status enum 추정.

    상태머신 (jp_properties.status):
      period_bid     — 期間入札 진행 중
      special_sale   — 特別売却 진행 중
      reval_pending  — 평가 재조정 대기
      re_bid         — 재매각 (별도 회차)
      closed         — 종결
      aborted        — 중지
    """
    label = (card.get("sale_status_text") or "").strip()
    if "期間入札" in label:
        return "period_bid"
    if "特別売却" in label:
        return "special_sale"
    if "売却中止" in label or "停止" in label:
        return "aborted"
    return None


# ---------- Config ----------

@dataclass
class BitStoreConfig:
    url: str
    key: str
    chunk_size: int = 50


class BitStore:
    """jp_* 테이블 upsert 인터페이스. 한국 Store와 거의 동일 패턴."""

    def __init__(self, cfg: BitStoreConfig | None = None) -> None:
        if cfg is None:
            url = os.environ.get("SUPABASE_URL")
            key = (
                os.environ.get("SUPABASE_SERVICE_KEY")
                or os.environ.get("SUPABASE_KEY")
            )
            if not url or not key:
                raise RuntimeError("SUPABASE_URL / SUPABASE_(SERVICE_)KEY env required")
            cfg = BitStoreConfig(url=url, key=key)
        self.cfg = cfg
        self.sb: Client = create_client(cfg.url, cfg.key)

    # ---------- masters ----------

    def upsert_courts(self, rows: list[dict]) -> int:
        """jp_courts upsert.

        rows: [{code, name, prefecture_code?, prefix?, raw?}]
        """
        if not rows:
            return 0
        payload = [
            {
                "code": r["code"], "name": r["name"],
                "prefecture_code": r.get("prefecture_code"),
                "prefix": r.get("prefix"),
                "raw": r.get("raw") or {},
            }
            for r in rows
        ]
        self.sb.table("jp_courts").upsert(payload, on_conflict="code").execute()
        return len(payload)

    def upsert_municipalities(self, rows: list[dict]) -> int:
        """jp_municipalities upsert. rows: [{code, prefecture_code, name, raw?}]"""
        if not rows:
            return 0
        payload = [
            {
                "code": r["code"],
                "prefecture_code": r["prefecture_code"],
                "name": r["name"],
                "raw": r.get("raw") or {},
            }
            for r in rows
        ]
        self.sb.table("jp_municipalities").upsert(
            payload, on_conflict="prefecture_code,code"
        ).execute()
        return len(payload)

    # ---------- search → cases + properties ----------

    def _ensure_court(self, court_id: str, court_name: str | None) -> None:
        """알려지지 않은 법원이 매물에 등장 → 자동 등록 (이름이 있을 때만)."""
        if not court_name:
            return
        try:
            self.sb.table("jp_courts").upsert(
                [{"code": court_id, "name": court_name}],
                on_conflict="code",
            ).execute()
        except Exception as e:
            logger.warning("jp_courts auto-insert failed: %s", e)

    def _upsert_case(self, court_id: str, card: dict[str, Any]) -> str:
        """jp_cases upsert → return case_id (uuid)."""
        case_no = card.get("case_no_text")
        if not case_no:
            raise ValueError(f"case_no missing in card sale_unit_id={card.get('sale_unit_id')}")
        parts = card.get("case_no_parts") or {}
        row = {
            "court_code": court_id,
            "case_no": case_no,
            "case_year": parts.get("year"),
            "case_era": parts.get("era"),
            "case_kind": parts.get("kind"),
            "case_kind_no": parts.get("no"),
            "raw": {"case_no_text": case_no, "parts": parts},
        }
        # upsert → returning id 직접 안 되니, 후속 select
        self.sb.table("jp_cases").upsert(
            [row], on_conflict="court_code,case_no"
        ).execute()
        sel = (
            self.sb.table("jp_cases")
            .select("id")
            .eq("court_code", court_id)
            .eq("case_no", case_no)
            .limit(1)
            .execute()
        )
        if not sel.data:
            raise RuntimeError(f"jp_cases lookup failed after upsert: {court_id}/{case_no}")
        return sel.data[0]["id"]

    def upsert_search_card(
        self,
        card: dict[str, Any],
        *,
        prefecture_code: str | None = None,
        municipality_code: str | None = None,
    ) -> str:
        """검색 카드 한 건 upsert → return jp_properties.id.

        card는 client.parse_search_result()[i] 형식.
        """
        court_id = card.get("court_id")
        if not court_id:
            raise ValueError(f"court_id missing in card {card}")

        self._ensure_court(court_id, card.get("court_name_text"))
        case_id = self._upsert_case(court_id, card)

        # sale_cls 라벨 → 코드
        label = (card.get("sale_cls_label") or "").strip()
        sale_cls_code = {"土地": "1", "戸建て": "2", "マンション": "3", "その他": "4"}.get(label)

        photo_meta = card.get("photo_meta") or {}
        prop_seq = photo_meta.get("seq") or 1

        sale_std = card.get("sale_standard_price")
        # 1만엔 함정 후보: 매각기준 ≤ 100,000円
        yen_10k_trap = bool(sale_std is not None and sale_std <= 100_000)

        addr_raw = card.get("address_text")
        addr_norm = _normalize_address(addr_raw)

        row = {
            "case_id": case_id,
            "sale_unit_id": card["sale_unit_id"],
            "property_seq": prop_seq,
            "sale_cls": sale_cls_code,
            "sale_cls_label": label or None,
            "sale_standard_price": sale_std,
            "bid_deposit": card.get("bid_deposit"),
            "status": _classify_status(card),
            "bid_view_start": card.get("bid_view_start"),
            "bid_period_start": card.get("bid_period_start"),
            "bid_period_end": card.get("bid_period_end"),
            "open_bid_date": card.get("open_bid_date"),
            "special_sale_start": card.get("special_sale_start"),
            "special_sale_end": card.get("special_sale_end"),
            "prefecture_code": prefecture_code,
            "municipality_code": municipality_code,
            "address_text": addr_raw,
            "address_normalized": addr_norm,
            "transit_info": card.get("transit_info"),
            "yen_10k_trap": yen_10k_trap,
            "search_row": card,
            # search 결과에 등장 → 살아있는 매물. 갱신 후 close-aged에서 활용.
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        self.sb.table("jp_properties").upsert(
            [row], on_conflict="sale_unit_id"
        ).execute()
        sel = (
            self.sb.table("jp_properties")
            .select("id")
            .eq("sale_unit_id", card["sale_unit_id"])
            .limit(1)
            .execute()
        )
        if not sel.data:
            raise RuntimeError(f"jp_properties lookup failed: {card['sale_unit_id']}")
        return sel.data[0]["id"]

    def upsert_search_cards(
        self,
        cards: Iterable[dict[str, Any]],
        *,
        prefecture_code: str | None = None,
        municipality_code: str | None = None,
    ) -> int:
        """다건 batched (chunk_size 단위)."""
        n = 0
        for c in cards:
            try:
                self.upsert_search_card(
                    c, prefecture_code=prefecture_code,
                    municipality_code=municipality_code,
                )
                n += 1
            except Exception as e:
                logger.warning(
                    "upsert_search_card failed sale_unit_id=%s: %s",
                    c.get("sale_unit_id"), e,
                )
        return n

    # ---------- detail ----------

    def upsert_detail(self, sale_unit_id: str, detail: dict[str, Any]) -> None:
        """상세 응답 jp_properties 갱신.

        detail_result jsonb에 통째 + 좌표·3종 가격은 컬럼에도 별도 저장.
        가격이 직전과 다르면 jp_valuation_history에 변경 이력 기록 (일본 평가 재조정 추적).
        """
        prices = detail.get("prices") or {}
        new_std = prices.get("sale_standard_price") if isinstance(prices, dict) else None
        new_ppp = prices.get("purchase_possible_price") if isinstance(prices, dict) else None

        # 변경 감지 — 직전 값 조회
        prev = (
            self.sb.table("jp_properties")
            .select("id, sale_standard_price, purchase_possible_price")
            .eq("sale_unit_id", sale_unit_id)
            .maybeSingle()
            .execute()
        )
        prev_data = prev.data or {}
        property_id = prev_data.get("id")
        prev_std = prev_data.get("sale_standard_price")
        prev_ppp = prev_data.get("purchase_possible_price")

        def _num(v: Any) -> int | None:
            if isinstance(v, (int, float)):
                return int(v)
            if isinstance(v, str):
                try:
                    return int(v.replace(",", ""))
                except ValueError:
                    return None
            return None

        prev_std_n = _num(prev_std)
        prev_ppp_n = _num(prev_ppp)
        new_std_n = _num(new_std)
        new_ppp_n = _num(new_ppp)

        # 변경 시 history 기록 (최초 적재 시 prev=None이면 skip — 시작점은 history 불요)
        if property_id and (
            (prev_std_n is not None and new_std_n is not None and prev_std_n != new_std_n)
            or (prev_ppp_n is not None and new_ppp_n is not None and prev_ppp_n != new_ppp_n)
        ):
            try:
                self.sb.table("jp_valuation_history").insert([{
                    "property_id": property_id,
                    "valued_at": datetime.now(timezone.utc).date().isoformat(),
                    "sale_standard_price": new_std_n,
                    "purchase_possible_price": new_ppp_n,
                    "reason": "BIT detail re-fetch 시 변경 감지",
                    "raw": {
                        "prev": {"sale_standard_price": prev_std_n,
                                 "purchase_possible_price": prev_ppp_n},
                        "new": {"sale_standard_price": new_std_n,
                                "purchase_possible_price": new_ppp_n},
                    },
                }]).execute()
                logger.info(
                    "valuation change %s: std %s→%s / ppp %s→%s",
                    sale_unit_id, prev_std_n, new_std_n, prev_ppp_n, new_ppp_n,
                )
            except Exception as e:
                logger.warning("valuation_history insert failed for %s: %s",
                               sale_unit_id, e)

        update: dict[str, Any] = {"detail_result": detail}
        lat = detail.get("latitude")
        lng = detail.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            update["latitude"] = lat
            update["longitude"] = lng
        if new_ppp_n is not None:
            update["purchase_possible_price"] = new_ppp_n
        if new_std_n is not None:
            update["sale_standard_price"] = new_std_n

        self.sb.table("jp_properties").update(update).eq(
            "sale_unit_id", sale_unit_id,
        ).execute()

    # ---------- close-aged ----------

    def close_aged(self, since_iso: str) -> int:
        """fetched_at < since_iso 이고 status가 종결 아닌 매물을 'closed' 마킹.

        매일 search-all 시작 시점을 since_iso로 받아 — 이번 갱신에서 등장 안 한 매물은
        BIT에서 사라진 것 → 낙찰 완료/절차 정지로 추정.
        """
        sel = (
            self.sb.table("jp_properties")
            .select("id, sale_unit_id, status, fetched_at")
            .lt("fetched_at", since_iso)
            .not_.in_("status", ["closed", "aborted"])
            .execute()
        )
        rows = sel.data or []
        if not rows:
            return 0
        ids = [r["id"] for r in rows]
        self.sb.table("jp_properties").update({"status": "closed"}).in_(
            "id", ids,
        ).execute()
        logger.info("closed %d aged properties (fetched_at < %s)", len(ids), since_iso)
        return len(ids)

    # ---------- photos ----------

    @staticmethod
    def _photo_storage_path(sale_unit_id: str, seq: int, ext: str = "jpg") -> str:
        return f"{sale_unit_id}/{seq:03d}.{ext}"

    @staticmethod
    def _thumb_storage_path(sale_unit_id: str, seq: int) -> str:
        return f"{JP_THUMB_PREFIX}{sale_unit_id}/{seq:03d}.jpg"

    def upload_photo_from_url(
        self, sale_unit_id: str, seq: int, photo_url: str,
        *, base_url: str = "https://www.bit.courts.go.jp",
    ) -> dict[str, Any] | None:
        """BIT 사진 URL 다운로드 → jp-auction-photos 버킷 + 썸네일.

        한국 store는 base64 디코딩 후 업로드. 일본은 정적 URL이라 GET 후 업로드.
        """
        from urllib.parse import urljoin
        full_url = urljoin(base_url, photo_url)
        try:
            r = httpx.get(full_url, timeout=20.0)
            r.raise_for_status()
            content = r.content
        except Exception as e:
            logger.warning("photo download failed %s: %s", full_url, e)
            return None

        path = self._photo_storage_path(sale_unit_id, seq)
        try:
            self.sb.storage.from_(JP_PHOTO_BUCKET).upload(
                path=path, file=content,
                file_options={"content-type": "image/jpeg", "upsert": "true"},
            )
        except Exception as e:
            logger.warning("photo upload failed %s: %s", path, e)
            return None

        thumb_path: str | None = None
        if _HAS_PIL:
            try:
                img = Image.open(io.BytesIO(content))
                img.thumbnail(THUMB_MAX)
                buf = io.BytesIO()
                img.convert("RGB").save(buf, "JPEG", quality=THUMB_QUALITY)
                thumb_path = self._thumb_storage_path(sale_unit_id, seq)
                self.sb.storage.from_(JP_PHOTO_BUCKET).upload(
                    path=thumb_path, file=buf.getvalue(),
                    file_options={"content-type": "image/jpeg", "upsert": "true"},
                )
            except Exception as e:
                logger.warning("thumb gen failed %s: %s", path, e)
                thumb_path = None

        # jp_property_photos upsert (property_id 필요)
        prop = (
            self.sb.table("jp_properties")
            .select("id")
            .eq("sale_unit_id", sale_unit_id)
            .limit(1)
            .execute()
        )
        if not prop.data:
            logger.warning("photo: property not found sale_unit_id=%s", sale_unit_id)
            return None
        property_id = prop.data[0]["id"]

        photo_row = {
            "property_id": property_id,
            "seq": seq,
            "bit_url": photo_url,
            "storage_path": path,
            "thumb_path": thumb_path,
            "kind": "list",
        }
        self.sb.table("jp_property_photos").upsert(
            [photo_row], on_conflict="property_id,seq",
        ).execute()
        return photo_row

    # ---------- crawl runs (한국 store와 동일한 crawl_runs 테이블 공용) ----------

    def start_run(self, job_type: str, params: dict | None = None) -> str:
        r = self.sb.table("crawl_runs").insert(
            {"job_type": job_type, "params": params or {}, "status": "running"}
        ).execute()
        return r.data[0]["id"]

    def finish_run(self, run_id: str, totals: dict | None = None,
                   *, status: str = "done", error: str | None = None) -> None:
        self.sb.table("crawl_runs").update(
            {"status": status, "totals": totals or {},
             "finished_at": datetime.now(timezone.utc).isoformat(), "error": error}
        ).eq("id", run_id).execute()
