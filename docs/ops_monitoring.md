# 운영 모니터링 SQL — cron 갱신 동작 검증

iMac 등 항상-켜진 머신에서 cron이 한국·일본 매물을 정상 갱신하고 있는지를 Supabase SQL Editor에서 확인하는 쿼리 모음. 한국과 일본 모두 같은 `crawl_runs` / `dead_letters` 테이블을 공유 (일본은 `job_type` 이 `jp_*` 로 시작).

> 일본 추적은 [jp_ingest.py 가 main()에서 wrapping](../crawler/scripts/jp_ingest.py) 하는 방식으로 PR `feat(jp): crawl_runs tracking` 이후 가능합니다. 그 이전 실행은 `jp_properties.updated_at` MAX 로 간접 확인 (마지막 쿼리).

## 1. 어제 갱신 현황 (한국 + 일본)

```sql
select
  job_type,
  count(*)                                          as runs,
  count(*) filter (where status = 'done')           as ok,
  count(*) filter (where status = 'failed')         as failed,
  count(*) filter (where status = 'running')        as still_running,
  sum((totals->>'rows')::int)                       as total_rows,
  min(started_at)                                   as first_started,
  max(coalesce(finished_at, started_at))            as last_active
from crawl_runs
where date(started_at at time zone 'Asia/Seoul') = current_date - 1
group by job_type
order by first_started;
```

→ `job_type` 별 어제 실행 횟수·성공/실패. `still_running > 0` 이면 정지된 run (수동 정리 필요).

## 2. 최근 7일 한국·일본 summary

```sql
select
  date(started_at at time zone 'Asia/Seoul')         as run_date,
  job_type like 'jp_%' as is_jp,
  count(*)                                            as runs,
  count(*) filter (where status = 'done')             as ok,
  count(*) filter (where status = 'failed')           as failed
from crawl_runs
where started_at > now() - interval '7 days'
group by run_date, is_jp
order by run_date desc, is_jp;
```

→ 매일 한국·일본 각각 정상 동작 여부 한눈에.

## 3. 최근 실패 상세

```sql
select
  job_type,
  started_at at time zone 'Asia/Seoul' as kst,
  status,
  error,
  params
from crawl_runs
where status = 'failed'
  and started_at > now() - interval '3 days'
order by started_at desc
limit 20;
```

→ 실패한 run의 에러 메시지·파라미터. 패턴 파악.

## 4. dead_letters — endpoint별 누적 실패

```sql
select
  endpoint,
  count(*)                  as cnt,
  max(occurred_at)          as latest
from dead_letters
where occurred_at > now() - interval '7 days'
  and resolved_at is null
group by endpoint
order by cnt desc
limit 20;
```

→ 특정 API endpoint가 반복 실패하면 사이트 변경 또는 IP 차단 가능성.

## 5. 일본 갱신 흔적 — crawl_runs 없는 시점에도 가능

```sql
select
  prefecture_code,
  count(*) as cnt,
  count(*) filter (where detail_result is not null) as with_detail,
  max(updated_at) at time zone 'Asia/Tokyo' as latest_jst
from jp_properties
group by prefecture_code
order by cnt desc;
```

→ 도도부현별 매물 수·detail 백필 완료 수·마지막 갱신 시각.

## 6. 데이터 audit — 차량(usage_lcl=30000) 매물 분포

Phase 1-A 의 "건물 필터에 차량 노출" 보고 검증.

```sql
-- 한국 lcl 분포
select usage_lcl_cd, count(*) as cnt
from properties
where deleted_at is null
group by usage_lcl_cd
order by cnt desc;

-- 차량 매물 (lcl=30000) 중 mcl/scl 확인
select usage_mcl_cd, usage_scl_cd, count(*) as cnt
from properties
where deleted_at is null and usage_lcl_cd = '30000'
group by usage_mcl_cd, usage_scl_cd
order by cnt desc
limit 20;

-- 의심 패턴 — usage_lcl=20000(건물)인데 mcl/scl이 차량 류
select docid, usage_lcl_cd, usage_mcl_cd, usage_scl_cd, conv_addr, building_summary
from properties
where deleted_at is null
  and usage_lcl_cd = '20000'
  and (usage_mcl_cd like '301%' or usage_mcl_cd like '311%'
       or building_summary ilike '%차량%' or building_summary ilike '%자동차%')
limit 20;
```

→ 데이터 오염 여부 확정. 만약 결과 행이 다수면 ingest 매핑 버그 또는 historical 데이터 오류.

## 7. 일본 has_pdf audit — 키 존재 여부

Phase 1-C 의 "has_pdf 필터 동작 시 오류" 검증.

```sql
-- has_three_set_pdf 키의 실제 값 분포
select
  detail_result->>'has_three_set_pdf' as has_pdf,
  count(*) as cnt
from jp_properties
where detail_result is not null
group by has_pdf
order by cnt desc;

-- detail이 있는데 has_three_set_pdf 키 자체가 없는 row
select count(*)
from jp_properties
where detail_result is not null
  and not (detail_result ? 'has_three_set_pdf');
```

→ `"true"` / `"false"` / `null` 분포. 만약 모두 NULL이면 client.py가 detail 백필 시 키를 안 채운 것 — ingest 보강.

## 권장 사용

- 매일 아침 1번 (1)·(2) 실행 → 정상 동작 확인
- 실패 발생 시 (3)·(4)
- Phase 1-A·1-C 수정 직후 (6)·(7) 1회 audit

자동 알림 (Supabase Database Webhook → Slack/email)은 후속 작업으로 분리.
