# auction 자체호스팅 (Synology DS918+)

Supabase 클라우드 → **Postgres + PostgREST + MinIO** 자체호스팅 배포 가이드.
한 줄씩 복붙 실행. 모든 명령은 시놀로지 SSH 또는 Container Manager 기준.

> 사전: DSM 7.2 · Container Manager 설치 · SSH 활성화 · Cloudflare에 연결된 도메인.

---

## 1. 파일 올리기

repo를 시놀로지 `/volume1/docker/auction` 에 통째로 둔다 (git clone 또는 File Station 업로드).
`deploy/synology/` 가 작업 디렉토리.

```bash
ssh <user>@<NAS_IP>
cd /volume1/docker/auction/deploy/synology
```

## 2. .env 생성 + 비밀번호 채우기

```bash
cp .env.example .env

# 비밀번호 자동 생성해서 출력 (복사해 .env 에 붙이기)
echo "POSTGRES_PASSWORD=$(openssl rand -base64 24)"
echo "AUTHENTICATOR_PASSWORD=$(openssl rand -base64 24)"
echo "JWT_SECRET=$(openssl rand -base64 48)"
echo "MINIO_ROOT_USER=auctionadmin"
echo "MINIO_ROOT_PASSWORD=$(openssl rand -hex 16)"
echo "PGADMIN_PASSWORD=$(openssl rand -hex 12)"

vi .env   # 위 값 붙여넣기
```

## 3. bootstrap 역할 비밀번호 동기화

`bootstrap/00_roles.sql` 의 `CHANGE_ME_SAME_AS_ENV` 를 `.env` 의 `AUTHENTICATOR_PASSWORD` 와 동일하게:

```bash
AUTH_PW=$(grep '^AUTHENTICATOR_PASSWORD=' .env | cut -d= -f2-)
sed -i "s|CHANGE_ME_SAME_AS_ENV|${AUTH_PW}|" bootstrap/00_roles.sql
grep "password" bootstrap/00_roles.sql   # 치환 확인
```

> ⚠️ 이 sed 는 1회만. 다시 실행하면 패턴이 없어 무효 (안전).

## 4. 컨테이너 기동

```bash
sudo docker compose up -d
sudo docker compose ps          # db/rest/storage/proxy 가 healthy/running
sudo docker compose logs -f db  # "database system is ready" 확인 후 Ctrl-C
```

bootstrap/00_roles.sql 은 **DB 최초 생성 시 자동 실행**. 확인:

```bash
sudo docker exec -i auction-db psql -U postgres -c "\du"  # anon/authenticated/service_role/authenticator 보임
```

## 5. 마이그레이션 적용

```bash
sudo bash apply-migrations.sh
# postgis/pg_trgm 확장 + 0001~0013 (0003/0010 storage 는 자동 SKIP)
sudo docker exec -i auction-db psql -U postgres -c "\dt"   # 테이블 목록 확인
```

## 6. MinIO 버킷 + 공개 정책

MinIO 콘솔 `http://<NAS_IP>:9001` (로그인: MINIO_ROOT_USER / PASSWORD) 또는 mc CLI:

```bash
# mc 컨테이너로 1회 실행
sudo docker run --rm --network synology_internal \
  -e MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@auction-minio:9000" \
  minio/mc sh -c "
    mc mb -p local/auction-photos local/jp-auction-photos &&
    mc anonymous set download local/auction-photos &&
    mc anonymous set download local/jp-auction-photos
  "
```

> `--network` 이름은 `sudo docker network ls | grep auction` 로 확인 (보통 `synology_internal` 또는 `auction_internal`).
> 콘솔 UI로 할 경우: 버킷 2개 생성 → 각 버킷 Access Policy = **public (download)**.

## 7. anon / service 키 발급

```bash
JWT=$(grep '^JWT_SECRET=' .env | cut -d= -f2-)
node gen-anon-key.mjs "$JWT"
# (node 없으면: sudo docker run --rm -v "$PWD":/w -w /w node:20 node gen-anon-key.mjs "$JWT")
```

출력된 `ANON_KEY` 는 web/crawler 의 `SUPABASE_KEY`, `SERVICE_KEY` 는 크롤러 적재용(선택).

## 8. Cloudflare Tunnel

Cloudflare Zero Trust → Networks → Tunnels → Create. cloudflared 를 시놀로지 컨테이너로 추가하거나 DSM에 설치. ingress 규칙:

| Public hostname | Service |
|---|---|
| `api.<domain>` | `http://auction-proxy:80` (또는 `http://<NAS_IP>:8080`) |
| `files.<domain>` | `http://auction-minio:9000` (또는 `http://<NAS_IP>:9000`) |

> cloudflared 를 같은 compose network 에 두면 컨테이너 이름으로, 아니면 `<NAS_IP>:포트` 로.

## 9. 검증

```bash
# 내부 — PostgREST anon read
ANON="<7번 ANON_KEY>"
curl -H "Authorization: Bearer $ANON" "http://<NAS_IP>:8080/rest/v1/courts?select=code,name&limit=3"

# 외부 — Tunnel
curl -H "Authorization: Bearer $ANON" "https://api.<domain>/rest/v1/courts?select=code,name&limit=3"
```

빈 배열 `[]` 이 정상 (아직 데이터 없음). 401/404 면 README 7·8 재확인.

## 10. 크롤러 / 웹 환경변수

### iMac 크롤러 — `/Users/.../auction/.env` (LAN 내부 IP 직접)
```dotenv
SUPABASE_URL=http://<NAS_IP>:8080
SUPABASE_KEY=<ANON_KEY>
SUPABASE_SERVICE_KEY=<SERVICE_KEY>     # 적재용
MINIO_ENDPOINT=http://<NAS_IP>:9000
MINIO_ACCESS_KEY=<MINIO_ROOT_USER>
MINIO_SECRET_KEY=<MINIO_ROOT_PASSWORD>
STORAGE_PUBLIC_URL=https://files.<domain>
# 기존 키 유지: DATA_GO_KR_API_KEY / KAKAO_REST_API_KEY / GEMINI_API_KEY
```
> 공용 venv 에 boto3 필요: `pip install boto3` (이미 설치됨).

### Vercel — 환경변수 (외부 Tunnel)
```
SUPABASE_URL=https://api.<domain>
SUPABASE_KEY=<ANON_KEY>
STORAGE_PUBLIC_URL=https://files.<domain>
DATA_GO_KR_API_KEY=<기존>
```

## 11. 데이터 재적재 (iMac)

```bash
cd /Users/<user>/workspace/auction
git pull
./crawler/run_daily.sh      # 한국 ~6h
./crawler/run_jp_daily.sh   # 일본 ~30min
```

검증 후 cron 이미 등록돼 있으면 자동 지속.

## 12. 백업

```bash
# pg_dump (cron 권장)
sudo docker exec auction-db pg_dump -U postgres -Fc postgres \
  > /volume1/backups/auction_$(date +%F).dump
```
MinIO `volumes/storage/` 는 Hyper Backup 대상에 포함.

---

## 트러블슈팅

| 증상 | 확인 |
|---|---|
| PostgREST 401 | ANON_KEY 가 JWT_SECRET 로 서명됐는지. `.env` JWT_SECRET 과 gen-anon-key 입력 일치 |
| PostgREST 404 (테이블) | 마이그레이션 적용됐는지 `\dt`. `NOTIFY pgrst,'reload schema'` |
| anon read 빈값/권한오류 | 0002 RLS 정책 + 00_roles grant 적용됐는지 |
| 이미지 403 | MinIO 버킷 `anonymous set download` 됐는지 |
| 크롤러 write 실패 | SUPABASE_SERVICE_KEY (또는 postgres) 권한. MINIO_* 키 |
