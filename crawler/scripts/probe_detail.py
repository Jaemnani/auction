"""사건 detail API 검증 — selectAuctnCsSrchRslt.on."""

import json
from pathlib import Path

import httpx

# 1차 검색 응답에서 첫 row 가져오기
search_result = json.loads(
    Path("/Users/jaemoonyeah/workspace/auction/crawler/data/probe/search_response_001.json").read_text()
)
first = search_result["data"]["dlt_srchResult"][0]
print(f"target: {first['srnSaNo']} ({first['boCd']}) 매물#{first['maemulSer']}")

URL = "https://www.courtauction.go.kr/pgj/pgj15B/selectAuctnCsSrchRslt.on"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.courtauction.go.kr",
    "Referer": "https://www.courtauction.go.kr/pgj/index.on?device=pc",
}

# srchInfo는 JSON string으로 (dataType=text)
payload = {
    "dma_srchGdsDtlSrch": {
        "csNo": first["srnSaNo"],
        "cortOfcCd": first["boCd"],
        "dspslGdsSeq": first["maemulSer"],
        "pgmId": "PGJ15BM01",
        "srchInfo": "",
    }
}

r = httpx.post(URL, json=payload, headers=HEADERS, timeout=30)
print("status:", r.status_code)
try:
    j = r.json()
except Exception:
    print(r.text[:500])
    raise

print("envelope status:", j.get("status"), "msg:", j.get("message"))
data = j.get("data") or {}
result = data.get("dma_result") or {}
print("\ndma_result keys:")
for k, v in result.items():
    if isinstance(v, list):
        print(f"  {k}: list[{len(v)}]")
    elif isinstance(v, dict):
        print(f"  {k}: dict({len(v)} keys)")
    elif v is None:
        print(f"  {k}: null")
    else:
        s = str(v)
        print(f"  {k}: {type(v).__name__} = {s[:80]}")

# 사건기본정보 살짝 미리보기
csb = result.get("csBaseInfo")
if isinstance(csb, dict):
    print("\n=== csBaseInfo (sample) ===")
    for k, v in list(csb.items())[:30]:
        s = str(v)
        if len(s) > 80:
            s = s[:80] + "…"
        print(f"  {k}: {s}")

out = Path("/Users/jaemoonyeah/workspace/auction/crawler/data/probe/detail_response_001.json")
out.write_text(json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n[+] saved → {out}")
