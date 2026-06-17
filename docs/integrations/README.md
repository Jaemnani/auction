# 외부 연동 가이드 (재사용 템플릿)

이 디렉토리는 프로젝트가 의존하는 **외부 연동(External Integration)**을 카테고리별로 정리한
문서다. 특정 도메인(이 프로젝트의 경우 경매)에 종속되지 않는 **재사용 가능한 패턴** 위주로
기술했다 — 다른 프로젝트에 그대로 복사해 환경변수·엔드포인트만 갈아끼우면 된다.

## 카테고리

| # | 문서 | 다루는 연동 | 인증/접속 |
|---|---|---|---|
| 1 | [01-data-sources.md](01-data-sources.md) | 외부 사이트 데이터 수집(크롤/스크래핑) | 키없음(세션·헤더) |
| 2 | [02-backend.md](02-backend.md) | DB(PostgREST/Supabase) + 오브젝트 스토리지(MinIO) | API 키 / S3 키 |
| 3 | [03-enrichment-apis.md](03-enrichment-apis.md) | 보강 API — 지오코딩 / 공공 OpenAPI / LLM | API 키 |
| 4 | [04-maps.md](04-maps.md) | 지도 타일 + 외부 지도 딥링크 | 키없음 |
| 5 | [05-ops-notifications.md](05-ops-notifications.md) | 운영 알림 (Discord Webhook) | Webhook URL |
| 6 | [06-infra-deployment.md](06-infra-deployment.md) | 인프라/배포 (Tunnel·역프록시·호스팅) | — |

## 공통 원칙

- **시크릿은 코드에 두지 않는다.** 모든 키/토큰은 환경변수(`.env`, 호스팅 플랫폼 env)로 주입.
  `.env`는 gitignore. 머신마다 직접 설정.
- **서버 전용 키와 공개 키를 분리한다.** 브라우저로 내려가면 안 되는 키(`*_SECRET`,
  `SERVICE_KEY`, OpenAPI 키)는 서버 라우트/백엔드에서만 사용. 프론트 노출용은 `NEXT_PUBLIC_`(또는
  동등) 접두사만.
- **미설정 시 graceful degrade.** 선택적 연동(알림·LLM 등)은 env 없으면 조용히 no-op 하도록.
- **실패 격리.** 외부 호출 실패가 본 작업을 죽이지 않게 — 타임아웃·재시도·`try/except` 또는 `|| true`.

## 연동 추가 체크리스트

1. 어느 카테고리인가 → 해당 문서에 1개 섹션 추가.
2. 환경변수 이름 정하고(`SCREAMING_SNAKE_CASE`, 서비스 접두사) `.env.example`/배포 문서에 기록.
3. 서버 전용인지 공개 가능인지 분류.
4. 타임아웃·재시도·실패 처리 명시.
5. 무료 할당량/요금/레이트리밋 확인해 문서화.
