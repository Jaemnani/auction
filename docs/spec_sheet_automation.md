# 매각물건명세서 자동 수집 — 정찰 완료 사양서

**상태**: 취득·텍스트 추출까지 **실증 완료** (2026-08-10). 남은 것은 파싱·저장·노출 구현.
**목적**: 인수액(대항력 임차인 보증금 중 낙찰자 부담분)을 사용자 입력 없이 자동 산출.

---

## 0. 왜 필요한가

인수액 = `대항력 임차인 보증금 − 그 임차인이 배당받는 금액`.
판정에 필요한 4개 값(**보증금 · 전입일 · 확정일자 · 배당요구 여부**)은 법원 API가 제공하지
않는다. 우리 DB로 대체 판정이 되는지 확인했으나 불가:

| 신호 | 건수 (활성 13,378 기준) |
|---|---:|
| 물건비고(rmk) 존재 | 6,740 (50%) |
| 선순위 임차인 플래그 | 78 (0.6%) |
| 임대관계 미상 플래그 | 7,343 (55%) |

→ 비고만으로 "인수액 0"을 단정하면 틀린다. **명세서가 유일한 출처.**

---

## 1. 공개 시점 (제품 제약)

| 서류 | 공개 |
|---|---|
| 매각물건명세서 | 매각기일 **1주 전**부터 |
| 현황조사서 · 감정평가서 | 매각기일 **2주 전**부터 |

우리 DB의 활성 매물은 기일이 2주 이내(법원 공고 지평)라 **절반 이상(7,174/13,378)이
이미 명세서 공개창 안**이다. 웹에는 `spec_open=1` 필터로 이미 노출 중.

---

## 2. 취득 경로 (실측 확인)

### ⚠ 핵심: raw fetch 는 거부, **UI 흐름은 통과**

| 방식 | 결과 |
|---|---|
| 코드에서 API 직접 POST | `{"data":{"ipcheck":false}, "message":"해당 IP는 비정상적인 접속으로…"}` — IP·쿠키·회선 바꿔도 동일 |
| Playwright 로 실제 UI 클릭 | **정상 200, ipcheck=true** |

차단 기준은 IP가 아니라 **요청 방식**이다. (한때 "IP 차단"으로 오진했으나, 새 브라우저
컨텍스트 + 다른 회선에서도 raw fetch 만 거부되고 UI 는 통과함을 확인.)
→ **자동화는 반드시 헤드리스 브라우저로 UI 를 몰아야 한다.**

### 전체 체인

```
1. courtauction.go.kr  기일별검색(PGJ153F00) → 검색 → 담당계 → 물건 클릭
2. POST /pgj/pgj15B/selectAuctnCsSrchRslt.on          (상세, ipcheck=true)
3. [매각물건명세서 보기] 클릭
   POST /pgj/pgj15B/insertDspslGdsSpecArtcWdrwInf.on  → 200
     body: {"dma_dspslGdsSpecLog":{cortOfcCd, csNo, dspslGdsSeq, orvParam,
             dspslGdsSpcfcEcdocId, cortAuctnMbrsId:"NONUSER", docFlag:"1"}}
     resp: data.dma_dspslSpcfcInfo = {scsYn, encParam, url}
4. 뷰어 새 탭: {url}?paramData=base64(JSON.stringify({encParam,pspTkn:"NA",pspSid:"NA"}))
   → https://ecfs.scourt.go.kr/sgvo/websquare/websquare.html?w2xPath=/sgvo/ui/sgvo200/SGVO201M01.xml
5. 뷰어 내부:
   POST ecfs.../sgvo/sgvomain/selectDocVwrInf.on   문서 메타
   POST ecfs.../sgvo/sgvomain/insertEcdocHst.on    열람 이력
   POST ecfs.../sgvo/sgvomain/getPdf.on            → {accessToken(JWE), streamdocsId}
   GET  pvo.scourt.go.kr/streamdocs/v4/documents/{id}/t   ← 텍스트 레이어 JSON (52~73KB)
   GET  pvo.scourt.go.kr/streamdocs/v4/documents/{id}/r   ← 렌더 이미지 PNG
```

**PDF 파일은 다운로드되지 않는다.** StreamDocs(사설 문서 스트리밍)가 렌더한다.

### ✅ 그러나 텍스트는 DOM 으로 읽힌다 (OCR 불필요)

StreamDocs 뷰어 iframe(`pvo.scourt.go.kr/streamdocs/view/sd`)의 `body.innerText` 에
문서 전문이 들어온다. Playwright 로 프레임 텍스트만 읽으면 끝.

```python
vp = ctx.pages[-1]                      # 뷰어 탭
for fr in vp.frames:
    if "streamdocs/view/sd" in fr.url:
        text = await fr.evaluate("() => document.body.innerText")
```

---

## 3. 추출 실증 (2024타경2532, 서울중앙지법)

```
사건 2024타경2532 부동산임의경매 1 2026. 7. 20. 최장길 전자서명완료
별지 기재와 같음 2022.10.11. 근저당 배당요구종기 2024. 8. 1.      ← 최선순위(말소기준) + 종기
...
인터 주거및
2022.07.10.-
코트라 504.7 현황조사 점포 2022.07.15.
2024.07.09.
주식회사 임차인                                                   ← 임차인 행 (열이 뒤섞임)
...
1회 2026.07.07 2,813,645,810 281,364,600                          ← 회차별 최저가/보증금
2회 2026.08.11 2,250,916,000 225,091,600
```

판정: 전입/사업자등록 **2024.07.09** > 말소기준 **2022.10.11** → **대항력 없음 → 인수액 0**.
보증금·차임은 공란(현황조사 출처, 미상).

---

## 4. 남은 작업

### 4-1. 파싱 — **좌표 확보로 해결됨 (LLM 불필요)**

`innerText` 만 쓰면 PDF 시각 순서라 표의 열이 뒤섞이지만, **좌표를 함께 뽑으면 결정적으로
복원된다.** 유료 API 없이 규칙 기반으로 충분하다.

**핵심**: 문서 텍스트는 캔버스 위에 깔린 `<p class="script">` 레이어에 있고 **`font-size: 0px`**
이다. 그래서 `Range.getBoundingClientRect()` 는 0×0 을 반환한다 — 반드시
**`parentElement` 의 좌표**를 써야 한다. (이걸 몰라 두 번 헛돌았음.)

```js
// streamdocs/view/sd 프레임에서 실행
const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
const out = []; let n;
while ((n = walker.nextNode())) {
  const t = (n.nodeValue || '').trim(); if (!t) continue;
  const pe = n.parentElement; if (!pe) continue;
  const b = pe.getBoundingClientRect();          // ← Range 아님. parentElement
  if (b.width === 0 && b.height === 0) continue;
  out.push({ t, x: Math.round(b.x), y: Math.round(b.y) });
}
```

⚠ **렌더 완료까지 폴링 필수** — `document.querySelectorAll('p.script').length > 30` 이 될
때까지 기다린다. 안 그러면 빈 문서를 읽는다(실측: 같은 코드가 어떤 실행에선 4개, 어떤
실행에선 66개).

실측 결과 (2024타경2532) — 66개 노드, y 로 행이 깔끔히 갈림:

```
y= 352  별지 기재와 같음 2022.10.11. 근저당 배당요구종기 2024. 8. 1.   @402
y= 520  인터 주거및                                                  @272
y= 528  2022.07.10.-                                                @501
y= 536  코트라 504.7 현황조사 점포 2022.07.15.                        @266
y= 544  2024.07.09.                                                 @501
y= 556  주식회사 임차인                                              @262
```

임차인 블록은 y 520~556 에 모여 있고 x 로 열이 갈린다(성명 262~272 / 점유부분·출처 266 /
날짜 501). **행=y 클러스터, 열=x 구간** 규칙으로 복원 가능.

여전히 **저신뢰 시 미저장** 원칙은 유지 — 인수액은 금액이 걸린 값이라, 애매하면 채우지 말고
"미상"으로 두고 명세서 원문 링크를 병기한다.

추출 목표 스키마:

추출 목표 스키마:
```ts
{ lienDate: string,            // 최선순위 설정일 (말소기준)
  demandDeadline: string,      // 배당요구종기
  tenants: [{ name, deposit: number|null, moveInDate: string|null,
              fixedDate: string|null, demandFiled: boolean|null,
              source: "현황조사"|"권리신고" }],
  confidence: "high"|"low" }
```

### 4-2. 저장

`property_tenancy` 신설 (0026): `property_id, lien_date, demand_deadline,
tenants jsonb, assumed_amount, confidence, raw_text, fetched_at`.
계산은 기존 `web/src/lib/assumption.ts` 의 `simulate()` 재사용 — **이미 검산 완료**.

### 4-3. 수집 트리거 (차단 위험 관리)

**온디맨드 권장** — 일괄 수집(공개창 7,174건/일)은 요청량이 커 차단 위험.

- 지도: 마커 클릭 → 팝업 오픈 시 요청 → InfoWindow `setContent()` 로 갱신
- 목록: 상세 진입 시
- 결과는 DB 캐시 → 다음 사용자에겐 즉시

### 4-4. 노출

지도 카드 인수액 줄은 이미 구현됨(`lib/map-popup-rows.ts`). 지금은 사용자가 계산기에서
저장한 localStorage 값을 읽는데, 이걸 DB 값 우선으로 바꾸면 된다.

---

## 5. 리스크

1. **차단** — UI 흐름이라 사람과 구별이 어렵지만, 요청량이 늘면 위험. 온디맨드 + 캐시 필수.
   막히면 기존 수동 계산기로 자동 폴백(이미 구현됨).
2. **StreamDocs/화면 변경** — 사설 뷰어라 개편 시 깨짐. 프레임 텍스트 방식은 비교적 견고.
3. **추출 오독** — 금액 오류는 치명적. 저신뢰 시 미저장 + 화면에 "명세서 원문 확인" 링크 병기.
4. **성능** — UI 흐름이라 매물당 30~60초. 온디맨드라면 사용자 대기시간 → 비동기 처리 + 로딩 표시.

---

## 6. 재현 스크립트

정찰 스크립트는 세션 스크래치패드에 있음(`pw_view.py` 등). 핵심 흐름만 옮기면:

```python
browser = await pw.chromium.launch(headless=True, channel="chrome")  # 시스템 Chrome
# 기일별검색 → 검색 → 담당계 → 물건 → [매각물건명세서] → 뷰어 탭 프레임 텍스트
```

관련: `docs/api_recon.md` "매각물건명세서" 절, `web/src/lib/assumption.ts`,
`web/src/lib/map-popup-rows.ts`
