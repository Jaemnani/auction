"""
courtauction.go.kr API 클라이언트.

설계 메모:
- 모든 endpoint가 동일한 envelope 패턴 (`{status, message, data, ...}`)
- 인증·세션 불필요 → httpx async 만으로 충분
- 봇 차단·캡차 없음 — 매너 차원의 자체 rate limit / retry 만 적용
- WebSquare submission 패턴 그대로 — `{"dma_xxx": {...}}` nested
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.courtauction.go.kr"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "application/json",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/pgj/index.on?device=pc",
}


# ---------- Errors ----------

class CourtAuctionError(Exception):
    """모든 클라이언트 오류의 베이스."""


class TransientError(CourtAuctionError):
    """재시도 대상 — 네트워크/일시적 5xx."""


class PermanentError(CourtAuctionError):
    """재시도 무의미 — 4xx, business 거부, 잘못된 파라미터 등."""


class StructureChanged(CourtAuctionError):
    """응답 스키마가 기대와 다름 — 사이트 개편 가능성."""


# ---------- Config ----------

@dataclass
class ClientConfig:
    base_url: str = BASE_URL
    concurrency: int = 2                # 병렬 너무 많으면 IP 차단
    min_interval_ms: int = 500          # 요청 간격 (200ms도 차단 유발)
    timeout_s: float = 30.0
    max_retries: int = 5
    backoff_base_s: float = 0.5
    backoff_max_s: float = 60.0
    ip_block_pause_s: float = 90.0      # IP 차단 감지 시 추가 대기
    save_dir: Path | None = None        # raw response 저장
    dead_letter_path: Path | None = None  # 영구 실패 jsonl
    extra_headers: dict[str, str] | None = None


# ---------- Client ----------

class CourtAuctionClient:
    """
    사용 예:

        async with CourtAuctionClient(ClientConfig(save_dir=Path("data/raw"))) as c:
            sido = await c.list_sido()
            page = await c.search_real_estate(court_code="B000210", page_size=100)
            detail = await c.get_case_detail("B000210", "2023타경6292", "1")
    """

    def __init__(self, config: ClientConfig | None = None) -> None:
        self.cfg = config or ClientConfig()
        self._sem = asyncio.Semaphore(self.cfg.concurrency)
        self._throttle_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._client: httpx.AsyncClient | None = None

        if self.cfg.save_dir:
            self.cfg.save_dir.mkdir(parents=True, exist_ok=True)
        if self.cfg.dead_letter_path:
            self.cfg.dead_letter_path.parent.mkdir(parents=True, exist_ok=True)

    async def __aenter__(self) -> "CourtAuctionClient":
        headers = dict(DEFAULT_HEADERS)
        if self.cfg.extra_headers:
            headers.update(self.cfg.extra_headers)
        self._client = httpx.AsyncClient(
            base_url=self.cfg.base_url,
            headers=headers,
            timeout=self.cfg.timeout_s,
            http2=False,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ---------- internals ----------

    async def _throttle(self) -> None:
        if self.cfg.min_interval_ms <= 0:
            return
        async with self._throttle_lock:
            elapsed_ms = (time.monotonic() - self._last_request_at) * 1000
            wait_ms = self.cfg.min_interval_ms - elapsed_ms
            if wait_ms > 0:
                await asyncio.sleep(wait_ms / 1000)
            self._last_request_at = time.monotonic()

    def _save_raw(self, path: str, payload: dict, body: Any) -> None:
        if not self.cfg.save_dir:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        slug = path.strip("/").replace("/", "_")
        out = self.cfg.save_dir / f"{stamp}_{slug}.json"
        out.write_text(
            json.dumps({"path": path, "payload": payload, "body": body},
                       ensure_ascii=False),
            encoding="utf-8",
        )

    def _dead_letter(self, path: str, payload: dict, *, status: int | None = None,
                     body: Any = None, note: str | None = None) -> None:
        if not self.cfg.dead_letter_path:
            return
        record = {
            "ts": datetime.now().isoformat(),
            "path": path, "payload": payload,
            "status": status, "body": body, "note": note,
        }
        with self.cfg.dead_letter_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    async def post(
        self,
        path: str,
        payload: dict,
        *,
        expect_keys: list[str] | None = None,
    ) -> dict:
        """
        envelope을 unwrap한 dict 전체(`{status, message, data, ...}`)를 반환.
        - 5xx/네트워크: exp. backoff + retry
        - 4xx: 즉시 PermanentError + dead-letter
        - envelope.status != 200 또는 expect_keys 누락: StructureChanged + dead-letter
        """
        if self._client is None:
            raise RuntimeError("CourtAuctionClient must be used as async context manager")

        last_err: Exception | None = None
        for attempt in range(self.cfg.max_retries):
            async with self._sem:
                try:
                    await self._throttle()
                    r = await self._client.post(path, json=payload)
                except (httpx.TimeoutException, httpx.NetworkError,
                        httpx.RemoteProtocolError) as e:
                    last_err = e
                    delay = min(self.cfg.backoff_base_s * (2 ** attempt),
                                self.cfg.backoff_max_s)
                    logger.warning("network error %s on %s (attempt %d), retry in %.1fs",
                                   type(e).__name__, path, attempt + 1, delay)
                    await asyncio.sleep(delay)
                    continue

            if 500 <= r.status_code < 600:
                last_err = TransientError(f"HTTP {r.status_code} on {path}")
                delay = min(self.cfg.backoff_base_s * (2 ** attempt),
                            self.cfg.backoff_max_s)
                logger.warning("HTTP %d on %s (attempt %d), retry in %.1fs",
                               r.status_code, path, attempt + 1, delay)
                await asyncio.sleep(delay)
                continue

            try:
                body = r.json()
            except Exception as e:
                self._dead_letter(path, payload, status=r.status_code,
                                  body=r.text[:500])
                raise PermanentError(f"non-JSON response on {path}: {e}") from e

            if r.status_code >= 400:
                err = body.get("errors") if isinstance(body, dict) else None
                self._dead_letter(path, payload, status=r.status_code, body=body)
                raise PermanentError(f"HTTP {r.status_code} on {path}: {err}")

            if not isinstance(body, dict) or body.get("status") != 200:
                self._dead_letter(path, payload, status=r.status_code, body=body,
                                  note="envelope status != 200")
                raise StructureChanged(f"envelope status != 200 on {path}")

            data = body.get("data")

            # IP 차단 감지: 응답 message에 "보안정책" 포함 또는 data.ipcheck == False
            msg = body.get("message") or ""
            ipchecked_ok = (
                not isinstance(data, dict) or data.get("ipcheck") is not False
            )
            if "보안정책" in msg or "차단" in msg or not ipchecked_ok:
                logger.warning("IP block detected on %s — pausing %.1fs (attempt %d/%d): msg=%s",
                               path, self.cfg.ip_block_pause_s,
                               attempt + 1, self.cfg.max_retries, msg[:80])
                await asyncio.sleep(self.cfg.ip_block_pause_s)
                last_err = TransientError(f"IP block on {path}")
                continue

            if expect_keys and isinstance(data, dict):
                missing = [k for k in expect_keys if k not in data]
                if missing:
                    self._dead_letter(path, payload, status=r.status_code, body=body,
                                      note=f"missing keys: {missing}")
                    raise StructureChanged(
                        f"{path} missing expected data keys: {missing}")

            self._save_raw(path, payload, body)
            return body

        raise TransientError(f"all {self.cfg.max_retries} retries exhausted on {path}") \
            from last_err

    # ---------- 마스터 코드 ----------

    async def list_courts(self, prefix: str = "00079B") -> list[dict]:
        """법원 목록. prefix=00079B (부동산 prefix B)."""
        body = await self.post(
            "/pgj/pgj002/selectCortOfcLst.on",
            {"cortExecrOfcDvsCd": prefix},
            expect_keys=["cortOfcLst"],
        )
        return body["data"]["cortOfcLst"]

    async def list_sido(self, *, srch_dvs: str = "O", pbanc_dvs: str = "FB",
                        pbanc_mid: str = "Y") -> list[dict]:
        body = await self.post(
            "/pgj/pgj002/selectAdongSdLst.on",
            {"pbancMidYn": pbanc_mid, "srchDvsCd": srch_dvs, "pbancDvsCd": pbanc_dvs},
            expect_keys=["adongSdLst"],
        )
        return body["data"]["adongSdLst"]

    async def list_sigungu(self, sd_code: str, *, srch_dvs: str = "O",
                           pbanc_dvs: str = "FB", pbanc_mid: str = "Y") -> list[dict]:
        body = await self.post(
            "/pgj/pgj002/selectAdongSggLst.on",
            {"adongSdCd": sd_code, "pbancMidYn": pbanc_mid,
             "srchDvsCd": srch_dvs, "pbancDvsCd": pbanc_dvs},
            expect_keys=["adongSggLst"],
        )
        return body["data"]["adongSggLst"]

    async def list_emd(self, sgg_code: str, *, srch_dvs: str = "O",
                       pbanc_dvs: str = "FB", pbanc_mid: str = "Y") -> list[dict]:
        body = await self.post(
            "/pgj/pgj002/selectAdongEmdLst.on",
            {"adongSggCd": sgg_code, "pbancMidYn": pbanc_mid,
             "srchDvsCd": srch_dvs, "pbancDvsCd": pbanc_dvs},
            expect_keys=["adongEmdLst"],
        )
        return body["data"]["adongEmdLst"]

    async def list_usage_lcl(self) -> list[dict]:
        body = await self.post(
            "/pgj/pgj002/selectLclLst.on", {},
            expect_keys=["usgLclLst"],
        )
        return body["data"]["usgLclLst"]

    async def list_usage_mcl(self, lcl_code: str) -> list[dict]:
        body = await self.post(
            "/pgj/pgj002/selectMclLst.on",
            {"lclDspslGdsLstUsgCd": lcl_code},
            expect_keys=["usgMclLst"],
        )
        return body["data"]["usgMclLst"]

    async def list_usage_scl(self, mcl_code: str) -> list[dict]:
        body = await self.post(
            "/pgj/pgj002/selectSclLst.on",
            {"mclDspslGdsLstUsgCd": mcl_code},
            expect_keys=["usgSclLst"],
        )
        return body["data"]["usgSclLst"]

    # ---------- 검색 ----------

    SEARCH_KEYS: tuple[str, ...] = (
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
    )

    def _empty_search_info(self) -> dict[str, str]:
        return {k: "" for k in self.SEARCH_KEYS}

    SEARCH_PAGE_SIZE_MAX = 50  # 사이트 상한 (60+ → HTTP 400)

    async def search(
        self,
        *,
        kind: str = "real_estate",          # "real_estate" | "movables"
        page_no: int = 1,
        page_size: int = 50,
        cort_ofc_cd: str | None = None,
        srch_cond: str = "0004601",
        notify_loc: str = "Y",
        order_by: str = "",
        filters: dict[str, str] | None = None,
    ) -> dict:
        """
        검색 결과를 그대로 반환: {"dma_pageInfo": {...}, "dlt_srchResult": [...], ...}.
        filters로 47개 검색 키 중 임의 필드 override 가능.
        """
        if page_size > self.SEARCH_PAGE_SIZE_MAX:
            raise ValueError(
                f"page_size {page_size} > server max {self.SEARCH_PAGE_SIZE_MAX}"
            )
        if kind == "real_estate":
            mvprp_rlet = "00031R"
            pgm_id = "PGJ151M01"
        elif kind == "movables":
            mvprp_rlet = "00031M"
            pgm_id = "PGJ151M02"
        else:
            raise ValueError(f"unknown kind: {kind}")

        info = self._empty_search_info()
        info["mvprpRletDvsCd"] = mvprp_rlet
        info["cortAuctnSrchCondCd"] = srch_cond
        info["pgmId"] = pgm_id
        info["notifyLoc"] = notify_loc
        info["lafjOrderBy"] = order_by
        if cort_ofc_cd:
            info["cortOfcCd"] = cort_ofc_cd
        if filters:
            for k, v in filters.items():
                if k not in self.SEARCH_KEYS:
                    raise ValueError(f"unknown search filter key: {k}")
                info[k] = v

        payload = {
            "dma_pageInfo": {
                "pageNo": str(page_no),
                "pageSize": str(page_size),
                "bfPageNo": "",
                "startRowNo": str((page_no - 1) * page_size + 1),
                "totalCnt": "0",
                "totalYn": "Y" if page_no == 1 else "N",
                "groupTotalCount": "",
            },
            "dma_srchGdsDtlSrchInfo": info,
        }
        body = await self.post(
            "/pgj/pgjsearch/searchControllerMain.on",
            payload,
            expect_keys=["dlt_srchResult", "dma_pageInfo"],
        )
        return body["data"]

    async def search_iter(
        self,
        *,
        kind: str = "real_estate",
        page_size: int = 50,
        cort_ofc_cd: str | None = None,
        max_pages: int | None = None,
        **kwargs,
    ):
        """
        모든 페이지 순회 — 페이지 단위 dict yield.
        rate limit은 client cfg가 알아서 적용.
        """
        page_no = 1
        cached_total: int | None = None  # 첫 페이지의 totalCnt를 정답으로 캐시
        while True:
            page = await self.search(
                kind=kind, page_no=page_no, page_size=page_size,
                cort_ofc_cd=cort_ofc_cd, **kwargs,
            )
            yield page

            page_info = page.get("dma_pageInfo") or {}
            try:
                t = int(page_info.get("totalCnt") or 0)
            except (TypeError, ValueError):
                t = 0
            # 사이트 동작: page 1 (totalYn=Y)만 진짜 totalCnt를 주고, 이후엔 0으로 옴.
            if cached_total is None:
                cached_total = t
            if cached_total <= 0:
                return                # 진짜 0건
            seen = page_no * page_size
            if seen >= cached_total:
                return
            page_no += 1
            if max_pages and page_no > max_pages:
                return

    # ---------- 상세 ----------

    async def get_case_detail(
        self,
        cort_ofc_cd: str,
        case_no: str,         # srnSaNo (예: "2023타경6292")
        dspsl_gds_seq: str | int,
        *,
        pgm_id: str = "PGJ15BM01",
    ) -> dict:
        """사건/물건 상세 — data.dma_result만 반환."""
        payload = {
            "dma_srchGdsDtlSrch": {
                "csNo": case_no,
                "cortOfcCd": cort_ofc_cd,
                "dspslGdsSeq": str(dspsl_gds_seq),
                "pgmId": pgm_id,
                "srchInfo": "",
            }
        }
        body = await self.post(
            "/pgj/pgj15B/selectAuctnCsSrchRslt.on",
            payload,
            expect_keys=["dma_result"],
        )
        return body["data"]["dma_result"]
