---
title: BIT (bit.courts.go.jp) API 정찰 보고서
date: 2026-05-10
status: 검색 + 상세 + 페이징 + 사진 + 좌표 + PDF endpoint 모두 발굴 완료 / PDF 본격 구현 미완
---

# BIT 사이트 정찰 결과

> `https://www.bit.courts.go.jp` (不動産競売物件情報サイト) — 일본 법원 경매 시스템.
> 한국 courtauction.go.kr와 달리 **JSON RIA가 아니라 Java Struts 기반 HTML 응답**.
> 모든 endpoint가 form POST + HTML 응답 (HTML scraping 필요).

## 1. Endpoint 매핑

| 단계 | Method | Path | Body | 응답 |
|---|---|---|---|---|
| 메인 | GET | `/` (→ 301 → `/app/top/pt001/h01`) | — | 블록 지도 페이지 |
| 블록 선택 | POST | `/app/top/pt001/h02` | `blockCls={01-09}&tabId=property` | 도도부현 선택 페이지 (`searchareaselectForm`) |
| 도도부현 검색 | POST | `/app/areaselect/ps002/h05` | (form 전체 — saleCls/saleStandardAmount/...) | **검색 결과 리스트** |
| 시구정촌 검색 | POST | `/app/areaselect/ps002/h10` | 위 + `municipalityId`, `municipalityNm` | **검색 결과 리스트** (단일 시구정촌) |
| 매물 상세 | POST | `/app/propertyresult/pr001/h05` | `saleUnitId={11자}&detailCourtId={5자}&transitionTabId=1` + 검색 form 전체 hidden inputs | 매물 상세 페이지 (target=_blank) |
| 페이지네이션 | POST | `/app/propertyresult/pr001/h04` | 직전 검색 응답의 propertyResultForm hidden inputs 그대로 + `currentPage`/`pageSize` 갱신 | 다음 페이지 결과 |
| 三点セット 확인 | POST | `/app/detail/pd001/h03` | `courtId&saleUnitId` | text "success" or 실패 |
| 三点セット 다운로드 | GET | `/app/detail/pd001/h04?courtId=&saleUnitId=` | (확인 성공 후) | PDF binary |

### 흐름 검증 완료 (2026-05-07 정찰)
1. `GET /` → 301 → `200`, 메인 HTML 332KB
2. `POST /app/top/pt001/h02 body=blockCls=03&tabId=property` → 200, "競売物件検索" (관동) 82KB
3. `POST /app/areaselect/ps002/h05 body=prefecturesId=13&saleCls=1&saleCls=2&saleCls=3&saleCls=4&saleClsSelected=1,2,3,4&saleStandardAmountCls=1&tabId=property&blockCls=03` → 200, "競売物件検索結果一覧", **도쿄 95건**, 1MB

## 2. 핵심 식별자

### blockCls (광역 블록, 9개)
| code | 名 | prefecture 코드 |
|---|---|---|
| 01 | 北海道 | 91-94 (지점별: 91 札幌 / 92 函館 / 93 旭川 / 94 釧路) |
| 02 | 東北 | 02-07 |
| 03 | 関東 | 08-14 |
| 04 | 北陸甲信越 | 15-20 |
| 05 | 東海 | 21-24 |
| 06 | 近畿 | 25-30 |
| 07 | 中国 | 31-35 |
| 08 | 四国 | 36-39 |
| 09 | 九州沖縄 | 40-47 |

### prefectures (47 + 北海道 4지점)
JIS 도도부현 코드와 동일 (예: 13 東京都, 27 大阪府).
북해도만 4지점 (91-94)으로 별도 코드.

### courtId (5자리)
- 31111 東京地方裁判所本庁
- 31131 東京地方裁判所立川支部
- 패턴 발견: 311XX = 東京地裁
- 전국 매핑은 검색 결과 페이지에서 점진적 수집 예정

### saleCls (用途, 체크박스)
| code | 名 |
|---|---|
| 1 | 土地 |
| 2 | 戸建て |
| 3 | マンション |
| 4 | その他 |

### 사건번호 패턴
`{元号}{年}年({種別})第{番号}号`
- 元号: 令和(R) / 平成(H)
- 種別:
  - **ケ**: 担保不動産競売 (한국 임의경매 대응)
  - **ヌ**: 強制競売 (한국 강제경매 대응)

## 3. 매물 카드 (검색 결과 페이지)

JSON이 아닌 HTML scraping. 카드 한 건당 다음 필드:

```html
<a onclick="tranPropertyDetail('00000021169', '31131', '1')">
  東京地方裁判所立川支部　令和07年(ケ)第221号
</a>
<span class="badge bit__badge_tochi">土地</span>
<p>期間入札</p>
<div>閲覧開始日: 令和08年04月17日</div>
<div>入札期間: 令和08年05月07日〜令和08年05月13日</div>
<div>開札期日: 令和08年05月19日</div>
<div>特別売却期間: 令和08年05月20日〜令和08年05月22日</div>
<img src="/data/image/TAC_R07K00221_1_l.jpg" />
<p>売却基準価額: 4,940,000円</p>
<p>買受申出保証金: 988,000円</p>
<p>八王子市川町１３番１３</p>  <!-- 주소 (전각 숫자) -->
<p>ＪＲ中央線「西八王子」駅 北西方 道路距離 約４．３ｋｍ</p>  <!-- 교통 -->
<button onclick="tranPropertyMap('00000021169', '31131', '2')">周辺地図</button>
```

### 사진 URL 패턴
`/data/image/{COURT_PREFIX}_R{YY}{KIND_CHAR}{NO5}_{SEQ}_{SIZE}.jpg`
- COURT_PREFIX: TAC = 立川 (3자), 다른 법원도 3자 약자
- R: 元号 (R=令和, H=平成)
- YY: 2자리 연도
- KIND_CHAR: K=ケ, N=ヌ
- NO5: 5자리 0-padded 번호
- SEQ: 매물 순번 (property_seq)
- SIZE: l(large) / s(small) 등

## 4. 페이징

`#propertyResultForm`을 그대로 resubmit.

```javascript
function getData(page) {
  $("#pageSize").val($("#pageList").val());        // pageSize: 사용자 선택값
  $("#currentPage").val(page);                     // 1-indexed
  $("#resultListSearchButtonFlag").val('0');
  $("#pageListChangeFlg").val('0');
  // ... saleClsSelected, municipalityId, ... 인풋 갱신
  $("#propertyResultForm").submit();
}
```

총 건수: `<span class="bit__numberOfResult_totalNumber">95</span>件中`

## 5. 매물 상세 페이지 (`/app/propertyresult/pr001/h05`) — 정찰 완료

상세 응답에서 다음 필드를 BeautifulSoup으로 추출 가능 (도쿄 73건 검증):

- **3종 가격** (`.bit__syousai_text_kakaku_container` 안 라벨-값):
  - 売却基準価額 / 買受申出保証金 / 買受可能価額 — 円 단위 정수
- **매각기일 6종** (`.bit__multiHeadTable th-td` 페어):
  - 公示開始日 · 閲覧開始日 · 入札期間(start, end) · 開札期日 · 売却決定期日 · 特別売却期間(start, end)
- **物件 명세** (`.bit__paragraphBreaksTable` th-td):
  - 種別/物件番号/所在地/地目(登記)(現況)/土地面積/用途地域/利用状況/建ぺい率/容積率
  - 戸建て/マンション는 별도 fields (床面積/構造/専有面積/管理費 등)
- **상세 사진**: `.bit__image` src — `/data/image/{PREFIX}_R{YY}{KIND}{NO}_{SEQ}_d.jpg` (size_label `d`)
- **좌표**: hidden `#latitude` / `#longitude` (mapion API 호출용. 도쿄 검증 시 모두 WGS84 정상값)
- **三点セット PDF 버튼**: `#threeSetPDF` 존재 여부

### 三点セット PDF 다운로드 흐름 (`/app/property/syosai.js` JS 분석)

```javascript
$("#threeSetPDF").click(function() {
  $.ajax({ url: '/app/detail/pd001/h03', type: 'POST',
    data: { courtId, saleUnitId }, dataType: 'text' })
    .done(function(data) {
      if (data.match(/success/)) {
        location.href = `/app/detail/pd001/h04?courtId=${courtId}&saleUnitId=${saleUnitId}`;
      }
    });
});
```

→ 2단계 흐름 (확인 POST + 다운로드 GET). CORS 때문에 브라우저 직접 호출 불가 — server proxy route 필요.

### 좌표 체계
- BIT 응답은 mapion API 호환 좌표 (WGS84 호환).
- 도쿄 검증: 35.673419, 139.280488 (八王子市川町) 등 WGS84 범위 정상.
- 일본 측지계 JGD2011도 WGS84와 좌표값 거의 동일 (수 cm 차이) → 추가 변환 불필요.

### 페이지네이션 — 핵심 트릭

검색 결과 페이지의 `propertyResultForm` hidden inputs를 그대로 다음 호출에 재사용해야 함.
인풋이 빠지면 BIT가 컨텍스트를 잃고 "該当データがありません" 빈 응답 반환.

```python
# crawler/src/bit/client.py 의 핵심
form_ctx = extract_property_result_form(html)  # 직전 응답의 hidden inputs 보존
body = dict(form_ctx)
body["currentPage"] = str(page)  # 갱신
body["pageSize"] = str(page_size)
# POST /app/propertyresult/pr001/h04
```

페이지 범위 초과 시 BIT는 HTTP 500 — graceful stop 필요.

### Static asset 직접 URL
- 사진은 `/data/image/...`로 직접 GET 가능 (인증 없는 정적 파일, content-type `image/jpeg`).
- 도쿄 73장 모두 정상 다운로드 → Supabase Storage `jp-auction-photos` 버킷 적재 완료.

## 5b. 미정찰 / 추후 작업

- **시구정촌 코드 매핑**: 도도부현 → 시구정촌 흐름 (`/app/areaselect/ps002/h10`)에서 사용할 BIT municipalityId. JIS 시구정촌 코드(예: 八王子市=13201)와의 매핑 확인 필요
- **평가 재조정 이력**: 매물별 평가 변경 시점·이유 — 별도 탭 정찰
- **매각결과(낙찰가)**: 별도 탭(`tabId=result`) — 한국 매각결과검색 대응
- **PDF server proxy**: BIT 2단계 호출을 본 사이트 API route로 대리 (현재는 상세 페이지에 PDF 버튼 존재 배지만 표시)

## 6. 한국 클라이언트와의 차이

| 항목 | 한국 (courtauction) | 일본 (BIT) |
|---|---|---|
| 응답 형식 | JSON (WebSquare RIA) | HTML (Java Struts) |
| 검색 endpoint | 단일 W2X (`selectCsSrchRslt.on`) | form POST `/app/areaselect/ps002/h05` |
| 페이지네이션 | `dma_pageInfo.pageNo` JSON | `currentPage` form input + resubmit |
| 사건번호 | `2026타경100` | `令和08年(ケ)第100号` |
| 가격 단위 | 만원 (예: 100,000,000) | 円 (예: 4,940,000) |
| 좌표 | KATEC (EPSG:5181) | JGD2011 (예상, 미확정) |
| 사진 | base64 (JSON 응답에 포함) | 정적 URL (`/data/image/...`) |
| 자동 차감 | 회차마다 20% (자동) | 없음. 평가 재조정으로 갱신 |
| 보증금 | 최저가의 10% | 売却基準価額의 20% (예: 4,940,000 → 988,000) |

## 7. 결정사항 (정찰 결과 반영)

- **HTML scraping**: BeautifulSoup4 / lxml 필요. 한국과 달리 JSON 파싱이 아님
- **세션 쿠키 보존**: 단계별 cookie 필요 (1단계 이후 JSESSIONID 발급)
- **Referer 필수**: 직접 호출 시 차단되는지 정찰 시 확인됨 (Referer 보냈을 때만 안정)
- **min_interval_ms=800**: 한국(500ms)보다 보수적. IP block 방지

## 8. 다음 액션

1. `0009_jp_init.sql` 마이그레이션 작성 (이미 `jp_schema_design.md` 기반 결정)
2. `bit/client.py` 1차 구현 — 위 흐름 그대로 + BeautifulSoup 파싱
3. `bit/store.py` 1차 구현 — 한국 store 패턴 차용
4. PoC 적재 — 도쿄 1개 시구정촌 (예: 八王子市) 100건 미만
5. 매물 상세 페이지 응답 정찰 (이건 PoC 진행 중에 자연스럽게)
