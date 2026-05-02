# courtauction.go.kr API 정찰 노트 (v2 — 정찰 완성본)

## 개요

- 도메인: `www.courtauction.go.kr`
- 프레임워크: **WebSquare 5** (인스웨이브 RIA — 정부/공공 사이트 표준)
- 메인: `https://www.courtauction.go.kr/pgj/index.on?device=pc`
- robots.txt: 없음 (404)

## 통신 규약 — 모든 API 동일

| 항목 | 값 |
|---|---|
| URL | `https://www.courtauction.go.kr/pgj/<모듈>/<액션>.on` |
| Method | POST (간혹 GET) |
| Request | `Content-Type: application/json;charset=UTF-8` + JSON body |
| Response | `application/json;charset=UTF-8` |
| 인증 | **없음** — 세션·쿠키·CSRF 토큰 모두 불필요. UA + Referer만 권장 |
| WebSquare 패턴 | dataMap 이름을 key로 nested → `{"dma_xxx": {...}, "dma_yyy": {...}}` |

표준 응답 envelope:

```json
{
  "status": 200,
  "message": "...",
  "timestamp": 1777692248788,
  "errors": null,
  "data": { ... },
  "token": null
}
```

에러 응답 (HTTP 400):

```json
{
  "timestamp": ...,
  "errors": {"errorMessage": "...", "errorCode": "", "referedUrl": "..."}
}
```

## 화면 ID 체계

- 디렉토리: `/pgj/ui/pgj100/`
- 패턴: `PGJ<영역><모듈>{M|F|P}<번호>.xml`
  - `M` = Main (실제 화면)
  - `F` = Frame (컨테이너; 진짜 로직은 자식 M에)
  - `P` = Popup
- 영역 매핑 (확정):

| 화면 | 정체 |
|---|---|
| `PGJ111M01/M02` | 메인 / 통계 차트 |
| `PGJ141M00/02` | 공지사항 |
| `PGJ151F00` | **물건상세검색** 컨테이너 |
| `PGJ151M01` | └─ 부동산 검색 (자식 frame) |
| `PGJ151M02` | └─ 동산 검색 (자식 frame) |
| `PGJ152F00` | 지도검색 |
| `PGJ153F00/M01` | 기일별검색 |
| `PGJ154M00~03` | 자동차·중기 검색 / detail |
| `PGJ157M00` | 매각예정물건 |
| `PGJ158M00/01` | 매각결과검색 |
| `PGJ159M00/01` | 경매사건검색 |
| `PGJ15BM01` | **부동산 사건/물건 상세** ⭐ |
| `PGJ15BP05~07` | 상세 팝업 (인쇄/사진 등) |
| `PGJ161~164` | 매각통계 (연도/법원/지역/용도별) |
| `PGJ171~177` | 도움말 (절차/용어/서식/안내/비용/관련법률) |
| `PGJ181~185` | 제공서비스/사이트맵 |
| `PGJ192~196` | 마이페이지 (관심물건/관심사건/자주쓰는검색 등) |

## 핵심 endpoint 목록 (모두 검증됨)

### 마스터 코드

| Endpoint | 요청 | 응답 키 | 용도 |
|---|---|---|---|
| `/pgj/pgj002/selectCortOfcLst.on` | `{"cortExecrOfcDvsCd":"00079B"}` | `cortOfcLst[]` | 법원 목록 (B prefix) |
| `/pgj/pgj002/selectCortOfcLst.on` | `{"cortExecrOfcDvsCd":"00079O"}` (추정) | `cortOfcLst[]` | 법원 목록 (O prefix) |
| `/pgj/pgj002/selectAdongSdLst.on` | `{"pbancMidYn":"Y","srchDvsCd":"O","pbancDvsCd":"FB"}` | `adongSdLst[]` | 시·도 |
| `/pgj/pgj002/selectAdongSggLst.on` | `{"adongSdCd":"11", ...}` | `adongSggLst[]` | 시·군·구 |
| `/pgj/pgj002/selectAdongEmdLst.on` | `{"adongSggCd":"11680", ...}` | `adongEmdLst[]` | 읍·면·동 |
| `/pgj/pgj002/selectRdnmAddr.on` | `{"adongSggCd":"...", "conValue1":"...", ...}` | `rdNmLst[]` | 도로명 주소 |
| `/pgj/pgj002/selectRnConsonantLst.on` | (없음/empty) | `rnConsonantLst[]` | 자음 인덱스 |
| `/pgj/pgj002/selectLclLst.on` | `{}` | `lclLst[]` | 용도 대분류 |
| `/pgj/pgj002/selectMclLst.on` | `{"lclDspslGdsLstUsgCd":"..."}` | `mclLst[]` | 용도 중분류 |
| `/pgj/pgj002/selectSclLst.on` | `{"mclDspslGdsLstUsgCd":"..."}` | `sclLst[]` | 용도 소분류 |
| `/pgj/pgj002/selectSpcCondLst.on` | (없음) | `spcCondLst[]` | 매각특수조건 |
| `/pgj/pgj002/selectMvprpDspslPlcTypLst.on` | (없음) | — | 동산매각장소유형 |
| `/pgj/pgj002/selectCarTmidClCdLst.on` | (없음) | — | 자동차 분류 |

> 마스터 endpoint는 `/pgj/cm/js/pgj.js`(0022.txt 캡처)에 모두 정의됨. 추가 발견 시 같은 패턴 가정.

### 검색 (✅ 검증)

**`POST /pgj/pgjsearch/searchControllerMain.on`**

페이로드(부동산 기준 — 모든 필드 string, 빈 값은 ""):

```json
{
  "dma_pageInfo": {
    "pageNo": "1", "pageSize": "100", "bfPageNo": "",
    "startRowNo": "1", "totalCnt": "0", "totalYn": "Y", "groupTotalCount": ""
  },
  "dma_srchGdsDtlSrchInfo": {
    "mvprpRletDvsCd": "00031R",       // 00031R=부동산, 00031M=동산
    "cortAuctnSrchCondCd": "0004601", // 검색조건 코드
    "pgmId": "PGJ151M01",             // 부동산:M01, 동산:M02
    "notifyLoc": "Y",
    "lafjOrderBy": "",
    "cortOfcCd": "B000210",           // 옵션 — 법원 필터
    // ... (47개 필드 모두 키는 존재해야 함; 빈 값 OK)
  }
}
```

**전체 47개 검색 키:**

```
rletDspslSpcCondCd, bidDvsCd, mvprpRletDvsCd, cortAuctnSrchCondCd,
rprsAdongSdCd, rprsAdongSggCd, rprsAdongEmdCd,           # 부동산 지번
rdnmSdCd, rdnmSggCd, rdnmNo,                              # 부동산 도로명
mvprpDspslPlcAdongSdCd/Sgg/Emd,                            # 동산 지번
rdDspslPlcAdongSdCd/Sgg/Emd,                               # 동산 도로명
cortOfcCd, jdbnCd, execrOfcDvsCd,                         # 법원
lclDspslGdsLstUsgCd, mclDspslGdsLstUsgCd, sclDspslGdsLstUsgCd,  # 용도
cortAuctnMbrsId,
aeeEvlAmtMin/Max,                                          # 감정가
rletLwsDspslPrcMin/Max, mvprpLwsDspslPrcMin/Max,           # 최저매각가
lwsDspslPrcRateMin/Max,                                    # 매각가율
flbdNcntMin/Max,                                           # 유찰횟수
objctArDtsMin/Max,                                         # 면적
mvprpArtclKndCd, mvprpArtclNm, mvprpAtchmPlcTypCd,         # 동산
notifyLoc, lafjOrderBy, pgmId,
csNo, cortStDvs, statNum, bidBgngYmd, bidEndYmd
```

**검증 결과**: 전국 부동산 공고중 매물 `totalCnt = 24,915건` (2026-05-02 기준).

**응답**: `data.dma_pageInfo + data.dlt_srchResult[] + data.ipcheck`

`dlt_srchResult` 한 row에 99컬럼 — 핵심:

```
docid           유니크 ID (예 B0002102023013000629211)
boCd, saNo      법원코드, 사건번호
srnSaNo         사건번호 표시 (예 "2023타경6292")
maemulSer, mokmulSer  매물순번, 목적물순번
gamevalAmt      감정가
minmaePrice     최저매각가
yuchalCnt       유찰횟수
maeGiil, maegyuljGiil  매각기일, 매각결정기일
maemulUtilCd / lclsUtilCd / mclsUtilCd / sclsUtilCd  용도
xCordi, yCordi, wgs84Xcordi, wgs84Ycordi             좌표
daepyoSidoCd~Dong/RdCd, daepyoLotno                  대표주소
buldList, areaList, jimokList                        건물/면적/지목
tel, jiwonNm, jpDeptNm                                법원 연락
```

### 사건/물건 상세 (✅ 검증)

**`POST /pgj/pgj15B/selectAuctnCsSrchRslt.on`**

라우팅 (PGJ151M01 `moveDtlPage` 함수, line 940):

| 조건 | 상세 화면 |
|---|---|
| `lclsUtilCd=30000 && mclsUtilCd in (30100, 31100)` | `PGJ154M03.xml` (자동차/중기) |
| 기타 | `PGJ15BM01.xml` (부동산 일반) |

페이로드:

```json
{
  "dma_srchGdsDtlSrch": {
    "csNo": "2023타경6292",       // = srnSaNo
    "cortOfcCd": "B000210",        // = boCd
    "dspslGdsSeq": "1",            // = maemulSer
    "pgmId": "PGJ15BM01",
    "srchInfo": ""
  }
}
```

응답 `data.dma_result` 키:

| 키 | 설명 |
|---|---|
| `csBaseInfo` (dict, 26 keys) | 사건번호/사건명/접수일/명령일/청구금액/법원/경매계/연락처 |
| `dstrtDemnInfo` (list[1]) | 배당요구종기일 |
| `dspslGdsDxdyInfo` (dict, 36 keys) | 매각물건정보 상세 |
| `picDvsIndvdCnt` (list) | 사진구분별 건수 |
| `csPicLst` (list) | 사진 리스트 (Base64 또는 URL) |
| `gdsDspslDxdyLst` (list) | 매각기일 전체 이력 (유찰포함) |
| `gdsDspslObjctLst` (list) | 매각목적물 |
| `rgltLandLstAll` (list) | 대지권토지 |
| `bldSdtrDtlLstAll` (list) | 건물표제부 상세 |
| `gdsNotSugtBldLsstAll` (list) | 제시외 건물 |
| `gdsRletStLtnoLstAll` (list) | 부동산 소재지번 |
| `aeeWevlMnpntLst` (list, 10) | **감정평가요항표** |

### 통계 / 인근

| Endpoint | 용도 |
|---|---|
| `/pgj/pgj15B/selectAuctnTongSrchRslt.on` | 인근매각통계 (사건단위) |
| `/pgj/pgjsearch/selectAroundDspslGds.on` | 주변 매각물건 |
| `/pgj/pgjsearch/selectAroundProgGds.on` | 주변 진행물건 |
| `/pgj/pgj15B/selectPicInf.on` | 물건 사진 페이징 조회 |
| `/pgj/pgj111/selectRletYrDspslStats.on` | 부동산 연도별 매각통계 |
| `/pgj/pgj161/selectRletYrDspslStats.on` | 연도별 매각통계 |
| `/pgj/pgj162/selectRletCortDspslStats.on` | 법원별 매각통계 |
| `/pgj/pgj163/selectRletYrDspslStatsByRdnm.on` | 지역별 매각통계 |
| `/pgj/pgj164/selectRletCortDspslStats.on` | 용도별 매각통계 |

### Generic blob (PDF/이미지 다운로드 추정)

`/pgj/pgjComm/000Blob.on` — 공지사항/서식/안내 등 공통 blob endpoint. 매각물건명세서 등도 같은 endpoint로 docId 기반 다운로드일 가능성. **추후 PGJ15BM01의 doc download 로직 분석 필요**.

## 코드 체계

| 코드 | 의미 | 알려진 값 |
|---|---|---|
| `mvprpRletDvsCd` | 부동산/동산 구분 | `00031R` 부동산, `00031M` 동산 |
| `cortAuctnSrchCondCd` | 검색조건 | `0004601`, `0004603`, `0004604` (의미 미해석) |
| `pgmId` | 호출 화면 ID | 검색 부동산: `PGJ151M01`, 동산: `PGJ151M02`, 상세: `PGJ15BM01` |
| `pbancDvsCd` | 공고구분 | `FB` (부동산 공고 추정) |
| `srchDvsCd` | 검색구분 | `O`, `B` |
| `pbancMidYn` | 공고중 여부 | `Y`/`N` |
| `notifyLoc` | 공고중 위치필터 | `Y` |
| `cortExecrOfcDvsCd` | 법원사무소구분 | `00079B` (B prefix), `00079O` (O prefix) |
| 법원코드 prefix | 분류 | `B000xxx` 부동산경매, `O000xxx` 다른 분류(추정) |
| 행정구역 시도 코드 | 표준 2자리 | 11=서울, 26=부산, 27=대구, 28=인천, 29=광주, 30=대전, 31=울산, 36=세종, 41=경기, 42=강원, 43=충북, 44=충남, 45=전북, 46=전남, 47=경북, 48=경남, 50=제주 |

## 안정성 / 운영 메모

- **로컬 Mac 가정용 IP** 사용 시 차단 사례 거의 없음 (참조 메모: 데이터센터 IP 대비 안전)
- 응답 schema는 `status==200` + 표준 envelope 일관됨 → 핵심 키 누락 시 즉시 변경 감지 가능
- W2X 정의 파일을 주기 fetch + diff 하면 **사이트 개편 자동 감지**
- 권장 rate limit: concurrent 5~8, 평균 200~500ms
- transient 5xx / network는 exp. backoff (0.5s → 30s, max 5회)
- 영구실패는 dead-letter jsonl로 분리

## 미해결 / 다음 발굴 항목

1. **매각물건명세서** (인수권리/임차인 — 권리분석 핵심) — PGJ15BM01의 sub-frame 또는 별도 popup일 가능성
2. **현황조사서** PDF 다운로드 endpoint
3. **감정평가서** 원본 PDF 다운로드 endpoint
4. **사진 원본 URL** — `selectPicInf.on` 응답에 base64인지 별도 URL인지 확인
5. `cortAuctnSrchCondCd` 값별 의미 (0004601 / 0004603 / 0004604)
6. 동산(`O` prefix) 법원 목록의 실제 차이
7. `00079O` 등 다른 법원분류구분 검증
