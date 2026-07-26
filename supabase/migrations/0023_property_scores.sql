-- ============================================================================
-- 0023 — 매수 안전도 점수 (가격 제외, 위험성 기반 0~100)
--
-- 배경: 매물이 "사도 괜찮은가"를 가격과 분리해 채점. 가격(감정가 대비 최저가·
--       유찰 할인)은 property_estimates(0022) 모델이 별도 담당하므로 여기선 제외.
--       100 = 사도 안전, 0 에 가까울수록 위험. 규칙 기반(투명 가중 감점):
--       100 에서 risk_flags(0011) 25종을 tier(danger/warn/info)별 감점 +
--       물건유형(집합건물/건물/토지)·건물연식 보정. crawler/scripts/score.py 가 계산.
--
--       detail 미동기(risk_flags 미산출) 매물은 위험을 알 수 없으므로 신뢰도 low +
--       점수 상한(65)으로 "정보부족"을 안전으로 오인하지 않게 함.
--
-- properties 컬럼 추가 대신 별도 테이블 — hot 테이블 스키마 변경/PostgREST
-- 캐시 리스크 회피(0022 와 동일 결정), version/breakdown 관리 용이.
--
-- 적용(시놀로지): docker exec -i auction-db psql -U postgres -d postgres < 0023_*.sql
-- ============================================================================

create table if not exists property_scores (
  property_id  uuid primary key references properties(id) on delete cascade,
  score        smallint not null check (score between 0 and 100),  -- 매수 안전도
  confidence   text not null check (confidence in ('high', 'medium', 'low')),
  breakdown    jsonb,        -- 감점 내역(base·항목별 소계·top_factors) — UI 투명성
  version      text,         -- 스코어러 버전 (규칙 변경 추적)
  scored_at    timestamptz not null default now()
);

comment on column property_scores.score is
  '매수 안전도 0~100 (가격 제외). 100=안전, ↓위험. risk_flags tier 감점 + 유형/연식 보정';
comment on column property_scores.confidence is
  'high=detail+건축대장 확보 / medium=detail만 / low=detail 미동기(점수 상한 65, 정보부족)';

-- 점수순 정렬·필터용
create index if not exists property_scores_score_idx on property_scores (score desc);

alter table property_scores enable row level security;
do $$ begin
  drop policy if exists "public read" on property_scores;
  create policy "public read" on property_scores
    for select to anon, authenticated using (true);
end $$;

notify pgrst, 'reload schema';
