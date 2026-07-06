"""
BIT (bit.courts.go.jp) HTTP 클라이언트.

한국 courtauction과 달리 JSON RIA가 아니라 Java Struts 기반 HTML 응답.
모든 endpoint가 form POST + HTML — BeautifulSoup으로 파싱.

흐름 (docs/bit_api_recon.md 참고):
  GET /                                → 메인 (블록 지도)
  POST /app/top/pt001/h02              → 블록 → 도도부현 선택 페이지
  POST /app/areaselect/ps002/h05       → 도도부현 단위 매물 검색 결과
  POST /app/areaselect/ps002/h10       → 시구정촌 단위 매물 검색 결과
  POST /app/propertyresult/pr001/h05   → 매물 상세
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BIT_BASE_URL = "https://www.bit.courts.go.jp"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "ja,ko;q=0.9,en;q=0.8",
    "Origin": BIT_BASE_URL,
}


# ---------- Errors ----------

class BitError(Exception):
    """BIT 클라이언트 베이스."""


class BitTransientError(BitError):
    """재시도 대상."""


class BitPermanentError(BitError):
    """재시도 무의미."""


class BitParseError(BitError):
    """HTML 구조 변경 — dead letter 후보."""


# ---------- Config ----------

@dataclass
class BitClientConfig:
    base_url: str = BIT_BASE_URL
    concurrency: int = 2
    min_interval_ms: int = 800
    timeout_s: float = 30.0
    max_retries: int = 5
    backoff_base_s: float = 1.0
    backoff_max_s: float = 60.0
    ip_block_pause_s: float = 120.0
    save_dir: Path | None = None


# ---------- 매물 카드 (검색 결과 → property) DTO ----------

# 사진 URL 파싱: /data/image/{COURT_PREFIX}_R{YY}{KIND_CHAR}{NO5}_{SEQ}_{SIZE}.jpg
PHOTO_URL_RE = re.compile(
    r"/data/image/(?P<prefix>[A-Z]+)_(?P<era>[RH])(?P<yy>\d{2})"
    r"(?P<kind>[KN])(?P<no>\d+)_(?P<seq>\d+)_(?P<size>[a-z])\.jpg"
)

# 사건번호 파싱: 令和07年(ケ)第221号
CASE_NO_RE = re.compile(
    r"(?P<era>令和|平成)(?P<yy>\d+)年\((?P<kind>[ケヌ])\)第(?P<no>\d+)号"
)

# tranPropertyDetail("00000021169", "31131", '1') → ids
DETAIL_RE = re.compile(
    r"""tranPropertyDetail\(\s*["']?(?P<sale_unit_id>\d+)["']?\s*,"""
    r"""\s*["']?(?P<court_id>\d+)["']?\s*,\s*['"]?(?P<tab>\d+)['"]?\s*\)"""
)

# 가격 파싱: "4,940,000円" → 4940000. 방어적으로 万円 표기도 지원:
#   "494万円" → 4,940,000 / "494万5,000円" → 4,945,000
#   (BIT 표준은 전액+콤마 표기지만, 표기 변경 시 조용히 NULL 되는 것 방지)
PRICE_RE = re.compile(r"([\d,]+)(?:万([\d,]*))?\s*円")

# 일본 날짜 파싱: 令和08年04月17日. 元年(1년차, 예: 令和元年) 표기도 지원.
JP_DATE_RE = re.compile(
    r"(令和|平成)(\d+|元)年(\d{1,2})月(\d{1,2})日"
)


def _parse_jp_date(text: str) -> str | None:
    """令和08年04月17日 → 2026-04-17 (ISO). 令和元年=2019, 平成元年=1989."""
    m = JP_DATE_RE.search(text)
    if not m:
        return None
    era = m.group(1)
    yy = 1 if m.group(2) == "元" else int(m.group(2))
    mm, dd = int(m.group(3)), int(m.group(4))
    base = 2018 if era == "令和" else 1988
    year = base + yy
    return f"{year:04d}-{mm:02d}-{dd:02d}"


def _parse_price(text: str) -> int | None:
    m = PRICE_RE.search(text)
    if not m:
        return None
    n = int(m.group(1).replace(",", ""))
    if m.group(2) is not None:  # 万 표기 — 앞부분×10000 + 뒷부분(있으면)
        rest = int(m.group(2).replace(",", "")) if m.group(2) else 0
        return n * 10000 + rest
    return n


# ---------- Client ----------

class BitClient:
    def __init__(self, config: BitClientConfig | None = None) -> None:
        self.cfg = config or BitClientConfig()
        self._sem = asyncio.Semaphore(self.cfg.concurrency)
        self._throttle_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._client: httpx.AsyncClient | None = None
        # 페이지네이션 컨텍스트 — 직전 검색 응답의 propertyResultForm hidden inputs
        self._last_search_form: dict[str, str] = {}

    async def __aenter__(self) -> "BitClient":
        self._client = httpx.AsyncClient(
            base_url=self.cfg.base_url,
            headers=DEFAULT_HEADERS,
            timeout=self.cfg.timeout_s,
            http2=False,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _throttle(self) -> None:
        if self.cfg.min_interval_ms <= 0:
            return
        async with self._throttle_lock:
            elapsed_ms = (time.monotonic() - self._last_request_at) * 1000
            wait_ms = self.cfg.min_interval_ms - elapsed_ms
            if wait_ms > 0:
                await asyncio.sleep(wait_ms / 1000)
            self._last_request_at = time.monotonic()

    async def _post_html(
        self, path: str, data: dict[str, Any],
        *, referer: str | None = None,
    ) -> str:
        """form POST → HTML text. retry + IP block detection."""
        if self._client is None:
            raise RuntimeError("BitClient must be used as async context manager")

        headers: dict[str, str] = {}
        if referer:
            headers["Referer"] = urljoin(self.cfg.base_url, referer)

        last_err: Exception | None = None
        for attempt in range(self.cfg.max_retries):
            async with self._sem:
                try:
                    await self._throttle()
                    r = await self._client.post(path, data=data, headers=headers)
                except (httpx.TimeoutException, httpx.NetworkError,
                        httpx.RemoteProtocolError) as e:
                    last_err = e
                    delay = min(self.cfg.backoff_base_s * (2 ** attempt),
                                self.cfg.backoff_max_s)
                    logger.warning("BIT network error %s on %s (attempt %d), retry in %.1fs",
                                   type(e).__name__, path, attempt + 1, delay)
                    await asyncio.sleep(delay)
                    continue

            if 500 <= r.status_code < 600:
                last_err = BitTransientError(f"HTTP {r.status_code} on {path}")
                delay = min(self.cfg.backoff_base_s * (2 ** attempt),
                            self.cfg.backoff_max_s)
                logger.warning("BIT %d on %s, retry in %.1fs", r.status_code, path, delay)
                await asyncio.sleep(delay)
                continue
            if 400 <= r.status_code < 500:
                raise BitPermanentError(f"HTTP {r.status_code} on {path}")

            text = r.text
            # IP block 감지 (한국과 유사 — BIT 차단 메시지는 정찰 미완)
            if "アクセスが集中" in text or "アクセス制限" in text:
                logger.warning("BIT IP block suspected on %s, sleeping %.0fs",
                               path, self.cfg.ip_block_pause_s)
                await asyncio.sleep(self.cfg.ip_block_pause_s)
                continue
            return text

        raise (last_err or BitTransientError(f"max retries exceeded on {path}"))

    # ---------- 검색 ----------

    async def open_block(self, block_cls: str, *, tab_id: str = "property") -> str:
        """블록 선택 → 도도부현 선택 페이지 HTML.

        cookie/세션 워밍업용. 결과 HTML은 도도부현·시구정촌 마스터 정찰에 사용 가능.
        """
        return await self._post_html(
            "/app/top/pt001/h02",
            data={"blockCls": block_cls, "tabId": tab_id},
            referer="/",
        )

    async def search(
        self, *,
        prefecture_id: str,
        block_cls: str,
        sale_cls: list[str] | None = None,
        municipality_id: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """매물 검색 → {total: int, properties: [PropertyCard...], html: str}.

        - prefecture_id: 도도부현 코드 (예: "13" 東京)
        - block_cls: 블록 코드 (예: "03" 関東) — Referer/세션 갱신용
        - sale_cls: 용도 필터 (1=토지, 2=戸建, 3=マンション, 4=その他). None이면 전체
        - municipality_id: 시구정촌 (선택) — 있으면 ps002/h10, 없으면 ps002/h05
        """
        # 사전: 블록 단계 GET (세션 컨텍스트 확보)
        await self.open_block(block_cls)

        sale_cls_list = sale_cls or ["1", "2", "3", "4"]

        if page == 1 or not self._last_search_form:
            # 1페이지 (또는 컨텍스트 없을 때): 검색 form (areaselect/ps002/h05 또는 h10)
            body: dict[str, Any] = {
                "prefecturesId": prefecture_id,
                "tabId": "property",
                "blockCls": block_cls,
                "saleCls": sale_cls_list,
                "saleClsSelected": ",".join(sale_cls_list),
                "saleStandardAmountCls": "1",
                "currentPage": "1",
                "pageSize": str(page_size),
                "resultListSearchButtonFlag": "0",
                "pageListChangeFlg": "0",
            }
            if municipality_id:
                body["municipalityId"] = municipality_id
                body["municipalitychecked"] = municipality_id
                path = "/app/areaselect/ps002/h10"
            else:
                path = "/app/areaselect/ps002/h05"
            referer = "/app/top/pt001/h02"
        else:
            # 2페이지+: 직전 응답의 propertyResultForm hidden inputs 그대로 재사용
            # currentPage / pageSize만 갱신
            body = dict(self._last_search_form)
            body["currentPage"] = str(page)
            body["pageSize"] = str(page_size)
            body["resultListSearchButtonFlag"] = "0"
            body["pageListChangeFlg"] = "0"
            # detail 호출 흔적 제거 (warmup → backfill 시 잔존 가능)
            body["saleUnitId"] = ""
            body["detailCourtId"] = ""
            body["transitionTabId"] = ""
            path = "/app/propertyresult/pr001/h04"
            referer = "/app/areaselect/ps002/h05"

        html = await self._post_html(path, body, referer=referer)
        # 다음 페이지 호출 시 재사용할 form context 업데이트
        form_ctx = extract_property_result_form(html)
        if form_ctx:
            self._last_search_form = form_ctx
        parsed = parse_search_result(html)
        parsed["html"] = html
        return parsed

    async def search_iter(
        self, *,
        prefecture_id: str,
        block_cls: str,
        sale_cls: list[str] | None = None,
        municipality_id: str | None = None,
        page_size: int = 50,
    ) -> AsyncIterator[dict[str, Any]]:
        """페이지 자동 순회 — yield individual property cards."""
        page = 1
        total: int | None = None
        seen = 0
        while True:
            result = await self.search(
                prefecture_id=prefecture_id,
                block_cls=block_cls,
                sale_cls=sale_cls,
                municipality_id=municipality_id,
                page=page,
                page_size=page_size,
            )
            if total is None:
                total = result.get("total", 0)
                logger.info("BIT search prefecture=%s total=%d", prefecture_id, total)
            cards = result.get("properties") or []
            if not cards:
                break
            for c in cards:
                yield c
            seen += len(cards)
            if total is not None and seen >= total:
                break
            page += 1
            if page > 100:  # safety
                logger.warning("BIT search pagination safety-stop at page %d", page)
                break

    async def get_detail(
        self, *, sale_unit_id: str, court_id: str,
        prefecture_id: str, block_cls: str,
        transition_tab_id: str = "1",
        warmup: bool = True,
    ) -> dict[str, Any]:
        """매물 상세 — POST /app/propertyresult/pr001/h05.

        BIT 상세는 propertyResultForm 전체 hidden context를 요구 (단순 ID 3개로는 HTTP 500).
        - warmup=True: 검색 결과 페이지를 한 번 거쳐 세션 컨텍스트 확보
          (배치 호출 시 첫 회만 True, 이후는 False로 호출 비용 절약)
        - 호출 시: 검색 결과 form의 모든 hidden input 그대로 전송
        """
        if warmup:
            await self.search(
                prefecture_id=prefecture_id, block_cls=block_cls,
                sale_cls=["1", "2", "3", "4"], page=1, page_size=10,
            )
        # 2) 상세 호출 — propertyResultForm 전체 hidden context 재현
        body: dict[str, Any] = {
            "saleUnitId": sale_unit_id,
            "detailCourtId": court_id,
            "transitionTabId": transition_tab_id,
            "prefecturesId": prefecture_id,
            "blockCls": block_cls,
            "tabId": "property",
            "stationBackPage": "",
            "pageSize": "10",
            "currentPage": "1",
            "pageListChangeFlg": "",
            "totalCount": "0",
            "conditionShowFlag": "H28",
            "navigationFlg": "4",
            "period": "",
            "municipalityId": "",
            "saleClsList": "1,2,3,4",
            "areaIdList": "",
            "blockName": "",
            "mapShowFlag": "",
            "mapSelectedAreaName": "",
            "detailConditionOpenFlg": "",
            "searchType": "",
            "municipalityNm": "",
            "landDetalConditionOpenFlag": "",
            "detachedDetalConditionOpenFlag": "",
            "mansionDetalConditionOpenFlag": "",
            "otherLandDetalConditionOpenFlag": "",
            "currentShikutyosonConditionFlag": "",
        }
        html = await self._post_html(
            "/app/propertyresult/pr001/h05",
            body,
            referer="/app/areaselect/ps002/h05",
        )
        return {"html": html, "parsed": parse_detail(html)}


# ---------- HTML Parser (모듈 레벨) ----------

def _select_one_text(soup: BeautifulSoup, selector: str) -> str | None:
    el = soup.select_one(selector)
    return el.get_text(strip=True) if el else None


def extract_property_result_form(html: str) -> dict[str, str]:
    """propertyResultForm의 모든 hidden input → name: value dict.

    페이지네이션 시 page1 응답의 form 컨텍스트를 그대로 다음 호출에 재사용.
    BIT는 인풋이 missing되면 검색 컨텍스트를 잃어서 빈 결과를 반환.
    """
    soup = BeautifulSoup(html, "html.parser")
    form = soup.select_one("#propertyResultForm")
    if form is None:
        return {}
    out: dict[str, str] = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        out[name] = inp.get("value") or ""
    return out


def parse_search_result(html: str) -> dict[str, Any]:
    """검색 결과 페이지 → {total: int, properties: [card...]}.

    카드 한 건당 다음 dict:
      - sale_unit_id, court_id  (tranPropertyDetail에서 추출)
      - case_no_text            (raw 사건번호 문자열)
      - case_no_parts           (parsed era/year/kind/no)
      - court_name_text
      - sale_cls_label          (土地/戸建て/マンション/その他)
      - sale_standard_price     (円, int)
      - bid_deposit             (円, int)
      - address_text
      - transit_info
      - photo_url               (대표 사진 1장)
      - photo_meta              (PHOTO_URL_RE 추출)
      - bid_view_start          (ISO date)
      - bid_period_start
      - bid_period_end
      - open_bid_date
      - special_sale_start
      - special_sale_end
      - sale_status_text        (期間入札 / 特別売却 ...)
    """
    soup = BeautifulSoup(html, "html.parser")

    # 총 건수
    total = 0
    total_el = soup.select_one(".bit__numberOfResult_totalNumber")
    if total_el and total_el.get_text(strip=True).isdigit():
        total = int(total_el.get_text(strip=True))

    properties: list[dict[str, Any]] = []

    # 매물 카드: tranPropertyDetail 호출이 있는 a 태그 → 카드 컨테이너 거슬러 올라가서 추출
    seen_ids: set[str] = set()
    for a in soup.find_all("a", onclick=True):
        m = DETAIL_RE.search(a.get("onclick", ""))
        if not m:
            continue
        sale_unit_id = m.group("sale_unit_id")
        court_id = m.group("court_id")
        if sale_unit_id in seen_ids:
            continue
        seen_ids.add(sale_unit_id)

        # 카드 컨테이너: ancestor 중 class에 정확히 'bit__searchResult'를
        # 포함하는 div (header 등 partial 매칭 제외)
        card = None
        node = a
        for _ in range(15):
            if node.parent is None:
                break
            node = node.parent
            classes = node.get("class") or [] if hasattr(node, "get") else []
            if "bit__searchResult" in classes:
                card = node
                break

        card_text = card.get_text(" ", strip=True) if card else ""

        # 사건번호 + 법원
        case_match = CASE_NO_RE.search(card_text)
        case_no_text: str | None = None
        case_no_parts: dict[str, Any] | None = None
        court_name_text: str | None = None
        if case_match:
            case_no_text = case_match.group(0)
            case_no_parts = {
                "era": case_match.group("era"),
                "year": int(case_match.group("yy")),
                "kind": case_match.group("kind"),
                "no": int(case_match.group("no")),
            }
            # 사건번호 앞에 법원 이름이 옴 — "東京地方裁判所立川支部" 등
            before = card_text[:case_match.start()].strip()
            for token in reversed(before.split()):
                if "裁判所" in token:
                    court_name_text = token
                    break
            if court_name_text is None and "裁判所" in before:
                # 마지막 " " 기준 split이 실패한 경우 — 강제 추출
                idx = before.rfind("裁判所")
                court_name_text = before[max(0, idx - 12):idx + 3]

        # 종별 라벨
        sale_cls_label: str | None = None
        for badge in (card.select(".badge") if card else []):
            text = badge.get_text(strip=True)
            if text in ("土地", "戸建て", "マンション", "その他"):
                sale_cls_label = text
                break

        # 가격
        sale_standard_price: int | None = None
        bid_deposit: int | None = None
        if card:
            for div in card.find_all(["div", "p"]):
                t = div.get_text(" ", strip=True)
                if "売却基準価額" in t:
                    sale_standard_price = sale_standard_price or _parse_price(t)
                elif "買受申出保証金" in t:
                    bid_deposit = bid_deposit or _parse_price(t)

        # 사진
        photo_url: str | None = None
        photo_meta: dict[str, Any] | None = None
        if card:
            img = card.select_one(".bit__searchResult_img")
            if img and img.get("src"):
                photo_url = img["src"]
                pm = PHOTO_URL_RE.search(photo_url)
                if pm:
                    photo_meta = {
                        "prefix": pm.group("prefix"),
                        "era": pm.group("era"),
                        "yy": int(pm.group("yy")),
                        "kind": pm.group("kind"),
                        "no": int(pm.group("no")),
                        "seq": int(pm.group("seq")),
                        "size": pm.group("size"),
                    }

        # 주소 — bit__icon_access 다음 형제 텍스트
        address_text: str | None = None
        if card:
            access_icon = card.select_one(".bit__icon_access")
            if access_icon and access_icon.parent:
                address_text = access_icon.parent.get_text(" ", strip=True)

        # 교통 — kakakuContainer 안의 col-12 bit__text_small div (가격 라벨이 아닌 본문)
        transit_info: str | None = None
        if card:
            for div in card.select(".bit__result_kakakuContainer div.bit__text_small"):
                # 가격 라벨(p.bit__text_small)이 아닌 div 본문만
                if div.name == "div":
                    text = div.get_text("\n", strip=True)
                    if text and ("駅" in text or "バス" in text or "ｋｍ" in text or "km" in text):
                        transit_info = text
                        break

        # 매각기일 (bit__multiHeadTable_th / _td 페어)
        sale_status_text: str | None = None
        bid_view_start: str | None = None
        bid_period_start: str | None = None
        bid_period_end: str | None = None
        open_bid_date: str | None = None
        special_sale_start: str | None = None
        special_sale_end: str | None = None
        if card:
            # 첫 번째 my-2 p 태그 = 用途 라벨 (期間入札 등)
            for p in card.select("p.my-2, p.my-1"):
                t = p.get_text(strip=True)
                if t in ("期間入札", "特別売却", "特別売却期間", "売却中止"):
                    sale_status_text = t
                    break

            ths = card.select(".bit__multiHeadTable_th")
            tds = card.select(".bit__multiHeadTable_td")
            for th, td in zip(ths, tds):
                lbl = th.get_text(strip=True)
                val = td.get_text(strip=True)
                if "閲覧開始日" in lbl:
                    bid_view_start = _parse_jp_date(val)
                elif "入札期間" in lbl:
                    parts = re.split(r"〜|～|~", val)
                    if len(parts) >= 1:
                        bid_period_start = _parse_jp_date(parts[0])
                    if len(parts) >= 2:
                        bid_period_end = _parse_jp_date(parts[1])
                elif "開札期日" in lbl:
                    open_bid_date = _parse_jp_date(val)
                elif "特別売却期間" in lbl:
                    parts = re.split(r"〜|～|~", val)
                    if len(parts) >= 1:
                        special_sale_start = _parse_jp_date(parts[0])
                    if len(parts) >= 2:
                        special_sale_end = _parse_jp_date(parts[1])

        properties.append({
            "sale_unit_id": sale_unit_id,
            "court_id": court_id,
            "case_no_text": case_no_text,
            "case_no_parts": case_no_parts,
            "court_name_text": court_name_text,
            "sale_cls_label": sale_cls_label,
            "sale_standard_price": sale_standard_price,
            "bid_deposit": bid_deposit,
            "address_text": address_text,
            "transit_info": transit_info,
            "photo_url": photo_url,
            "photo_meta": photo_meta,
            "sale_status_text": sale_status_text,
            "bid_view_start": bid_view_start,
            "bid_period_start": bid_period_start,
            "bid_period_end": bid_period_end,
            "open_bid_date": open_bid_date,
            "special_sale_start": special_sale_start,
            "special_sale_end": special_sale_end,
        })

    return {"total": total, "properties": properties}


def parse_detail(html: str) -> dict[str, Any]:
    """매물 상세 페이지 파싱 — bit__paragraphBreaksTable + bit__multiHeadTable 기반.

    추출 항목:
      - prices: {sale_standard_price, bid_deposit, purchase_possible_price}
      - dates: {koji_start, view_start, bid_period, open_bid_date, sale_decision_date,
                special_sale_period}
      - properties: list[dict]  — 물건 1건당 종별/면적/용도/위치 등 key-value dict
                                  (bit__paragraphBreaksTable_th → _td 페어)
      - photos: list[str]  — 모든 .bit__image src
      - has_three_set_pdf: bool — 3点セット 다운로드 버튼 존재 여부
      - case_no_text, court_name_text
    """
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text(strip=True) if soup.title else None

    # 사건번호 + 법원
    case_no_text: str | None = None
    court_name_text: str | None = None
    head_p = soup.select_one(".bit__text_big.col-12.d-sm-inline")
    if head_p:
        text = head_p.get_text(" ", strip=True)
        m = CASE_NO_RE.search(text)
        if m:
            case_no_text = m.group(0)
            court_name_text = text[:m.start()].strip().rstrip("　 ")

    # 3종 가격 + 보증금 — bit__syousai_text_kakaku_container 안의 라벨-값
    prices: dict[str, int | None] = {
        "sale_standard_price": None,
        "bid_deposit": None,
        "purchase_possible_price": None,
    }
    container = soup.select_one(".bit__syousai_text_kakaku_container")
    if container:
        # 라벨 기반 페어링 — 단순 "다음 <p>=값" 위치 가정은 마크업에 다른 <p>가
        # 끼면 엉뚱한 금액이 붙음(잘못된 값이 card 가격을 덮어쓰고 가짜
        # valuation_history까지 생성). 라벨 뒤에서 '다음 라벨 전까지' 첫 가격을
        # 값으로 취하고, 소비한 값은 재사용 금지.
        PRICE_LABELS = {
            "売却基準価額": "sale_standard_price",
            "買受申出保証金": "bid_deposit",
            "買受可能価額": "purchase_possible_price",
        }
        texts = [p.get_text(strip=True) for p in container.find_all("p")]
        used: set[int] = set()
        for i, label in enumerate(texts):
            key = PRICE_LABELS.get(label)
            if not key:
                continue
            for j in range(i + 1, len(texts)):
                if texts[j] in PRICE_LABELS:
                    break  # 다음 라벨 시작 — 이 라벨의 값 없음
                if j in used:
                    continue
                price = _parse_price(texts[j])
                if price is not None:
                    prices[key] = price
                    used.add(j)
                    break

    # 매각기일 — multiHeadTable th-td 페어
    dates: dict[str, str | None] = {}
    for th in soup.select(".bit__multiHeadTable_th"):
        td = th.find_next_sibling()
        if not td or "bit__multiHeadTable_td" not in (td.get("class") or []):
            continue
        label = th.get_text(strip=True)
        val = td.get_text(strip=True)
        if label in ("公示開始日", "閲覧開始日", "開札期日", "売却決定期日"):
            key = {
                "公示開始日": "koji_start",
                "閲覧開始日": "view_start",
                "開札期日": "open_bid_date",
                "売却決定期日": "sale_decision_date",
            }[label]
            dates[key] = _parse_jp_date(val)
        elif label in ("入札期間", "特別売却期間"):
            parts = re.split(r"〜|～|~", val)
            start = _parse_jp_date(parts[0]) if parts else None
            end = _parse_jp_date(parts[1]) if len(parts) > 1 else None
            key = "bid_period" if label == "入札期間" else "special_sale_period"
            dates[key] = {"start": start, "end": end}

    # 물건 상세 — paragraphBreaksTable 키-값 (물건 N개일 수 있음)
    properties_list: list[dict[str, Any]] = []
    for table in soup.select(".bit__paragraphBreaksTable"):
        kv: dict[str, str] = {}
        ths = table.select(".bit__paragraphBreaksTable_th")
        tds = table.select(".bit__paragraphBreaksTable_td")
        for th, td in zip(ths, tds):
            label = th.get_text(strip=True)
            val = td.get_text(" ", strip=True)
            if label and val:
                kv[label] = val
        if kv:
            # 직전의 물건 헤더 (1．土地 등) — table 직전 형제 또는 부모에 있음
            head = table.find_previous("p", class_="bit__text_big")
            head_label = head.get_text(strip=True) if head else None
            properties_list.append({"head": head_label, "fields": kv})

    # 사진 — .bit__image src 모두
    photos: list[str] = []
    for img in soup.select(".bit__image"):
        src = img.get("src")
        if src and src.startswith("/data/image/"):
            photos.append(src)

    # 3点セット PDF — JS 흐름: POST /app/detail/pd001/h03 (확인) → GET pd001/h04 (다운로드)
    has_three_set_pdf = bool(soup.select_one("#threeSetPDF"))

    # 좌표 — hidden input (mapion API 호출용. WGS84 추정)
    lat_input = soup.select_one("input#latitude")
    lng_input = soup.select_one("input#longitude")
    latitude: float | None = None
    longitude: float | None = None
    try:
        if lat_input and lat_input.get("value"):
            latitude = float(lat_input["value"])
        if lng_input and lng_input.get("value"):
            longitude = float(lng_input["value"])
    except (TypeError, ValueError):
        latitude = longitude = None

    return {
        "title": title,
        "case_no_text": case_no_text,
        "court_name_text": court_name_text,
        "prices": prices,
        "dates": dates,
        "properties": properties_list,
        "photos": photos,
        "latitude": latitude,
        "longitude": longitude,
        "has_three_set_pdf": has_three_set_pdf,
    }
