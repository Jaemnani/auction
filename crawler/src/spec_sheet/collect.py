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
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

BASE = "https://www.courtauction.go.kr"
SEARCH_BY_DATE = f"{BASE}/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ153F00.xml"

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


async def capture_spec_sheet(court_name: str, case_no: str,
                             *, headless: bool = True,
                             timeout_s: float = 240) -> Capture:
    """법원명·사건번호로 명세서를 열어 좌표 텍스트 노드를 확보.

    court_name: 기일별검색의 법원 select 표시명 (예: '서울중앙지방법원')
    case_no:    '2024타경2532'
    """
    from playwright.async_api import async_playwright  # 지연 import (선택 의존성)

    async with async_playwright() as pw:
        # 시스템 Chrome — 번들 Chromium 다운로드(150MB) 회피 + 실제 지문
        browser = await pw.chromium.launch(headless=headless, channel="chrome")
        try:
            ctx = await browser.new_context(
                locale="ko-KR", timezone_id="Asia/Seoul",
                viewport={"width": 1600, "height": 1400})
            page = await ctx.new_page()

            await page.goto(SEARCH_BY_DATE, wait_until="domcontentloaded")
            await asyncio.sleep(6)
            await page.get_by_role("button", name="검색").first.click(timeout=15000)
            await asyncio.sleep(6)

            # 담당계 → 물건 목록 → 첫 물건. (사건 딥링크가 없어 UI 를 밟는다)
            await page.get_by_text("경매", exact=False).filter(
                has_text="계").first.click(timeout=15000)
            await asyncio.sleep(7)
            await page.get_by_text(case_no, exact=False).first.click(timeout=15000)
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
