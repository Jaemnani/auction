# 공항 소음등고선 레이어 — 정찰 완료 사양서

**상태**: 엔드포인트·데이터 구조 실증 완료 (2026-08-10). 남은 것은 변환·표시 구현.
**목적**: 공항 소음대책지역(제1~3종 구역)을 우리 지도에 오버레이해 입찰 판단 재료로 제공.
**방식**: 데이터를 우리가 저장·재배포하지 않고, **원 서비스의 WFS 를 라이브로 호출**해 표시.

---

## 1. 왜 라이브 호출인가

원본 SHP 은 브이월드에 있으나 라이선스가 걸린다.

- [(연속주제)_공항소음/소음대책지역](https://www.vworld.kr/dtmk/dtmk_ntads_s002.do?dsId=30275)
  (국토교통부, SHP, EPSG:5186/2097, 기준일 2026-07)
- 라이선스: **CC BY-NC-ND** — "원 저작자를 밝히면 자유로운 이용이 가능. **영리목적 이용이
  불가**하며 **변경 없이** 이용해야 함"
- 오버레이하려면 좌표 변환·단순화가 필요한데 이는 ND(변경금지)와 충돌 소지가 크고,
  NC(비영리)는 향후 수익화 시 위반이 된다.

⚠ 옛 국가공간정보포털 `nsdi.go.kr` 은 **도메인 폐지**(DNS 미해석). 브이월드로 통합됨.

한국공항공사가 공공데이터포털에 올린 [공항 소음대책지역 정보](https://www.data.go.kr/data/15002850/fileData.do)
는 이용허락 제한이 없으나 **면적·가구수 통계뿐이고 경계 좌표가 없어** 오버레이에 못 쓴다.

→ 그래서 저장 없이 원 서비스를 호출하는 라이브 레이어로 간다.

---

## 2. 엔드포인트 (실증 완료)

소음지도는 WMS 이미지가 아니라 **WFS 벡터**를 받아 OpenLayers 가 그린다.
(배경지도만 카카오 타일을 `/anps/gis/proxy?url=` 로 우회한다.)

```
POST https://www.airportnoise.kr/anps/gis/engine
Content-Type: text/xml

<wfs:GetFeature service="WFS" version="1.1.0">
  <wfs:Query typeName="TL_NS_CTRLN" srsName="EPSG:5179">
    <ogc:SrsName>EPSG:5179</ogc:SrsName>
    <ogc:Filter>
      <ogc:And>
        <ogc:PropertyIsEqualTo>
          <ogc:PropertyName>ARP_SE</ogc:PropertyName><ogc:Literal>GMP</ogc:Literal>
        </ogc:PropertyIsEqualTo>
        <ogc:PropertyIsEqualTo>
          <ogc:PropertyName>YEAR</ogc:PropertyName><ogc:Literal>2023</ogc:Literal>
        </ogc:PropertyIsEqualTo>
        <ogc:PropertyIsEqualTo>
          <ogc:PropertyName>WECPNL</ogc:PropertyName><ogc:Literal>85</ogc:Literal>
        </ogc:PropertyIsEqualTo>
      </ogc:And>
    </ogc:Filter>
  </wfs:Query>
</wfs:GetFeature>
```

**서버측에서 인증·쿠키 없이 그대로 호출된다** (실측 HTTP 200, 52KB). 법원 사이트와 달리
봇 차단이 없다.

### 응답

GML `wfs:FeatureCollection`, feature 1개. 속성:

| 필드 | 예시 | 의미 |
|---|---|---|
| `ARP_SE` | `GMP` | 공항 코드 |
| `YEAR` | `2023` | 등고선 기준연도 |
| `WECPNL` | `85` | 소음도 등급 (구역 구분) |
| `GEOM` | `gml:Polygon` → `gml:posList` | **EPSG:5179** 좌표열 (실측 정점 1,655개) |
| `USE_AT`, `REGIST_DT`, `UPDT_DT` | | 사용여부·등록·수정일 |

구역 색은 사이트 범례 기준: 제1종 / 제2종 / 제3종 가·나·다지구 (WECPNL 값으로 구분).

### 보조 API (모두 POST, 파라미터 없음)

| 엔드포인트 | 내용 |
|---|---|
| `/anps/gis/getAirportPosList` | 공항 6종 + BBOX — GMP 김포 / PUS 김해 / RSU 여수 / USN 울산 / CJU 제주 / ICN 인천 |
| `/anps/gis/getCtrlnList` | 공항×연도 등고선 목록 20세트 (김포 2023·2017·2010·1993, 인천 2023·2016·2010 등) |

---

## 3. 구현 설계

### 3-1. 좌표 변환

응답이 **EPSG:5179**(UTM-K)라 구글 지도(EPSG:4326)로 변환해야 한다.
`proj4` 로 변환 (웹에서 이미 쓰는 라이브러리 아님 — 서버에서 변환해 GeoJSON 으로 내리는 편이 낫다).

```
EPSG:5179 = +proj=tmerc +lat_0=38 +lon_0=127.5 +k=0.9996 +x_0=1000000 +y_0=2000000
            +ellps=GRS80 +units=m +no_defs
```

### 3-2. 캐시 (필수)

- 등고선은 **연 단위로만 바뀐다**(YEAR 필드). 매 요청마다 원 서비스를 때릴 이유가 없다.
- 우리 API route 에서 받아 변환한 GeoJSON 을 **장기 캐시**(`s-maxage` 수일~수주).
- 남의 서비스에 부하를 주지 않는 것이 라이브 방식의 전제다.
- ⚠ 캐시는 성능용 임시 사본이며 **재배포·다운로드 제공은 하지 않는다**.

### 3-3. 표시

- Google Maps **Data layer** 에 GeoJSON 주입 (`map.data.addGeoJson`).
- 구역별 색·투명도는 원 사이트 범례와 맞춘다. 클릭 시 "제3종 나지구" 같은 정보 표시.
- 지도 legend 에 토글 추가 (기존 마커 색 토글과 같은 자리).
- **출처 표기 의무**: "자료: 공항소음포털(airportnoise.kr)" 을 지도에 상시 노출.

### 3-4. 노출 범위

공항 6종 BBOX 안으로 지도가 들어왔을 때만 레이어를 켜면 요청이 최소화된다
(전국 뷰에서는 의미도 없다).

---

## 4. 주의

1. **참고용 고지** — 원 사이트가 "지적도를 포함한 모든 주제도는 참고용으로만 사용하시기
   바랍니다" 라고 명시. 우리 화면에도 같은 취지를 표기해야 한다.
2. **법적 효력** — 소음대책지역은 「공항소음 방지 및 소음대책지역 지원에 관한 법률」상
   재산권 제약·지원이 걸리는 법정 구역이다. 정확한 구역 판정은 관할 지자체 확인이 필요하다.
3. **서비스 의존** — 원 서비스가 바뀌면 레이어만 사라지도록 실패를 격리한다(지도 본체 무영향).
4. **이용 문의 병행 권장** — 국토교통부/한국공항공사에 상업적 이용 가능 여부를 문의해 두면,
   추후 자체 호스팅으로 승격할 근거가 된다.

---

## 5. 재현

정찰 스크립트: 세션 스크래치패드 `noise4.py` (레이어 토글 시 요청 전수 캡처).
핵심 흐름 — 기일별 UI 조작 없이도 위 WFS 를 직접 호출하면 끝이다.
