"""
모든 화면 W2X 파일을 fetch해서 endpoint를 전수 발굴.

입력: 화면 ID 리스트 (recon에서 추출한 것)
출력: data/w2x/<screen_id>.xml + 화면 → endpoint 매핑 JSON
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx

BASE = "https://www.courtauction.go.kr"
W2X_DIR_GUESS = "/pgj/ui/pgj100/"  # 1차 정찰에서 본 패턴 — 다른 디렉토리는 404로 나오면 추가 시도

SCREENS = [
    "PGJ111M01.xml", "PGJ111M02.xml",
    "PGJ111P01.xml", "PGJ111P02.xml", "PGJ111P03.xml", "PGJ111P04.xml",
    "PGJ111P05.xml", "PGJ111P06.xml", "PGJ111P07.xml", "PGJ111P08.xml", "PGJ111P09.xml",
    "PGJ141M00.xml", "PGJ141M02.xml",
    "PGJ151F00.xml", "PGJ152F00.xml", "PGJ152P01.xml", "PGJ153F00.xml",
    "PGJ154M00.xml", "PGJ155M00.xml", "PGJ157M00.xml", "PGJ158M00.xml", "PGJ159M00.xml",
    "PGJ15BP06.xml",
    "PGJ161M01.xml", "PGJ162M01.xml", "PGJ163M01.xml", "PGJ164M01.xml",
    "PGJ171M01.xml", "PGJ171M02.xml", "PGJ172M01.xml", "PGJ173F01.xml", "PGJ174M01.xml",
    "PGJ175M01.xml", "PGJ176F01.xml", "PGJ177F01.xml", "PGJ177M01.xml", "PGJ177M02.xml",
    "PGJ181M01.xml", "PGJ182F00.xml", "PGJ184M01.xml", "PGJ185M01.xml",
    "PGJ192M01.xml", "PGJ193M00.xml", "PGJ194M00.xml",
    "PGJ195M00.xml", "PGJ195M01.xml", "PGJ195M03.xml", "PGJ196M01.xml",
]

ON_RE = re.compile(r"/pgj/[A-Za-z0-9_/]+\.on")
TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.I)
DESC_RE = re.compile(r"description[^<>]*?>\s*([^<]+?)\s*<", re.I)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Referer": "https://www.courtauction.go.kr/pgj/index.on?device=pc",
}


async def fetch_one(client: httpx.AsyncClient, screen: str) -> tuple[str, int, str]:
    url = f"{BASE}{W2X_DIR_GUESS}{screen}"
    r = await client.get(url, headers=HEADERS, timeout=15)
    return screen, r.status_code, r.text


async def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "data" / "w2x"
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: dict = {}
    sem = asyncio.Semaphore(5)

    async with httpx.AsyncClient(http2=False, follow_redirects=True) as client:

        async def worker(screen: str):
            async with sem:
                try:
                    sid, status, body = await fetch_one(client, screen)
                except Exception as e:
                    summary[screen] = {"error": str(e)}
                    return
                if status != 200 or len(body) < 100:
                    summary[sid] = {"status": status, "len": len(body)}
                    return
                (out_dir / sid).write_text(body, encoding="utf-8")
                ons = sorted(set(ON_RE.findall(body)))
                title_m = TITLE_RE.search(body)
                desc_m = DESC_RE.search(body)
                summary[sid] = {
                    "status": status,
                    "len": len(body),
                    "title": title_m.group(1).strip() if title_m else None,
                    "desc": desc_m.group(1).strip() if desc_m else None,
                    "endpoints": ons,
                }

        await asyncio.gather(*(worker(s) for s in SCREENS))

    summary_path = out_dir.parent / "w2x_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[+] saved {len(summary)} screens → {out_dir}")
    print(f"[+] summary → {summary_path}")

    print("\n=== 화면별 endpoint 요약 ===")
    for sid in sorted(summary):
        info = summary[sid]
        if "endpoints" not in info:
            print(f"  [{sid}] !! status={info.get('status')} len={info.get('len')}")
            continue
        eps = info["endpoints"]
        title = info.get("title") or info.get("desc") or ""
        print(f"  [{sid}] eps={len(eps):<2} {title}")
        for ep in eps:
            print(f"          {ep}")


if __name__ == "__main__":
    asyncio.run(main())
