"""
courtauction.go.kr API 클라이언트.

설계 메모:
- 모든 endpoint가 동일한 envelope 패턴 (`{status, message, data, ...}`)
- 세션 쿠키 기반 WAF 차단 있음 → __aenter__에서 index 페이지 GET으로 세션 워밍업
  (쿠키 없는 요청은 "보안정책" 차단 유발). rate limit + 지터로 봇 패턴 회피.
- 차단 감지 시 세션 재워밍 후 지수 backoff 재시도.
- WebSquare submission 패턴 그대로 — `{"dma_xxx": {...}}` nested
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
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


class IpBlocked(CourtAuctionError):
    """courtauction IP 차단 — 지수 backoff 재시도 다 소진. 세션 종료하고
    다음 실행(cron)에 재개하는 것이 정답 (보통 차단은 수십분~수시간 지속)."""


# 차단/일시제한 메시지 키워드 — 두 형태 모두 backoff 대상으로 통일.
#  · 200 envelope: message="...보안정책..." 또는 data.ipcheck=False
#  · 400: errorMessage="...잠시 후 다시 이용...사용에 불편..."
_BLOCK_KEYWORDS = ("보안정책", "차단", "잠시 후 다시", "사용에 불편", "일시적으로")


def _block_message(body: Any) -> str | None:
    """응답 body가 IP/세션 차단·일시제한이면 메시지 문자열, 아니면 None."""
    if not isinstance(body, dict):
        return None
    data = body.get("data")
    if isinstance(data, dict) and data.get("ipcheck") is False:
        return "ipcheck=False"
    parts: list[str] = []
    for k in ("message", "errorMessage"):
        v = body.get(k)
        if isinstance(v, str):
            parts.append(v)
    err = body.get("errors")
    if isinstance(err, dict):
        v = err.get("errorMessage") or err.get("message")
        if isinstance(v, str):
            parts.append(v)
    elif isinstance(err, str):
        parts.append(err)
    text = " ".join(parts)
    if any(k in text for k in _BLOCK_KEYWORDS):
        return text[:120]
    return None


# ---------- Config ----------

@dataclass
class ClientConfig:
    base_url: str = BASE_URL
    concurrency: int = 2                # 병렬 너무 많으면 IP 차단
    min_interval_ms: int = 1500         # 요청 최소 간격 (200ms도 차단 유발)
    jitter_ms: int = 1000               # 간격에 더할 랜덤 지터 0~jitter (봇 패턴 회피)
    warmup: bool = True                 # 세션 시작 시 index GET으로 쿠키 시드
    proxy: str | None = None            # 출구 IP 우회 — http(s)://... (socks5는 socksio 필요)
    # 실측(2026-06-27~07-02, 6회): 요청 간격은 설정대로(~1s) 정확히 지켜지는데도
    # 152~481 요청(3배 편차)에서 차단 → 고정 카운트가 아니라 슬라이딩 윈도우형
    # rate-limit 추정. 그래서 (a) 기본 간격을 늦추고 (b) 요청 다발을 끊어주는
    # 주기적 쿨다운 (c) 차단 감지 시 이후 요청을 더 늦추는 적응형 감속을 추가.
    checkpoint_every: int = 80          # 이 요청 수마다 추가 쿨다운 (다발 끊기)
    checkpoint_pause_s: float = 20.0    # 체크포인트 쿨다운 길이
    slowdown_on_block: float = 1.6      # 차단 감지 시 이후 간격에 곱할 배율 (누적, cap 있음)
    slowdown_cap: float = 4.0           # 감속 배율 상한
    timeout_s: float = 30.0
    max_retries: int = 5
    backoff_base_s: float = 0.5
    backoff_max_s: float = 60.0
    # IP 차단은 network retry 와 분리된 카운터 + 지수 backoff.
    # 90 → 180 → 360 → 720 (cap 900) = 약 22분 시도 후 IpBlocked 로 세션 종료.
    ip_block_pause_s: float = 90.0       # 첫 대기 (지수 base)
    ip_block_pause_max_s: float = 900.0  # 대기 상한 (15분)
    ip_block_max_retries: int = 4        # IP block 전용 재시도 횟수
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
        self._request_count = 0     # 체크포인트 쿨다운 판단용
        self._slowdown = 1.0        # 차단 감지 시 누적 증가 — 세션 남은 기간 더 느리게

        if self.cfg.save_dir:
            self.cfg.save_dir.mkdir(parents=True, exist_ok=True)
        if self.cfg.dead_letter_path:
            self.cfg.dead_letter_path.parent.mkdir(parents=True, exist_ok=True)

    async def __aenter__(self) -> "CourtAuctionClient":
        headers = dict(DEFAULT_HEADERS)
        if self.cfg.extra_headers:
            headers.update(self.cfg.extra_headers)
        if self.cfg.proxy:
            # 자격증명 노출 방지차 host만 로그.
            try:
                host = httpx.URL(self.cfg.proxy).host
            except Exception:
                host = "?"
            logger.info("courtauction 요청을 프록시 경유: %s", host)
        self._client = httpx.AsyncClient(
            base_url=self.cfg.base_url,
            headers=headers,
            timeout=self.cfg.timeout_s,
            http2=False,
            proxy=self.cfg.proxy,  # None이면 직결
        )
        if self.cfg.warmup:
            await self._warmup()
        return self

    async def _warmup(self) -> None:
        """index 페이지 GET으로 세션 쿠키(JSESSIONID/WMONID 등) 시드.
        courtauction WAF가 쿠키 없는 API 직접호출을 '보안정책' 차단할 수 있음 →
        브라우저처럼 메인 페이지를 먼저 방문해 쿠키를 받아둔다. 실패해도 진행."""
        if self._client is None:
            return
        try:
            r = await self._client.get(
                "/pgj/index.on?device=pc",
                headers={"Accept": "text/html,application/xhtml+xml,*/*"},
            )
            logger.info("session warmup: GET index → %d, cookies=%d",
                        r.status_code, len(self._client.cookies))
        except Exception as e:  # noqa: BLE001
            logger.warning("session warmup 실패(무시): %s", e)

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ---------- internals ----------

    async def _throttle(self) -> None:
        # 락 안에서 간격+체크포인트를 모두 처리 — concurrency≥2에서도 전역으로 적용
        # (락 밖에서 sleep하면 다른 worker가 계속 쏴 '다발 끊기'가 안 됨).
        async with self._throttle_lock:
            self._request_count += 1
            # 체크포인트 쿨다운 — 요청 다발을 끊어 슬라이딩 윈도우형 rate-limit 회피.
            if (self.cfg.checkpoint_every > 0
                    and self._request_count % self.cfg.checkpoint_every == 0):
                logger.info("checkpoint cooldown: %d requests → pausing %.0fs",
                            self._request_count, self.cfg.checkpoint_pause_s)
                await asyncio.sleep(self.cfg.checkpoint_pause_s)
                self._last_request_at = time.monotonic()
            if self.cfg.min_interval_ms > 0:
                # 고정 간격은 봇 패턴 → 매 요청 최소간격 + 0~jitter 랜덤을 목표로.
                # _slowdown: 차단 감지 시 누적 증가하는 배율 (세션 남은 기간 더 느리게).
                target_ms = (
                    (self.cfg.min_interval_ms + random.uniform(0, self.cfg.jitter_ms))
                    * self._slowdown
                )
                elapsed_ms = (time.monotonic() - self._last_request_at) * 1000
                wait_ms = target_ms - elapsed_ms
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
        attempt = 0              # network/5xx 재시도 카운터
        ip_block_attempt = 0     # IP 차단 전용 카운터 (위와 분리)
        while attempt < self.cfg.max_retries:
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
                    attempt += 1
                    continue

            if 500 <= r.status_code < 600:
                last_err = TransientError(f"HTTP {r.status_code} on {path}")
                delay = min(self.cfg.backoff_base_s * (2 ** attempt),
                            self.cfg.backoff_max_s)
                logger.warning("HTTP %d on %s (attempt %d), retry in %.1fs",
                               r.status_code, path, attempt + 1, delay)
                await asyncio.sleep(delay)
                attempt += 1
                continue

            try:
                body = r.json()
            except Exception as e:
                self._dead_letter(path, payload, status=r.status_code,
                                  body=r.text[:500])
                raise PermanentError(f"non-JSON response on {path}: {e}") from e

            # IP/세션 차단·일시제한 감지 (400 '잠시 후 다시' + 200 '보안정책' + ipcheck=False
            # 통합). 일반 retry 와 분리된 카운터 + 지수 backoff. 다 소진하면 IpBlocked 로
            # 세션 종료 (수십분 차단은 다음 실행에서 재개하는 게 정답).
            block_msg = _block_message(body)
            if block_msg is not None:
                ip_block_attempt += 1
                prev_slowdown = self._slowdown
                self._slowdown = min(
                    self._slowdown * self.cfg.slowdown_on_block, self.cfg.slowdown_cap
                )
                if self._slowdown != prev_slowdown:
                    logger.info("적응형 감속: 이후 요청 간격 x%.2f (누적)", self._slowdown)
                if ip_block_attempt > self.cfg.ip_block_max_retries:
                    raise IpBlocked(
                        f"IP blocked on {path} — {self.cfg.ip_block_max_retries}회 "
                        f"지수 backoff 후에도 미해소. 차단이 길어 세션 종료 "
                        f"(다음 실행에서 재개). msg={block_msg[:80]}"
                    )
                delay = min(
                    self.cfg.ip_block_pause_s * (2 ** (ip_block_attempt - 1)),
                    self.cfg.ip_block_pause_max_s,
                )
                logger.warning(
                    "IP/세션 차단 감지 %s (HTTP %d) — pausing %.0fs (ip-block %d/%d): msg=%s",
                    path, r.status_code, delay, ip_block_attempt,
                    self.cfg.ip_block_max_retries, block_msg[:80],
                )
                await asyncio.sleep(delay)
                # 대기 후 세션 재워밍(새 쿠키) — 세션 단위 차단이면 갱신으로 풀릴 수 있음.
                if self.cfg.warmup:
                    await self._warmup()
                last_err = IpBlocked(f"IP block on {path}")
                continue  # attempt(network 카운터) 안 깎음

            if r.status_code >= 400:
                err = body.get("errors") if isinstance(body, dict) else None
                self._dead_letter(path, payload, status=r.status_code, body=body)
                raise PermanentError(f"HTTP {r.status_code} on {path}: {err}")

            if not isinstance(body, dict) or body.get("status") != 200:
                self._dead_letter(path, payload, status=r.status_code, body=body,
                                  note="envelope status != 200")
                raise StructureChanged(f"envelope status != 200 on {path}")

            data = body.get("data")

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
        # 실제 사이트 JS(getUsgMclLst)는 {"code": lclCd}로 요청 — 과거 파라미터명
        # (lclDspslGdsLstUsgCd)은 200 + 빈 목록을 반환해 usage_codes level2가
        # 영영 안 채워졌음 (recon 캡처 bodies/0022.txt로 확인).
        body = await self.post(
            "/pgj/pgj002/selectMclLst.on",
            {"code": lcl_code},
            expect_keys=["usgMclLst"],
        )
        return body["data"]["usgMclLst"]

    async def list_usage_scl(self, mcl_code: str) -> list[dict]:
        body = await self.post(
            "/pgj/pgj002/selectSclLst.on",
            {"code": mcl_code},
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

    # 매각결과검색 (PGJ158M02) — 종결된 사건들의 결과 (낙찰가/유찰 등)
    async def search_results(
        self,
        *,
        page_no: int = 1,
        page_size: int = 50,
        sd_code: str | None = None,
        sgg_code: str | None = None,
        usage_lcl: str | None = None,
        bid_from: str | None = None,  # YYYYMMDD
        bid_to: str | None = None,
        filters: dict[str, str] | None = None,
    ) -> dict:
        """매각결과 검색. search와 같은 row 구조 + maeAmt/inqCnt 등 결과 필드 포함."""
        if page_size > self.SEARCH_PAGE_SIZE_MAX:
            raise ValueError(f"page_size {page_size} > {self.SEARCH_PAGE_SIZE_MAX}")
        info = self._empty_search_info()
        info.update({
            "mvprpRletDvsCd": "00031R",
            "cortAuctnSrchCondCd": "0004601",
            "pgmId": "PGJ158M02",
        })
        if sd_code:    info["rprsAdongSdCd"] = sd_code
        if sgg_code:   info["rprsAdongSggCd"] = sgg_code
        if usage_lcl:  info["lclDspslGdsLstUsgCd"] = usage_lcl
        if bid_from:   info["bidBgngYmd"] = bid_from
        if bid_to:     info["bidEndYmd"] = bid_to
        if filters:
            for k, v in filters.items():
                if k not in self.SEARCH_KEYS:
                    raise ValueError(f"unknown filter: {k}")
                info[k] = v
        payload = {
            "dma_pageInfo": {
                "pageNo": str(page_no), "pageSize": str(page_size),
                "bfPageNo": "", "startRowNo": str((page_no - 1) * page_size + 1),
                "totalCnt": "0",
                "totalYn": "Y" if page_no == 1 else "N",
                "groupTotalCount": "",
            },
            "dma_srchGdsDtlSrchInfo": info,
        }
        body = await self.post(
            "/pgj/pgjsearch/selectDspslSchdRsltSrch.on",
            payload, expect_keys=["dlt_srchResult", "dma_pageInfo"],
        )
        return body["data"]

    async def search_results_iter(
        self, *, page_size: int = 50, max_pages: int | None = None, **kwargs,
    ):
        """모든 페이지 순회."""
        page_no = 1
        cached_total: int | None = None
        while True:
            page = await self.search_results(
                page_no=page_no, page_size=page_size, **kwargs,
            )
            yield page
            page_info = page.get("dma_pageInfo") or {}
            try: t = int(page_info.get("totalCnt") or 0)
            except (TypeError, ValueError): t = 0
            if cached_total is None: cached_total = t
            if cached_total <= 0: return
            seen = page_no * page_size
            if seen >= cached_total: return
            page_no += 1
            if max_pages and page_no > max_pages: return

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
