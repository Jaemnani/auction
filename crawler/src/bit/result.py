"""BIT 売却結果(매각결과) 수집 — 낙찰가·개찰결과.

기존 검색 피드(competitive)에는 낙찰가가 없다. 낙찰 결과는 BIT 의 별도
「売却結果」 섹션에만 있고, 이 모듈이 그 흐름을 담당한다.

흐름·필드·함정은 docs/bit_sale_result_recon.md 참고. 요약:

    POST /app/area/pk001/h01          {tabId: result}          지역 선택
    POST /app/area/pk001/h02          {blockCls, tabId}        도도부현+법원
    POST /app/peroidsearch/ps007/h02  {prefecturesId, ...}     법원 라디오 목록
    POST /app/peroidsearch/ps007/h04  {courtId, ...}           開札期日 목록 (AJAX 조각)
    POST /app/peroidsearch/ps007/h08  {courtId, saleScdId,...} 売却結果一覧

⚠ h08 은 h02·h04 를 거친 **같은 세션**에서만 동작하고, 필드가 하나라도 빠지면
  500 이다(특히 peroidCourtId·codeCls·mapShowFlag). 필드 세트를 임의로 줄이지 말 것.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .client import BitClient

logger = logging.getLogger(__name__)

# 期間入札 = 1 (ps007) / 特別売却 = 2 (ps008)
SALE_TYPE_PERIOD = "period"
SALE_TYPE_SPECIAL = "special"

_PATHS = {
    SALE_TYPE_PERIOD: {
        "courts": "/app/peroidsearch/ps007/h02",
        "dates": "/app/peroidsearch/ps007/h04",
        "list": "/app/peroidsearch/ps007/h08",
        "sale_type": "1",
        "court_field": "peroidCourtId",
        "cls_field": "peroidSaleCls",
        "flg_field": "peroidSearchFlg",
    },
    SALE_TYPE_SPECIAL: {
        "courts": "/app/specialsearch/ps008/h02",
        "dates": "/app/specialsearch/ps008/h04",
        "list": "/app/specialsearch/ps008/h08",
        "sale_type": "2",
        "court_field": "specialCourtId",
        "cls_field": "specialSaleCls",
        "flg_field": "specialSearchFlg",
    },
}


@dataclass
class Court:
    court_id: str
    name: str


@dataclass
class OpenBidDate:
    sale_scd_id: str          # 20000014084
    label: str                # 令和08年07月29日
    date: str | None          # 2026-07-29 (서기 변환)


@dataclass
class SaleResult:
    court_id: str
    case_no: str              # 令和08年(ケ)第48号
    property_no: str          # "1，2" 원문
    sale_cls_label: str | None
    sale_price: int | None            # 売却価額 — 낙찰가 (不売/取下 면 None)
    sale_standard_price: int | None   # 売却基準価額
    address_text: str | None
    result_cls: str | None            # 売却 / 不売 / 取下
    bidder_count: int | None          # 入札者数
    winner_kind: str | None           # 法人 / 個人
    open_bid_date: str | None         # 2026-07-29
    sale_type: str = SALE_TYPE_PERIOD
    raw: dict[str, Any] = field(default_factory=dict)


# ---------- 파싱 헬퍼 ----------

_ERA_BASE = {"令和": 2018, "平成": 1988, "昭和": 1925}
_JP_DATE = re.compile(r"(令和|平成|昭和)\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


def jp_date_to_iso(text: str) -> str | None:
    """令和08年07月29日 → 2026-07-29."""
    m = _JP_DATE.search(text or "")
    if not m:
        return None
    era, yy, mm, dd = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
    base = _ERA_BASE.get(era)
    if base is None:
        return None
    return f"{base + yy:04d}-{mm:02d}-{dd:02d}"


def _money(text: str | None) -> int | None:
    """28,000,000円 → 28000000. '-' 이나 빈 값은 None."""
    if not text:
        return None
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else None


def _int(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


# 결과 1건 = regionBox 시작 ~ 다음 regionBox 시작.
# 중첩 <div> 를 정규식으로 닫으려 하면 블록이 짧게 잘려 뒤쪽 필드(개찰결과·
# 입찰자수 등)를 통째로 놓친다 — 실제로 그렇게 잘렸었다.
_BOX_MARK = "bit__currentSearchCondition_regionBox"


def _iter_boxes(html: str):
    starts = [m.start() for m in re.finditer(_BOX_MARK, html)]
    for i, st in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(html)
        yield html[st:end]
# 가격류: <p ...>라벨</p> <p ...>값</p>
_PAIR_TMPL = r"{label}\s*</p>\s*<p[^>]*>(.*?)</p>"
# 결과류(물건번호·개찰결과·입찰자수·낙찰자자격):
#   <div class="bit__result_InfoHeader ...">라벨</div> <div ...>값</div>
_INFO_TMPL = r'bit__result_InfoHeader[^>]*>\s*{label}[^<]*</div>\s*<div[^>]*>(.*?)</div>'
# 소재지: 아이콘 뒤 텍스트
_ADDR = re.compile(r'bit__icon_access[^>]*>\s*</i>\s*(.*?)</p>', re.S)

# 페이지네이션 — 결과 페이지의 resultDetailForm 을 그대로 재제출한다(currPage 만 교체).
_PAGING_PATH = "/app/resultlist/pr002/h03"
_RESULT_FORM_FIELDS = (
    "prefecturesId", "courtId", "saleClsList", "tenderDate", "specialSaleDate",
    "saleScdId", "fiscalYear", "codeCls", "caseNo", "saleType", "blockCls",
    "blockName", "tabId", "searchType", "mapShowFlag", "mapSelectedAreaName",
    "peroidSearchFlg", "specialSearchFlg", "pageSize", "currPage", "totalCount",
    "navigationFlg",
)


def parse_result_form(html: str) -> dict[str, str]:
    """결과 페이지의 resultDetailForm hidden 값 → 다음 페이지 요청 본문."""
    i = html.find('id="resultDetailForm"')
    if i < 0:
        return {}
    inner = html[i:html.find("</form>", i)]
    out: dict[str, str] = {}
    for m in re.finditer(r'<input([^>]*)>', inner):
        a = m.group(1)
        n = re.search(r'name="([^"]*)"', a)
        if not n or n.group(1) not in _RESULT_FORM_FIELDS:
            continue
        v = re.search(r'value="([^"]*)"', a)
        out[n.group(1)] = v.group(1) if v else ""
    # saleClsList 가 "[1, 2, 3, 4]" 로 렌더되는 경우가 있어 정규화
    if out.get("saleClsList", "").startswith("["):
        out["saleClsList"] = ",".join(re.findall(r"\d", out["saleClsList"]))
    return out


def parse_total_count(html: str) -> int | None:
    """N件中 표기에서 전체 건수."""
    m = re.search(r'name="totalCount"[^>]*value="(\d+)"', html)
    return int(m.group(1)) if m else None


def _pair(html: str, label: str) -> str | None:
    """가격 라벨-값 쌍 (<p>라벨</p><p>값</p>)."""
    m = re.search(_PAIR_TMPL.format(label=re.escape(label)), html, re.S)
    return _clean(m.group(1)) if m else None


def _info(html: str, label: str) -> str | None:
    """결과 정보 카드 (InfoHeader/값 div 쌍)."""
    m = re.search(_INFO_TMPL.format(label=re.escape(label)), html, re.S)
    return _clean(m.group(1)) if m else None


def _dash_to_none(v: str | None) -> str | None:
    """'-' / '—' / 빈 문자열은 값 없음."""
    if v is None:
        return None
    t = v.strip()
    return None if t in ("", "-", "—", "ー") else t


def parse_sale_results(html: str, *, court_id: str, open_bid_date: str | None,
                       sale_type: str = SALE_TYPE_PERIOD) -> list[SaleResult]:
    """売却結果一覧 HTML → SaleResult 목록.

    검색 조건 표시 영역에도 같은 클래스의 박스가 있으므로 '売却価額' 을 포함한
    박스만 결과로 본다.
    """
    out: list[SaleResult] = []
    for block in _iter_boxes(html):
        if "売却価額" not in block:
            continue
        case_m = re.search(r"(令和|平成|昭和)\s*\d{1,2}\s*年\s*\([ケヌ]\)\s*第\s*\d+\s*号", block)
        if not case_m:
            continue
        badge = re.search(r'class="[^"]*badge[^"]*"[^>]*>(.*?)</span>', block, re.S)
        addr_m = _ADDR.search(block)
        # 物件番号는 전각 쉼표 구분 ("1 ，2 ") — 반각으로 정규화
        prop_no = _dash_to_none(_info(block, "物件番号")) or ""
        prop_no = re.sub(r"\s*[，,]\s*", ",", prop_no).strip()
        out.append(SaleResult(
            court_id=court_id,
            case_no=_clean(case_m.group(0)).replace(" ", ""),
            property_no=prop_no,
            sale_cls_label=_clean(badge.group(1)) if badge else None,
            sale_price=_money(_dash_to_none(_pair(block, "売却価額"))),
            sale_standard_price=_money(_dash_to_none(_pair(block, "売却基準価額"))),
            address_text=_dash_to_none(_clean(addr_m.group(1))) if addr_m else None,
            result_cls=_dash_to_none(_info(block, "開札結果") or _info(block, "売却結果")),
            bidder_count=_int(_dash_to_none(_info(block, "入札者数"))),
            winner_kind=_dash_to_none(_info(block, "落札者資格")),
            open_bid_date=open_bid_date,
            sale_type=sale_type,
            raw={"html_len": len(block)},
        ))
    return out


def parse_courts(html: str, *, sale_type: str = SALE_TYPE_PERIOD) -> list[Court]:
    """도도부현 선택 응답 → 법원 라디오 목록."""
    field_name = _PATHS[sale_type]["court_field"]
    out: list[Court] = []
    # <input name=... value="31111" ...> ... <label for="courtId_31111">東京地方裁判所本庁</label>
    for m in re.finditer(
        rf'name="{field_name}"[^>]*value="([^"]*)"[^>]*>\s*<label[^>]*>(.*?)</label>',
        html, re.S,
    ):
        out.append(Court(m.group(1), _clean(m.group(2))))
    return out


def parse_open_bid_dates(fragment: str) -> tuple[list[OpenBidDate], dict[str, str]]:
    """h04 AJAX 조각 → (開札期日 목록, h08 에 그대로 넘겨야 할 hidden 값들).

    codeCls/fiscalYear 는 여기서 안 가져오면 h08 이 500 난다.
    """
    dates: list[OpenBidDate] = []
    sel = re.search(r'name="saleScdId"[^>]*>(.*?)</select>', fragment, re.S)
    if sel:
        for v, label in re.findall(r'value="([^"]*)"[^>]*>([^<]*)<', sel.group(1)):
            lb = _clean(label)
            dates.append(OpenBidDate(v, lb, jp_date_to_iso(lb)))
    extras: dict[str, str] = {}
    for name in ("fiscalYear", "codeCls"):
        m = re.search(rf'name="{name}"[^>]*value="([^"]*)"', fragment)
        if m:
            extras[name] = m.group(1)
        else:  # select 형태면 첫 option
            sm = re.search(rf'name="{name}"[^>]*>(.*?)</select>', fragment, re.S)
            if sm:
                om = re.search(r'value="([^"]*)"', sm.group(1))
                if om:
                    extras[name] = om.group(1)
    return dates, extras


# ---------- 수집 흐름 ----------

class SaleResultFetcher:
    """BitClient 세션 위에서 売却結果 흐름을 진행한다.

    세션 순서 의존이 있어(h02 → h04 → h08) 메서드 호출 순서를 지켜야 한다.
    """

    def __init__(self, client: BitClient, *, sale_type: str = SALE_TYPE_PERIOD) -> None:
        self.c = client
        self.sale_type = sale_type
        self.p = _PATHS[sale_type]

    async def enter(self, block_cls: str) -> None:
        """売却結果 탭 진입 (세션에 tabId=result 컨텍스트 확보)."""
        await self.c._post_html(
            "/app/area/pk001/h01", {"tabId": "result", "blockCls": ""}, referer="/",
        )
        await self.c._post_html(
            "/app/area/pk001/h02", {"blockCls": block_cls, "tabId": "result"},
            referer="/app/area/pk001/h01",
        )

    def _base_body(self, block_cls: str, block_name: str, prefecture_id: str) -> dict[str, Any]:
        return {
            "blockCls": block_cls,
            "blockName": block_name,
            "tabId": "result",
            "saleType": self.p["sale_type"],
            self.p["cls_field"]: ["1", "2", "3", "4"],
            "saleClsList": "1,2,3,4",
            "prefecturesId": prefecture_id,
            "mapShowFlag": "1",
            "mapSelectedAreaName": "",
        }

    async def courts(self, *, block_cls: str, block_name: str,
                     prefecture_id: str) -> list[Court]:
        html = await self.c._post_html(
            self.p["courts"],
            {**self._base_body(block_cls, block_name, prefecture_id),
             "courtId": "", self.p["flg_field"]: "", "searchType": ""},
            referer="/app/area/pk001/h02",
        )
        return parse_courts(html, sale_type=self.sale_type)

    async def open_bid_dates(self, court_id: str) -> tuple[list[OpenBidDate], dict[str, str]]:
        frag = await self.c._post_html(
            self.p["dates"],
            {"courtId": court_id, "saleScdId": "", "fiscalYear": "",
             "codeCls": "", "caseNo": "", self.p["flg_field"]: "0"},
            referer=self.p["courts"],
        )
        return parse_open_bid_dates(frag)

    async def results(
        self, *, block_cls: str, block_name: str, prefecture_id: str,
        court_id: str, date: OpenBidDate, extras: dict[str, str],
    ) -> list[SaleResult]:
        body = {
            **self._base_body(block_cls, block_name, prefecture_id),
            self.p["court_field"]: court_id,
            "courtId": court_id,
            "saleScdId": date.sale_scd_id,
            "fiscalYear": extras.get("fiscalYear", ""),
            "codeCls": extras.get("codeCls", ""),
            "caseNo": "",
            "error": "",
            self.p["flg_field"]: "",
            "searchType": "0",
        }
        html = await self.c._post_html(self.p["list"], body, referer=self.p["courts"])
        rows = parse_sale_results(
            html, court_id=court_id, open_bid_date=date.date, sale_type=self.sale_type,
        )
        total = parse_total_count(html)
        logger.info(
            "court=%s date=%s(%s): %d/%s results",
            court_id, date.label, date.date, len(rows), total,
        )
        # 2페이지 이후 — 결과 폼을 그대로 재제출(currPage 만 교체)
        form = parse_result_form(html)
        page_size = int(form.get("pageSize") or 10)
        if total and form and page_size > 0:
            pages = (total + page_size - 1) // page_size
            for page in range(2, pages + 1):
                nxt = await self.c._post_html(
                    _PAGING_PATH, {**form, "currPage": str(page)},
                    referer=self.p["list"],
                )
                more = parse_sale_results(
                    nxt, court_id=court_id, open_bid_date=date.date,
                    sale_type=self.sale_type,
                )
                if not more:
                    break
                rows.extend(more)
        return rows
