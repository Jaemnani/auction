"""searchControllerMain.on 호출 검증 — 부동산 검색 1페이지."""

import json

import httpx

URL = "https://www.courtauction.go.kr/pgj/pgjsearch/searchControllerMain.on"

ALL_SEARCH_KEYS = [
    "rletDspslSpcCondCd", "bidDvsCd", "mvprpRletDvsCd", "cortAuctnSrchCondCd",
    "rprsAdongSdCd", "rprsAdongSggCd", "rprsAdongEmdCd",
    "rdnmSdCd", "rdnmSggCd", "rdnmNo",
    "mvprpDspslPlcAdongSdCd", "mvprpDspslPlcAdongSggCd", "mvprpDspslPlcAdongEmdCd",
    "rdDspslPlcAdongSdCd", "rdDspslPlcAdongSggCd", "rdDspslPlcAdongEmdCd",
    "cortOfcCd", "jdbnCd", "execrOfcDvsCd",
    "lclDspslGdsLstUsgCd", "mclDspslGdsLstUsgCd", "sclDspslGdsLstUsgCd",
    "cortAuctnMbrsId",
    "aeeEvlAmtMin", "aeeEvlAmtMax",
    "rletLwsDspslPrcMin", "rletLwsDspslPrcMax",
    "mvprpLwsDspslPrcMin", "mvprpLwsDspslPrcMax",
    "lwsDspslPrcRateMin", "lwsDspslPrcRateMax",
    "flbdNcntMin", "flbdNcntMax",
    "objctArDtsMin", "objctArDtsMax",
    "mvprpArtclKndCd", "mvprpArtclNm", "mvprpAtchmPlcTypCd",
    "notifyLoc", "lafjOrderBy", "pgmId", "csNo",
    "cortStDvs", "statNum", "bidBgngYmd", "bidEndYmd",
]

base = {k: "" for k in ALL_SEARCH_KEYS}
base.update({
    "mvprpRletDvsCd": "00031R",       # 부동산
    "cortAuctnSrchCondCd": "0004601",  # 가장 흔한 값
    "pgmId": "PGJ151M01",              # 부동산 검색 화면
    "notifyLoc": "Y",                  # 공고중
    "lafjOrderBy": "",
})

payload = {
    "dma_pageInfo": {
        "pageNo": "1",
        "pageSize": "10",
        "bfPageNo": "",
        "startRowNo": "1",
        "totalCnt": "0",
        "totalYn": "Y",
        "groupTotalCount": "",
    },
    "dma_srchGdsDtlSrchInfo": base,
}

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.courtauction.go.kr",
    "Referer": "https://www.courtauction.go.kr/pgj/index.on?device=pc",
}

r = httpx.post(URL, json=payload, headers=headers, timeout=30)
print("status:", r.status_code)
print("ctype:", r.headers.get("content-type"))
print("len:", len(r.content))

try:
    j = r.json()
except Exception:
    print("raw body[:1000]:", r.text[:1000])
    raise

print("envelope keys:", list(j.keys()))
print("status:", j.get("status"))
print("message:", j.get("message"))
data = j.get("data") or {}
print("data keys:", list(data.keys()) if isinstance(data, dict) else "(not dict)")

# 결과 list 추정 키들 출력
if isinstance(data, dict):
    for k, v in data.items():
        if isinstance(v, list):
            print(f"\n=== data.{k} (list, len={len(v)}) ===")
            if v:
                print("  sample[0] keys:", list(v[0].keys()) if isinstance(v[0], dict) else type(v[0]).__name__)
                print("  sample[0]:", json.dumps(v[0], ensure_ascii=False)[:600])
        elif isinstance(v, dict):
            print(f"\n=== data.{k} (dict) ===")
            print("  keys:", list(v.keys()))
            print("  sample:", json.dumps(v, ensure_ascii=False)[:400])

# 전체 응답을 파일로 저장
from pathlib import Path
out = Path(__file__).resolve().parent.parent / "data" / "probe"
out.mkdir(parents=True, exist_ok=True)
(out / "search_response_001.json").write_text(
    json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"\n[+] saved → {out / 'search_response_001.json'}")
