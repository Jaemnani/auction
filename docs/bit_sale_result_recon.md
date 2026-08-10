# BIT 売却結果(매각결과) 수집 — 정찰 완료 사양서

**상태**: 엔드포인트·필드 실증 완료 (2026-08-10). 남은 것은 클라이언트·파서·저장 구현.
**목적**: 일본 매물에 **낙찰가(売却価額)** 를 붙여, 한국의 `/sold`(최근 낙찰)에 대응하는
화면과 지도 표시를 가능하게 한다. 부수적으로 `jp_properties.status` 를 실제 결과로 확정한다.

> 기존 검색 피드(`competitive` 탭)에는 낙찰가가 **없다**. 낙찰 결과는 BIT 의 별도
> 「売却結果」 섹션에만 있고, 우리는 그동안 이 섹션을 수집하지 않았다.

---

## 1. 왜 필요한가

- `jp_properties` 에 낙찰가 컬럼 자체가 없다 → 일본은 "최근 낙찰" 화면을 못 만든다.
- `status` 를 "BIT 목록에서 사라짐 = 종결" 로 추정 중이라 신뢰도가 낮다
  (2026-08-10 기준 closed 2,245건 중 153건이 미래 기일이었다 → `0027` 커밋에서 교정).
  실제 결과를 받으면 **추정이 아니라 사실로** 상태를 확정할 수 있다.

---

## 2. 화면 흐름 (실증)

BIT 상단 탭 `競売物件 / 売却結果 / 過去データ / スケジュール` 중 **売却結果**.
JS `tranArea('result','')` → `#headerForm` 의 `tabId` 를 `result` 로 바꿔 submit.

```
GET  /                                     세션 워밍업
POST /app/area/pk001/h01   {tabId: result, blockCls: ""}        → 売却結果照会(지역 선택)
POST /app/area/pk001/h02   {blockCls, tabId: result}            → 売却結果検索(도도부현+법원)
POST /app/peroidsearch/ps007/h02  {prefecturesId, ...}          → 그 도도부현의 법원 라디오
POST /app/peroidsearch/ps007/h04  {courtId, ...}   (AJAX 조각)   → 開札期日 목록
POST /app/peroidsearch/ps007/h08  {courtId, saleScdId, ...}     → ★ 売却結果一覧
```

특별매각은 같은 구조의 `ps008` 계열(`h02`/`h04`/`h08`).
도도부현 전체 검색은 `h03`(`searchType=1`) — 다만 아래 필드 세트가 그대로 필요하다.

### 2-1. h08 요청 본문 (브라우저 실측 그대로)

```
peroidCourtId  = 31111        ← 라디오. 이게 빠지면 500
peroidSaleCls  = 1,2,3,4      ← 체크박스 (복수)
error          =
saleScdId      = 20000014084  ← 開札期日 id (h04 에서 획득)
fiscalYear     = 000805       ← 令和8
codeCls        = 2            ← h04 가 채워줌. 빈 값이면 500
caseNo         =
saleClsList    = 1,2,3,4
courtId        = 31111
saleType       = 1            ← 1=期間入札, 2=特別売却
peroidSearchFlg=
blockCls       = 03
blockName      = 関東
prefecturesId  = 13
mapShowFlag    = 1            ← "" 이면 500
mapSelectedAreaName =
searchType     = 0            ← submitPeroidForm 이 0(통상)/1(전체) 설정
tabId          = result
```

⚠ **500 의 원인은 대부분 누락 필드다.** 특히 `peroidCourtId`·`codeCls`·`mapShowFlag`.
필드를 추측하지 말고 위 세트를 그대로 보낼 것 (정찰 때 4번 연속 500 을 맞았다).

---

## 3. 응답 — 売却結果一覧

`.bit__currentSearchCondition_regionBox` 중 `売却価額` 을 포함한 블록이 결과 1건.
東京地裁本庁 · 令和08年07月29日 개찰분 = 15건(10건씩 페이지네이션) 실측.

| 필드 | 예시 | 비고 |
|---|---|---|
| 種別 | `戸建て` | 土地/戸建て/マンション/その他 |
| 事件番号 | `令和08年(ケ)第48号` | `jp_cases.case_no` 와 동일 형식 → 조인 키 |
| **売却価額** | `28,000,000円` | **낙찰가**. 不売/取下 면 `-` |
| 売却基準価額 | `19,380,000円` | 낙찰가/기준가 비율 계산용 |
| 所在地 | `足立区西新井三丁目１番地３０` | |
| 物件番号 | `1 ，2` | 복수 물건 묶음 (전각 쉼표) |
| **開札結果** | `売却` / `不売` / `取下` | status 확정 근거 |
| 入札者数（人） | `13` | 한국엔 없는 정보 — 경쟁 강도 |
| 落札者資格 | `法人` / `個人` | |

실측 예: 令和07年(ケ)第94号 → 기준가 88,000,000 / 낙찰가 206,800,000 (**235%**), 입찰자 23명.

### 조회 가능 기간

`開札期日` 는 **최근 것만** 제공된다 — 東京地裁本庁 기준 4회분
(令和08年 06/17, 07/01, 07/15, 07/29). 즉 **과거 전체를 소급 수집할 수 없고**,
주기적으로 돌면서 새 개찰분을 쌓아야 한다. 놓치면 그 회차는 영구 손실.
→ 일일 크론에 포함하고, 법원×개찰기일 단위로 멱등 저장할 것.

---

## 4. 구현 설계 (예정)

### 4-1. 저장 스키마 `jp_sale_results`

```
court_code, case_no, property_no, open_bid_date, sale_type(period|special)  ← unique
sale_cls_label, sale_price, sale_standard_price, address_text,
result_cls(売却|不売|取下|…), bidder_count, winner_kind, raw jsonb
```

`(court_code, case_no)` 로 `jp_cases` 조인 → `jp_properties` 연결.
物件番号가 복수(`1，2`)라 매물 1:1 매칭은 사건 단위로 우선 붙이고,
번호 단위 매칭은 `jp_properties.property_seq` 와 대조.

### 4-2. status 확정

| 開札結果 | jp_properties.status |
|---|---|
| 売却 | `closed` (낙찰 확정) |
| 不売 | 유지 (재매각/특별매각 대기) |
| 取下 | `aborted` |

이게 들어오면 "목록에서 사라짐 = 종결" 추정에 의존하지 않아도 된다.

### 4-3. 수집 단위

법원(약 250개) × 개찰기일(각 4회분) = 1일 1회 순회면 충분.
법원 목록은 도도부현 선택(`ps007/h02`) 응답의 `peroidCourtId` 라디오에서 얻는다.

---

## 5. 주의

1. **요청 간격** — 기존 `BitClient` 의 throttle 을 그대로 쓴다. 정찰도 1.2초 간격으로 했다.
2. **세션 순서 의존** — h08 은 h02·h04 를 거친 세션에서만 동작한다. 쿠키 재사용 필수.
3. **500 은 대부분 필드 누락** — 위 2-1 세트를 통째로 유지할 것.
4. **소급 불가** — 조회 가능한 개찰기일이 최근 몇 회로 제한된다(3장 참조).
