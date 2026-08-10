# 공항 소음등고선 레이어

**상태**: 구현 완료 (2026-08-10). 6개 공항 등고선이 지도 레이어로 뜬다.
**목적**: 공항 소음대책지역(제1~3종 구역)을 우리 지도에 오버레이해 입찰 판단 재료로 제공.
**방식**: 원 서비스의 WFS 를 **한 번 받아 GeoJSON 으로 저장**하고 그것을 재사용.

> ⚠ 최초 설계는 "매 요청 라이브 호출"이었으나, 그러면 남의 서버를 상시 때린다.
> 등고선은 연 단위로만 바뀌므로 **1회 수집 → 정적 파일 재사용**으로 바꿨다
> (`crawler/scripts/noise_layer.py build`). 아래 1장의 라이선스 논의는 그대로 유효하고,
> 저장본이라 **출처 표기·원본 다운로드 미제공**이 더 중요해졌다.

---

## 1. 라이선스 — 왜 우리가 SHP 을 직접 받지 않았나

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

## 3. 구현 (완료)

### 3-1. 수집·변환 — `crawler/`

```
python scripts/noise_layer.py build    # 6개 공항 수집 → web/public/noise/*.json
python scripts/noise_layer.py check    # 원본에 새 YEAR 가 있는지만 확인 (exit 1 = 갱신 필요)
```

| 파일 | 역할 |
|---|---|
| `src/noise/proj.py` | EPSG:5179(UTM-K) → EPSG:4326 역투영. **pyproj 없이 순수 Python** (Snyder 횡메르카토르). 검증: 원점 (1000000, 2000000) → 정확히 (127.5, 38.0) |
| `src/noise/fetch.py` | WFS GetFeature → GML 정규식 파싱 → GeoJSON. WECPNL 오름차순 정렬(넓은 구역이 아래 깔림) |
| `scripts/noise_layer.py` | build / check |

좌표는 소수 6자리로 반올림(≈11cm) — 기하 단순화가 아니라 반올림이라 모양은 보존하면서
파일이 절반 이하가 된다. 산출물 합계 **2.6MB** (CJU 1.2MB, ICN 651KB, GMP 344KB,
PUS 255KB, RSU 170KB, USN 116KB).

**갱신**: 연 1회 `check` → exit 1 이면 `build` 후 커밋. 자동화하지 않는다(원본 부하 최소화).

### 3-2. 표시 — `web/`

| 파일 | 역할 |
|---|---|
| `src/lib/noise-layer.ts` | index/파일 fetch + 메모리 캐시, `airportsInView()` (bbox 교차, 여유 0.25°) |
| `src/components/property-map.tsx` | Data layer 주입·스타일·클릭 팝업·범례 토글·출처 표기 |

- 기본 **꺼짐**. 켤 때만 받는다 — 공항당 수백 KB 라 항상 켜두면 낭비다.
- **화면에 들어온 공항 것만** 로드하고, `idle` 마다 재확인해 새로 들어온 공항을 추가한다.
  한 번 받은 공항은 `noiseLoadedRef` 로 중복 주입을 막는다.
- 폴리곤 클릭 → "공항소음 제2종 구역 / 2023년 등고선 · 참고용" InfoWindow.
- **실패 격리**: index·파일 fetch, `addGeoJson` 모두 실패를 삼킨다. 레이어만 안 뜨고 지도는 정상.

### 3-3. 고지 (의무)

레이어가 켜져 있는 동안 지도 우하단에 상시 노출:

> 자료: [공항소음포털](https://www.airportnoise.kr/anps/gis) · 참고용(정확한 구역은 관할 지자체 확인)

---

## 4. 주의

1. **참고용 고지** — 원 사이트가 "지적도를 포함한 모든 주제도는 참고용으로만 사용하시기
   바랍니다" 라고 명시. 우리 화면에도 같은 취지를 표기해야 한다.
2. **법적 효력** — 소음대책지역은 「공항소음 방지 및 소음대책지역 지원에 관한 법률」상
   재산권 제약·지원이 걸리는 법정 구역이다. 정확한 구역 판정은 관할 지자체 확인이 필요하다.
3. **서비스 의존** — 원 서비스가 바뀌면 레이어만 사라지도록 실패를 격리한다(지도 본체 무영향).
4. **이용 문의 병행 권장** — 국토교통부/한국공항공사에 상업적 이용 가능 여부를 문의해 두면,
   저장본 재사용의 근거가 분명해진다. (현재는 출처 표기 + 원본 다운로드 미제공으로 대응)
5. **원본 재배포 금지** — `web/public/noise/*.json` 은 지도 표시용이다. 이 파일을 내려받게
   하는 UI(다운로드 버튼 등)를 만들지 않는다.

---

## 5. 검증 기록 (2026-08-10)

- **좌표**: 원점 (1000000, 2000000) → (127.500000000, 38.000000000) 정확 일치.
  6개 공항 등고선 중심이 모두 각 공항 BBOX 안 (김포 첫 정점 126.772549, 37.575795).
- **데이터**: 6개 파일 모두 `WECPNL = [70, 75, 80, 85, 90, 95]` 6단계 존재.
  정점 수 CJU 52,227 / ICN 28,517 / GMP 15,068 / PUS 11,172 / RSU 7,418 / USN 5,039.
- **화면**: 로컬 dev 에서 토글 ON → `index.json` + 화면 안 공항(GMP·ICN)만 fetch →
  김포 상공에 1종(적)~3종 다(청) 동심 등고선 렌더 확인. 폴리곤 클릭 시
  "공항소음 제2종 구역 / 2023년 등고선 · 참고용" 팝업. 토글 OFF 시 폴리곤·출처 표기 동시 제거.

## 6. 재현

정찰 스크립트: 세션 스크래치패드 `noise4.py` (레이어 토글 시 요청 전수 캡처).
핵심 흐름 — 기일별 UI 조작 없이도 위 WFS 를 직접 호출하면 끝이다.
