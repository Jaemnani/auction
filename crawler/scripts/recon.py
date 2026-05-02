"""
법원경매정보(courtauction.go.kr) 사이트 정찰 스크립트.

W2X 기반 RIA 프레임워크라서 화면 URL과 실제 데이터 API가 분리돼있음.
브라우저로 사이트를 정상 사용하면서 발생하는 모든 XHR/fetch를 캡처해
백엔드 API 엔드포인트의 URL/method/payload/response shape를 발굴한다.

사용법:
    /Users/jaemoonyeah/workspace/venv_common/bin/python crawler/scripts/recon.py

기본은 headed 모드 — 직접 검색을 클릭하면 그 트래픽이 모두 잡힘.
끝나면 터미널에서 Enter.

결과:
    crawler/data/recon/<timestamp>/
        requests.jsonl   모든 비정적 요청
        responses.jsonl  응답 메타
        bodies/          응답 본문 (JSON/XML/HTML)
        page_main.html   초기 페이지 스냅샷
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import Request, Response, async_playwright

BASE_URL = "https://www.courtauction.go.kr/pgj/index.on?device=pc"

SAVE_BODY_TYPES = re.compile(r"json|xml|javascript|html|text/plain", re.I)
IGNORE_URL = re.compile(
    r"\.(png|jpe?g|gif|svg|woff2?|ttf|eot|css|ico)(\?|$)", re.I
)


async def run(headless: bool, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    bodies_dir = output_dir / "bodies"
    bodies_dir.mkdir(exist_ok=True)

    req_fp = (output_dir / "requests.jsonl").open("w", encoding="utf-8")
    res_fp = (output_dir / "responses.jsonl").open("w", encoding="utf-8")
    body_counter = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
        )
        page = await context.new_page()

        def on_request(req: Request) -> None:
            if IGNORE_URL.search(req.url):
                return
            entry = {
                "ts": datetime.now().isoformat(timespec="milliseconds"),
                "method": req.method,
                "url": req.url,
                "resource_type": req.resource_type,
                "headers": req.headers,
                "post_data": req.post_data,
            }
            req_fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
            req_fp.flush()

        async def on_response(resp: Response) -> None:
            nonlocal body_counter
            if IGNORE_URL.search(resp.url):
                return
            try:
                headers = await resp.all_headers()
            except Exception:
                headers = {}
            ctype = headers.get("content-type", "")
            entry: dict = {
                "ts": datetime.now().isoformat(timespec="milliseconds"),
                "url": resp.url,
                "status": resp.status,
                "content_type": ctype,
                "resource_type": resp.request.resource_type,
            }
            if SAVE_BODY_TYPES.search(ctype) and resp.request.resource_type in (
                "xhr",
                "fetch",
                "document",
            ):
                try:
                    body = await resp.body()
                    body_counter += 1
                    ext = (
                        "json"
                        if "json" in ctype
                        else "xml"
                        if "xml" in ctype
                        else "html"
                        if "html" in ctype
                        else "txt"
                    )
                    body_path = bodies_dir / f"{body_counter:04d}.{ext}"
                    body_path.write_bytes(body)
                    entry["body_file"] = body_path.name
                except Exception as e:
                    entry["body_error"] = str(e)
            res_fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
            res_fp.flush()

        page.on("request", on_request)
        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        print(f"[+] 정찰 시작: {BASE_URL}")
        try:
            await page.goto(BASE_URL, wait_until="networkidle", timeout=60_000)
        except Exception as e:
            print(f"[!] networkidle 대기 중 timeout/오류: {e} (계속 진행)")

        try:
            (output_dir / "page_main.html").write_text(
                await page.content(), encoding="utf-8"
            )
        except Exception:
            pass

        if headless:
            print("[+] headless 모드 — 60초 대기")
            await page.wait_for_timeout(60_000)
        else:
            print(
                "[+] headed 모드 — 브라우저에서 부동산 물건 검색 흐름을 직접 클릭하세요.\n"
                "    원하는 화면을 다 본 뒤 이 터미널에서 Enter 누르면 캡처를 마무리합니다."
            )
            await asyncio.get_event_loop().run_in_executor(None, input)

        await browser.close()

    req_fp.close()
    res_fp.close()
    print(f"[+] 결과 저장: {output_dir.resolve()}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    script_dir = Path(__file__).resolve().parent
    crawler_root = script_dir.parent
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(args.out) if args.out else crawler_root / "data" / "recon" / ts
    asyncio.run(run(args.headless, out))


if __name__ == "__main__":
    main()
