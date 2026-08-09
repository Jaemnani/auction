"""명세서 텍스트를 좌표와 함께 추출 — 규칙 기반 표 복원용 (LLM 불필요).

innerText 는 시각 순서라 표의 열이 뒤섞인다. TreeWalker 로 모든 텍스트 노드를
훑고 Range.getBoundingClientRect() 로 좌표를 재면, y 로 행을 묶고 x 로 열을
가를 수 있어 표를 결정적으로 복원할 수 있다.
"""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "https://www.courtauction.go.kr"
OUT = Path(__file__).parent

EXTRACT = """() => {
  // 문서 텍스트는 캔버스 위에 깔린 p.script 레이어(font-size:0)에 있다.
  // Range 사각형은 0 이므로 반드시 parentElement 의 좌표를 쓴다.
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const out = [];
  let n;
  while ((n = walker.nextNode())) {
    const t = (n.nodeValue || '').trim();
    if (!t) continue;
    const pe = n.parentElement;
    if (!pe) continue;
    const b = pe.getBoundingClientRect();
    if (b.width === 0 && b.height === 0) continue;
    out.push({t, x: Math.round(b.x), y: Math.round(b.y),
              w: Math.round(b.width), h: Math.round(b.height)});
  }
  return out;
}"""


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, channel="chrome")
        ctx = await browser.new_context(locale="ko-KR", timezone_id="Asia/Seoul",
                                        viewport={"width": 1600, "height": 1400})
        page = await ctx.new_page()

        print("[1] UI 흐름 → 명세서")
        await page.goto(f"{BASE}/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ153F00.xml",
                        wait_until="domcontentloaded")
        await asyncio.sleep(6)
        await page.get_by_role("button", name="검색").first.click(timeout=15000)
        await asyncio.sleep(6)
        await page.get_by_text("경매", exact=False).filter(has_text="계").first.click(timeout=15000)
        await asyncio.sleep(7)
        await page.locator("a, [onclick]").filter(has_text="서울").first.click(timeout=15000)
        await asyncio.sleep(7)
        try:
            await page.get_by_role("button", name="매각물건명세서").first.click(timeout=15000)
        except Exception:
            await page.get_by_text("매각물건명세서", exact=False).first.click(timeout=15000)

        for _ in range(30):
            await asyncio.sleep(2)
            if len(ctx.pages) > 1:
                break
        vp = ctx.pages[-1]
        await asyncio.sleep(30)

        target = None
        for fr in vp.frames:
            if "streamdocs/view/sd" in fr.url:
                target = fr
                break
        if target is None:
            print("[stop] streamdocs 프레임 없음")
            await browser.close()
            return

        # 텍스트 레이어(p.script)가 채워질 때까지 폴링 — 렌더 전 추출 방지
        for i in range(40):
            cnt = await target.evaluate(
                "() => document.querySelectorAll('p.script').length")
            if cnt > 30:
                print(f"    텍스트 레이어 준비 @{i*3}s (p.script {cnt}개)")
                break
            await asyncio.sleep(3)
        else:
            print(f"    [warn] 텍스트 레이어 미완성 (p.script {cnt}개)")

        diag = await target.evaluate("""() => {
          const counts = {};
          document.querySelectorAll('*').forEach(e => {
            counts[e.tagName] = (counts[e.tagName]||0)+1;
          });
          let shadow = 0;
          document.querySelectorAll('*').forEach(e => { if (e.shadowRoot) shadow++; });
          const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          let tn = 0, sample = [];
          let n; while ((n = walker.nextNode())) {
            const t = (n.nodeValue||'').trim();
            if (!t) continue; tn++;
            if (sample.length < 8) {
              const pe = n.parentElement;
              const r = pe ? pe.getBoundingClientRect() : null;
              sample.push({t: t.slice(0,30), tag: pe && pe.tagName,
                cls: pe && String(pe.className).slice(0,40),
                rect: r ? [Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)] : null,
                cs: pe ? getComputedStyle(pe).fontSize + '/' + getComputedStyle(pe).visibility : ''});
            }
          }
          return {innerTextLen: (document.body.innerText||'').length,
                  textNodes: tn, shadowHosts: shadow,
                  topTags: Object.entries(counts).sort((a,b)=>b[1]-a[1]).slice(0,10),
                  sample};
        }""")
        print(f"[진단] innerTextLen={diag['innerTextLen']} textNodes={diag['textNodes']} shadow={diag['shadowHosts']}")
        nodes = await target.evaluate(EXTRACT)
        print(f"[2] 텍스트 노드 {len(nodes)}개 (좌표 포함)")
        (OUT / "coords.json").write_text(json.dumps(nodes, ensure_ascii=False, indent=1))

        # y 로 행 묶어 미리보기 (허용오차 4px)
        rows: dict[int, list] = {}
        for nd in nodes:
            key = round(nd["y"] / 4) * 4
            rows.setdefault(key, []).append(nd)
        print(f"[3] 행 {len(rows)}개 — 앞 30행 (x 순 정렬):")
        for y in sorted(rows)[:45]:
            cells = sorted(rows[y], key=lambda c: c["x"])
            line = "  |  ".join(f"{c['t']}@{c['x']}" for c in cells)
            print(f"    y={y:4d}  {line[:170]}")

        await browser.close()


asyncio.run(main())
