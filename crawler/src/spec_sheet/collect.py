"""매각물건명세서 수집 — Playwright 로 UI 를 몰아 문서 텍스트를 좌표와 함께 확보.

⚠ 왜 UI 를 클릭해야 하나 (docs/api_recon.md, spec_sheet_automation.md):
   API 를 코드에서 직접 POST 하면 `{"data":{"ipcheck":false}}` 로 거부된다.
   IP·쿠키·회선을 바꿔도 같고, **실제 UI 클릭 흐름만 통과**한다.
   그래서 헤드리스 브라우저로 사람과 같은 경로를 밟는다.

⚠ 요청량 주의: 매물당 30~60초 + 여러 요청. 일괄 수집은 차단 위험이 크므로
   온디맨드(사용자가 연 매물만)로 쓰는 것을 전제로 한다.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

BASE = "https://www.courtauction.go.kr"
# 기일별검색 — 물건 상세(PGJ15BM01, 명세서 버튼 보유)까지 도달하는 검증된 경로.
#   경매사건검색(PGJ159M00)은 '사건내역'까지만 가고 물건 상세 링크가 없어 부적합.
#   물건상세검색(PGJ151M01)은 검색 폼이 이 방식으로 안 잡혀 보류.
SEARCH_BY_DATE = f"{BASE}/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ153F00.xml"

# WebSquare 컨트롤 id (실측). rlet=부동산 / mvprp=동산 — 부동산 쪽을 쓴다.
SEL_COURT = "#mf_wfm_mainFrame_sbx_rletDxdyCortOfc"
BTN_SEARCH = "#mf_wfm_mainFrame_btn_rletSrch"

_CASE_RE = re.compile(r"(\d{4})\s*타경\s*(\d+)")
# 물건 목록 페이지 탐색 상한 — 담당계당 100건 초과도 있음(실측 129건)
_MAX_LIST_PAGES = 12
_PAGER_ID_PREFIX = "mf_wfm_mainFrame_pgl_gdsDtlSrchPage_page_"


def split_case_no(case_no: str) -> tuple[str, str] | None:
    """'2025타경30751' → ('2025', '30751')"""
    m = _CASE_RE.search(case_no or "")
    return (m.group(1), m.group(2)) if m else None

# 문서 텍스트는 캔버스 위 p.script 레이어(font-size:0)에 있다.
# Range 사각형은 0×0 이므로 반드시 parentElement 좌표를 쓴다.
EXTRACT_JS = """() => {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const out = []; let n;
  while ((n = walker.nextNode())) {
    const t = (n.nodeValue || '').trim(); if (!t) continue;
    const pe = n.parentElement; if (!pe) continue;
    const b = pe.getBoundingClientRect();
    if (b.width === 0 && b.height === 0) continue;
    out.push({t, x: Math.round(b.x), y: Math.round(b.y),
              w: Math.round(b.width), h: Math.round(b.height)});
  }
  return out;
}"""


@dataclass
class Capture:
    nodes: list[dict[str, Any]]
    viewer_url: str | None
    ok: bool
    reason: str = ""


async def _wait_text_layer(frame, tries: int = 40, gap: float = 3.0) -> int:
    """렌더 완료 폴링. 안 기다리면 빈 문서를 읽는다 (실측: 4개 vs 66개)."""
    count = 0
    for _ in range(tries):
        try:
            count = await frame.evaluate(
                "() => document.querySelectorAll('p.script').length")
        except Exception:  # noqa: BLE001 — 프레임 전환 중
            count = 0
        if count > 30:
            return count
        await asyncio.sleep(gap)
    return count


async def _find_case_across_pages(page, case_no: str) -> bool:
    """물건 목록을 페이지 넘기며 사건번호를 찾아 클릭. 찾으면 True.

    목록은 담당계 기준이라 100건을 넘기도 한다(실측 129건/7건 표시).
    '다음' 링크가 없거나 페이지가 안 바뀌면 중단한다.
    """
    for pg in range(1, _MAX_LIST_PAGES + 1):
        if pg > 1:
            # 페이저는 WebSquare w2pageList — 숫자 페이지마다 고유 id 가 있다(실측).
            # '다음/›' 텍스트 링크는 label 이 비어 있어 role=link 로는 안 잡힌다.
            sel = f"#{_PAGER_ID_PREFIX}{pg}"
            if await page.locator(sel).count() == 0:
                return False           # 그 페이지 없음 = 마지막
            await page.click(sel, timeout=8000)
            await asyncio.sleep(5)
        # ⚠ 사건번호 셀은 링크가 아니다 — 클릭 가능한 건 같은 행의 소재지 anchor.
        #   사건번호 텍스트를 직접 클릭하면 페이지에 있어도 실패한다(실측:
        #   목록 2페이지에 대상이 있는데 get_by_text().click() 가 계속 실패했음).
        row = page.locator("tr").filter(has_text=case_no).first
        if await row.count() > 0:
            try:
                await row.locator("a").first.click(timeout=8000)
                return True
            except Exception as e:  # noqa: BLE001
                logger.info("행은 찾았으나 링크 클릭 실패(p%d): %s", pg, e)
    return False


async def capture_spec_sheet(court_name: str, case_no: str,
                             *, sale_date: str | None = None,
                             headless: bool = True) -> Capture:
    """법원명·사건번호로 명세서를 열어 좌표 텍스트 노드를 확보.

    court_name: 법원 select 표시명 (예: '서울중앙지방법원', '충주지원')
    case_no:    '2024타경2532'
    sale_date:  'YYYY-MM-DD' — 여러 기일 중 해당 행을 고르는 데 사용(선택)
    """
    from playwright.async_api import async_playwright  # 지연 import (선택 의존성)

    parts = split_case_no(case_no)
    if not parts:
        return Capture([], None, False, f"사건번호 형식 불명: {case_no}")
    del parts  # 형식 검증용 — 기일별검색 경로는 연도/일련번호를 따로 안 쓴다

    async with async_playwright() as pw:
        # 시스템 Chrome — 번들 Chromium 다운로드(150MB) 회피 + 실제 지문
        browser = await pw.chromium.launch(headless=headless, channel="chrome")
        try:
            ctx = await browser.new_context(
                locale="ko-KR", timezone_id="Asia/Seoul",
                viewport={"width": 1600, "height": 1400})
            page = await ctx.new_page()

            # 기일별검색 — 법원을 반드시 고른다.
            # (안 고르면 기본값 서울중앙으로 검색돼 다른 법원 사건을 못 찾는다 — 실측)
            await page.goto(SEARCH_BY_DATE, wait_until="domcontentloaded")
            await asyncio.sleep(7)
            await page.select_option(SEL_COURT, label=court_name, timeout=15000)
            await asyncio.sleep(1)
            await page.click(BTN_SEARCH, timeout=15000)
            await asyncio.sleep(7)

            body = await page.inner_text("body")
            if "보안정책" in body:
                return Capture([], None, False, "차단(보안정책)")

            # 매각일정 표에서 담당계 링크 → 물건 목록.
            # sale_date 가 주어지면 그 기일 행을 고른다 (여러 기일이 잡힐 수 있음).
            clicked = False
            if sale_date:
                ymd = sale_date.replace("-", ".")
                try:
                    row = page.locator("tr").filter(has_text=ymd).first
                    await row.locator("a").first.click(timeout=10000)
                    clicked = True
                except Exception:  # noqa: BLE001
                    logger.info("기일 %s 행 못 찾음 — 첫 담당계로 폴백", ymd)
            if not clicked:
                await page.get_by_text("경매", exact=False).filter(
                    has_text="계").first.click(timeout=15000)
            await asyncio.sleep(7)

            # 물건 목록에서 해당 사건 클릭 → 물건 상세(PGJ15BM01).
            # ⚠ 목록은 페이징된다 (실측: 총 129건인데 한 화면에 7건) —
            #   첫 페이지만 보고 "없음" 처리하면 대부분 실패한다.
            if not await _find_case_across_pages(page, case_no):
                return Capture([], None, False,
                               f"목록 {_MAX_LIST_PAGES}페이지 안에 {case_no} 없음")
            await asyncio.sleep(7)

            body = await page.inner_text("body")
            if "보안정책" in body:
                return Capture([], None, False, "차단(보안정책)")
            if "매각물건명세서" not in body:
                return Capture([], None, False, "명세서 버튼 없음(공개 전이거나 대상 아님)")

            try:
                await page.get_by_role(
                    "button", name="매각물건명세서").first.click(timeout=15000)
            except Exception:  # noqa: BLE001
                await page.get_by_text(
                    "매각물건명세서", exact=False).first.click(timeout=15000)

            # 뷰어 탭
            for _ in range(30):
                await asyncio.sleep(2)
                if len(ctx.pages) > 1:
                    break
            else:
                return Capture([], None, False, "뷰어 탭 미오픈")
            vp = ctx.pages[-1]

            target = None
            for _ in range(20):
                for fr in vp.frames:
                    if "streamdocs/view/sd" in fr.url:
                        target = fr
                        break
                if target:
                    break
                await asyncio.sleep(2)
            if target is None:
                return Capture([], vp.url, False, "streamdocs 프레임 없음")

            n = await _wait_text_layer(target)
            if n <= 30:
                return Capture([], vp.url, False, f"텍스트 레이어 미완성({n})")

            nodes = await target.evaluate(EXTRACT_JS)
            return Capture(nodes, vp.url, True)
        except Exception as e:  # noqa: BLE001
            logger.warning("capture 실패 %s %s: %s", court_name, case_no, e)
            return Capture([], None, False, f"{type(e).__name__}: {e}")
        finally:
            await browser.close()
