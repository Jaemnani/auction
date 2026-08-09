"""① StreamDocs 뷰어 렌더 방식 확인.

핵심 질문: 문서를 (a) DOM 텍스트로 그리는가 (b) canvas/이미지로 그리는가
 (a)면 Playwright 로 바로 읽으면 끝 — OCR/API 역분석 불필요
 (b)면 StreamDocs API 또는 OCR 필요
부수: 뷰어가 문서 데이터를 어디서 받는지 전체 요청 로그.
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "https://www.courtauction.go.kr"
OUT = Path(__file__).parent


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, channel="chrome")
        ctx = await browser.new_context(locale="ko-KR", timezone_id="Asia/Seoul",
                                        viewport={"width": 1600, "height": 1200})
        pvo: list[str] = []

        def hook(page):
            async def on_res(res):
                if "pvo.scourt.go.kr" in res.url:
                    u = res.url.split("scourt.go.kr")[-1].split("?")[0]
                    if u.endswith((".js", ".css", ".png", ".svg", ".woff2", ".ico")):
                        return
                    try:
                        n = len(await res.body())
                    except Exception:  # noqa: BLE001
                        n = -1
                    pvo.append(f"{res.status} {res.request.method} {u[:70]} "
                               f"{n:,}B ct={res.headers.get('content-type','')[:35]}")
            page.on("response", lambda r: asyncio.create_task(on_res(r)))

        page = await ctx.new_page(); hook(page); ctx.on("page", hook)

        print("[1] UI 흐름")
        await page.goto(f"{BASE}/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ153F00.xml",
                        wait_until="domcontentloaded")
        await asyncio.sleep(6)
        await page.get_by_role("button", name="검색").first.click(timeout=15000)
        await asyncio.sleep(6)
        await page.get_by_text("경매", exact=False).filter(has_text="계").first.click(timeout=15000)
        await asyncio.sleep(7)
        await page.locator("a, [onclick]").filter(has_text="서울").first.click(timeout=15000)
        await asyncio.sleep(7)
        print("[2] 명세서 클릭")
        try:
            await page.get_by_role("button", name="매각물건명세서").first.click(timeout=15000)
        except Exception:
            await page.get_by_text("매각물건명세서", exact=False).first.click(timeout=15000)

        # 뷰어 탭 확보
        for _ in range(30):
            await asyncio.sleep(2)
            if len(ctx.pages) > 1:
                break
        vp = ctx.pages[-1]
        print(f"[3] 뷰어 탭: {vp.url[:90]}")

        # 렌더 완료까지 폴링 (텍스트/캔버스 등장 감시)
        for i in range(30):
            await asyncio.sleep(3)
            info = await vp.evaluate("""() => {
                const t = (document.body.innerText || '').trim();
                return {
                  textLen: t.length,
                  canvas: document.querySelectorAll('canvas').length,
                  svg: document.querySelectorAll('svg').length,
                  img: document.querySelectorAll('img').length,
                  iframes: document.querySelectorAll('iframe').length,
                };
            }""")
            if info["textLen"] > 300 or info["canvas"] or info["svg"] > 3:
                print(f"    렌더 감지 @{(i+1)*3}s: {info}")
                break
        else:
            print(f"    렌더 미감지: {info}")

        print("\n[4] 뷰어 DOM 텍스트 (앞 1200자):")
        txt = await vp.evaluate("() => document.body.innerText || ''")
        print(repr(txt[:1200]))

        # iframe 안에 있을 수도 — 모든 프레임 텍스트
        print("\n[5] 프레임별 텍스트 길이:")
        for fr in vp.frames:
            try:
                ft = await fr.evaluate("() => document.body ? document.body.innerText : ''")
            except Exception:  # noqa: BLE001
                ft = ""
            print(f"    {fr.url[:70]:70s} len={len(ft)}")
            if len(ft) > 300:
                (OUT / "viewer_text.txt").write_text(ft)
                print(f"      → viewer_text.txt 저장, 앞 600자:\n{ft[:600]!r}")

        await vp.screenshot(path=str(OUT / "viewer_render.png"), full_page=True)
        print(f"\n[6] pvo 요청 ({len(pvo)}건):")
        for r in pvo:
            print(f"    {r}")

        await browser.close()


asyncio.run(main())
