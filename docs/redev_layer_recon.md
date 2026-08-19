# 정비사업(재개발·재건축) 레이어 — 데이터 소스 정찰 기록

2026-08-20. 목표: 지도(/map)에 정비구역 폴리곤 + 사업 단계 필터 표시.
재현 스크립트: `crawler/scripts/probe_redev.py`, 빌더: `crawler/scripts/redev_layer.py`.

## 결론 (Go/No-go)

**Go — 1차 범위는 서울.** 서울은 폴리곤+단계를 키 없이 전부 확보 가능.
전국 통합 소스는 존재하지 않고, 타 시도는 키 신청·소스 미확정이라 후속 확장.
웹은 `web/public/redev/index.json` 의 지역 목록 주도라 지역 추가 = 데이터만 추가.

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

## 타 시도 (후속 — 소스 정찰만)

| 지역 | 단계 현황 | 폴리곤 | 막힌 것 |
|---|---|---|---|
| 부산 | data.go.kr `6260000/MaintenanceBusinessStatus1/getMaintenanceBusiness1` — areaName/location/step 확인 | 미확정 (dynamice.busan.go.kr 정찰 필요) | 기존 `DATA_GO_KR_API_KEY` 가 이 API 에 **미신청** → 포털에서 활용신청(자동승인) 필요 (403 SERVICE_KEY_IS_NOT_REGISTERED 실측) |
| 경기 | 경기데이터드림 "일반 정비사업 추진현황" (시군/구역명/위치/단계) | 없음 | 경기데이터드림 별도 인증키 발급 필요 |
| 전국 폴리곤 | — | 국토부 토지이용계획정보(data.go.kr 15123973)는 LINK 형(외부 연계)이라 엔드포인트 불명. VWorld WMS 공개 목록엔 정비구역 레이어 없음(시장정비구역 lt_c_ub901 뿐). VWorld 데이터 API 카탈로그는 키·로그인 없이 조회 불가 | VWorld 키 발급 후 `LT_C_UPISUQ181` 존재 여부 확인이 다음 스텝 |

## 운영

- 갱신: **월 1회** `python scripts/redev_layer.py check` → exit 1(사업장 수 변화)
  이면 `build` 후 `web/public/redev/` 커밋 = Vercel 배포. 크론 미편입.
- 단계 원값이 새로 나타나면 build 가 `⚠ 미매핑 단계` 경고 출력 →
  `phases.py` 의 `SEOUL_STAGE_MAP` 에 추가.
- 정비몽땅 화면 개편 시 `fetch_biz_list()` 가 헤더 검증으로 실패하게 해 둠
  (조용한 오파싱 방지).
