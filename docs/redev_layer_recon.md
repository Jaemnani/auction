# 정비사업(재개발·재건축) 레이어 — 데이터 소스 정찰 기록

2026-08-20. 목표: 지도(/map)에 정비구역 폴리곤 + 사업 단계 필터 표시.
재현 스크립트: `crawler/scripts/probe_redev.py`, 빌더: `crawler/scripts/redev_layer.py`.

## 결론 (Go/No-go)

**Go — 서울(폴리곤+점) + 부산·경기(대표 위치 점).** 전국 통합 소스는 없고,
지역별 소스를 어댑터로 붙인다. 표시 규칙: **폴리곤이 있으면 구역 경계, 없으면
주소 지오코딩 대표 위치 점** (feature 에 `loc_precision` 으로 정밀도 명시 —
`parcel`=필지, `dong`=동 단위 근사. 오지오코딩 방지로 시도 경계 밖 점은 build
가 폐기). 웹은 `web/public/redev/index.json` 의 지역 목록 주도라 지역 추가 =
데이터만 추가.

## 서울 (구현 완료)

### 단계 현황 — 정비몽땅 (cleanup.seoul.go.kr)
- 공식 오픈API 없음. 열린데이터광장 OA-2253("서울시 재개발 재건축 정비사업 현황")은
  **종료된 서비스** (페이지가 정비몽땅으로 안내).
- 사업장검색 `GET /cleanup/bsnssttus/lscrMainIndx.do?cpage=1&pageSize=3000`
  → 전체 목록이 한 페이지 HTML 로 옴 (실측 1,152행).
  컬럼: 자치구/사업구분/사업장명/대표지번/**진행단계**. 376행에 지도ID
  (`mapOpenPopup('<WTNNC_SN>')`, 예 `11000AGZ201211160062`).
- 진행단계 원값 25종 실측 → `crawler/src/redevelopment/phases.py` 의
  `SEOUL_STAGE_MAP` 에 전수 매핑. 사업구분 8종(재건축/재개발(주택·도시정비형)/
  가로주택정비/소규모재건축·재개발/지역주택/리모델링).
- 엑셀 다운로드(`POST /cleanup/bsnssttus/lsubBsnsSttusExcel.do`)도 가능하나
  구형 .xls(CDFV2) 라 의존성(xlrd)이 필요해 HTML 파싱 채택.

### 폴리곤 — 서울 도시공간포털 UPIS (urban.seoul.go.kr)
- 정비몽땅 지도 팝업이 `urban.seoul.go.kr/view/map/mapPopup.html?recordCode=<ID>`
  로 열리고, 내부적으로 ArcGIS 레이어를 `WTNNC_SN='<ID>'` 로 조회 —
  **지도ID = UPIS WTNNC_SN 동일 체계** → 이름 매칭 없이 ID 조인.
- ArcGIS 서버는 내부IP(98.33.2.225:6080)지만 공식 프록시로 접근:
  `https://urban.seoul.go.kr/proxy/proxy.jsp?http://98.33.2.225:6080/arcgis/rest/services/UPIS/20200526_WFS/MapServer`
  - layer **64 = UPIS_C_UQ181**(정비구역 현황, 3,305건),
    **163 = UPIS_H_UQ181**(이력 — 목록 지도ID 의 약 1/3 이 여기에만 있음, 예:
    개포주공6,7단지). C 우선, H 보강.
  - 필드: `WTNNC_SN, DGM_NM(도형명), SIGNGU_SE, LCLAS_CL/ATRB_SE(UPIS 분류코드),
    DGM_AR(면적㎡)`. 원 좌표계 EPSG:5174.
  - **`outSR=4326` + `geometryPrecision=6` 서버 재투영 지원** (실측) → 좌표 변환
    코드 불필요.
  - 속성만 조회(`returnGeometry=false`)는 3,305건이 한 번에 옴.
    도형은 `resultOffset` **미지원**(0행) → `returnIdsOnly` 로 ID 확보 후
    `objectIds` 배치(50개) 조회.
- 조인 실측 (2026-08-20 build): 사업장 1,152 (지도ID 376) → ID조인 361
  (C 249 + H ~112) + 보수적 이름조인(`_canon_name` exact) 77 = **feature 438**,
  1.4MB(precision 6). 지도ID 미해결 15.
- **미매칭 UQ181 도형(~2,900)은 표시하지 않는다** — 이력·해제·타 사업 코드
  (UQ5xxx/UQ63xx 등)가 섞여 있어 "현재 정비사업" 으로 그리면 오정보.
  표시 대상 = 정비몽땅 사업장과 매칭된 것만 (전 feature 에 단계 존재).

### 라이선스/약관
- 정비몽땅 데이터의 오픈데이터 판(OA-2253)은 공공누리 1유형(출처표시·상업이용
  가능)이었음. 현행 화면 데이터도 공공데이터 성격이나 명시 라이선스는 없음 →
  **표시용 사본 + 출처 상시 표기 + 원본 다운로드 미제공** (noise 레이어와 동일
  운영). 호출은 build 시 극소량(목록 1 + 속성 2 + 도형 ~12 요청).

## 부산 (구현 완료 — 점)

- data.go.kr `6260000/MaintenanceBusinessStatus1/getMaintenanceBusiness1`
  (`DATA_GO_KR_API_KEY` 활용신청 완료, 2026-08 실측 343건).
  필드: `areaName`(구역명), `step`(단계 12종 전수 → `BUSAN_STAGE_MAP`),
  `location`(주소, 75건 빈값), `areaUnit`(면적㎡), `aCode`.
- **좌표·폴리곤 없음** → `location` 을 Kakao 지오코딩(대표 위치 점).
  유형은 areaName 실재 키워드에서만 추출(없으면 None).
- ⚠ ServiceKey 는 raw concat 필수 (httpx `params=` 재인코딩 시 403 —
  molit 클라이언트와 동일 함정, 실측 재확인).
- 2026-08 build: 점 235 (주소없음 75 / 지오코딩 실패 20 / **타 지역 오지오코딩
  13 폐기** — 동명·도로명 중복이 원인. 시도 경계 박스 필터가 잡음).

## 경기 (구현 완료 — 점)

- 경기데이터드림 `openapi.gg.go.kr/GenrlimprvBizpropls` (`GG_DATA_API_KEY`,
  2026-08 실측 533건). 필드: `SIGUN_NM/CD`, `BIZ_TYPE_NM`(재건축/재개발/주거
  환경개선), `IMPRV_ZONE_NM`, `LOCPLC_ADDR`(주소), `ZONE_AR`, `BIZ_STEP_NM`
  (단계 9종 전수 → `GG_STAGE_MAP`).
- **좌표·폴리곤 없음** → 주소 지오코딩 점. 2026-08 build: 점 512
  (실패 21, 동 단위 근사 137 — "~번지 일원" 등 포괄 지번은 필지 매칭 불가).
- ⚠ **WAF 2종**: ① 서버형 기본 UA(curl/httpx) 는 차단 페이지(EUC-KR html)
  → 브라우저 UA 필수. ② `Accept`/`Referer` 헤더를 붙이면 500 → UA 만 보낼 것.
- 데이터셋 페이지: data.gg.go.kr infId `S62GFEEN7JMLMA0PH6CF19108891`
  (포털 자체도 서버형 클라이언트 차단 — 서비스명은 브라우저로 확인했음).

## 지오코딩 (crawler/src/redevelopment/geocode.py)

- Kakao `/v2/local/search/address.json` (`KAKAO_REST_API_KEY`).
  정제(괄호·"번지 일원"·상세층 제거) → 실패 시 지번 떼고 동 단위 폴백
  (`precision: "dong"` 표기 — 웹 팝업이 "동 단위 근사" 로 노출).
- 결과(실패 포함) 파일 캐시: `crawler/data/redev_geocode_cache.json` —
  재빌드 시 재호출 없음. keep-alive 끊김 재시도 내장.
- 서울 미매칭 사업장 714건도 같은 방식으로 점 표시 (전 사업장 100% 표시).

## 전국 폴리곤 (결론: VWorld 불가 — 2026-08-21 확정)

- **VWorld 데이터 API 공식 카탈로그(189종)에 재개발·재건축 정비구역 레이어가
  없다.** (전수 확인: PublicDataReader `raw/code_vworld.json` = 데이터 API
  레퍼런스 미러.) 가장 가까운 것은 `LT_C_UD601 주거환경개선지구도`(주거환경
  개선 유형만), `LT_C_UPISUQ161 지구단위계획` 정도.
- `LT_C_UPISUQ181` 은 이름 검증은 통과하지만(=내부 존재) `INCORRECT_KEY` 로
  거부 = **미개방 레이어**. 개발키/운영키 차이는 유효기간(6개월/2년)뿐이라
  운영키로도 못 연다.
- ⚠ VWorld `INCORRECT_KEY` 는 오도된 에러 — ① 미개방 레이어 ② 키에 데이터
  API 사용 권한 없음/차단 ③ 진짜 키 오류가 모두 같은 코드로 나온다.
  판별: 없는 레이어명은 `INVALID_RANGE`(이름 검증이 키 검증보다 먼저),
  키 자체 유효성은 검색 API(`req/search`)로 대조. 상세는
  `~/.claude/TOOL_GOTCHAS.md` "VWorld 데이터 API" 항목.
- 현 개발키는 검색 API 는 상시 정상이나 데이터 API 는 초기 몇 회 성공 후
  지속 거부 — **키의 "사용 API" 신청 범위에 2D 데이터 API 포함 여부**를
  마이페이지에서 확인 필요 (향후 VWorld 를 다른 레이어에 쓸 때만 해당).
## 부산·경기 폴리곤 정찰 (2026-08-21)

### 경기 — 폴리곤 소스 확보 ✅ (단계 조인은 부분적)
- 경기부동산포털 ArcGIS (키 불필요, 브라우저 UA 권장):
  `http://gris.gg.go.kr:8080/grisgis/rest/services/bdsUseLand_20090805/MapServer`
  - **72 = 정비구역(356)** / 99 = 재정비촉진지구(19) / 74 = 주거환경개선지구(31)
    / 81 = 재개발구역(1). 합계 407.
  - 필드: `ALIAS`(구역명) `NTFDATE`(고시일) `MNUM` `REMARK` `STD_SGGCD`.
  - `outSR=4326` + `geometryPrecision` 서버 재투영 지원(서울 UPIS 와 동일).
  - ⚠ **`resultOffset` 페이징 미지원**(`Pagination is not supported`) →
    `returnIdsOnly` 로 ID 확보 후 `objectIds` 배치(40개) 조회.
  - 서비스명이 `_20090805` 지만 **데이터는 갱신 중**(고시 2025년 24건·2026년 1건).
- 데이터 품질 한계: `ALIAS` 121/407(30%), `NTFDATE` 72/407(18%) 만 채워짐.
- **단계 조인 실측** (경기 API 점 512 vs 폴리곤 407):
  - 이름 exact 매칭(정규화 후): **54건** — 표본 검수 전부 정확
    (`수진1 재개발 정비구역`↔`수진1`, `호원2구역 재개발정비구역`↔`호원2구역` 등)
  - point-in-polygon: **51건** — 낮은 이유는 좌표계·구현 오류가 아니라
    **지오코딩 점이 구역 경계 밖에 떨어지기 때문**(폴리곤→최근접점 거리
    중앙값 333m, 500m 이내 250/407). 대표지번이 구역 중심이 아님.
  - 합집합 기준 커버리지 ≈ 100건/407 (25%).
  - ⚠ **최근접(nearest) 매칭은 채택 금지 판단** — 정비구역은 서로 인접해
    몰려 있고(성남 신흥/수진 등) 폴리곤 이름이 70% 비어 검증 불가라
    오매칭 시 잘못된 단계가 조용히 붙는다(날조 금지 원칙 위배).

### 부산 — 막힘 ❌
- 도시공간정보시스템(`lifemap.busan.go.kr`) ArcGIS REST → **시스템 점검 안내
  페이지**로 리다이렉트(`/error.html`). 공개 엔드포인트 없음.
- 정비사업 통합홈페이지(dynamice.busan.go.kr): 사업장 미니홈
  `/home/<aCode>/main.do` 가 API `aCode` 와 동일 체계지만, 지도는 **위치도
  이미지(loctImgPath)** 뿐 — 좌표·폴리곤 없음.

### 전국 후보 (미해결)
- **NSDI 오픈마켓 `data.nsdi.go.kr/dataset/12709`
  "(연속주제)_도시및주거환경정비/정비구역"** = 전국 SHP 존재 확인(검색).
  단 이 네트워크에서 `data.nsdi.go.kr`·`www.nsdi.go.kr` 모두 **접속 불가**
  (curl·브라우저 전부 연결 실패) → 사용자 환경에서 직접 다운로드 후 적재가
  현실적 경로. 되면 전국(부산 포함)이 한 번에 해결된다.
- 토지이음 GIS `https://www.eum.ne.kr:9004/MapPlan/MapPlan`
  (`?req=search&version=<YYYYMMDD>&layer=FA&code=<pnu>` → GeoJSON, EPSG:5179)
  는 동작 확인했으나 레이어 코드 체계(FA/FD/FE/CB/DA…)에 정비구역이 있는지
  미확인. `req=code`(bbox) 는 빈 응답. 리버스 난이도 대비 실익 불확실.
- upis.go.kr 은 접속 불가(연결 실패).

## 운영

- 갱신: **월 1회** `python scripts/redev_layer.py check` → exit 1(사업장 수 변화)
  이면 `build` 후 `web/public/redev/` 커밋 = Vercel 배포. 크론 미편입.
- 필요 env(루트 .env 자동 로드): `DATA_GO_KR_API_KEY`(부산),
  `GG_DATA_API_KEY`(경기), `KAKAO_REST_API_KEY`(지오코딩).
- 단계 원값이 새로 나타나면 build 가 `⚠ 미매핑 단계` 경고 출력 →
  `phases.py` 의 지역별 STAGE_MAP 에 추가.
- 정비몽땅 화면 개편 시 `fetch_biz_list()` 가 헤더 검증으로 실패하게 해 둠
  (조용한 오파싱 방지). 새 지역 추가 = 어댑터 모듈(`build_features`/
  `source_count`) + `redev_layer.py` REGIONS 등록 + phases 매핑.
