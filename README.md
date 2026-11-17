# PR Review Assistant

GitHub Pull Request를 자동으로 리뷰하는 FastAPI 서비스입니다.  
웹훅으로 PR 이벤트를 받아 Redis 큐에 넣고, 워커가 LLM으로 리뷰한 뒤 PostgreSQL에 저장하고 PR에 코멘트를 남깁니다.

## 주요 기능

- GitHub 웹훅 수신 + HMAC-SHA256 서명 검증
- Redis 멱등 키로 동일 PR·커밋 중복 처리 방지
- arq 워커: diff 조회 → LLM 리뷰 → DB 저장 → GitHub 코멘트
- 리뷰 이력·코멘트 조회, 실패 재시도, 저장소별 통계 API
- Docker Compose 한 줄 기동, GitHub Actions CI

## 아키텍처

```
GitHub PR ──(webhook)──► FastAPI ──► Redis (queue + idempotency)
                              │              │
                              │              ▼
                              │         Worker (arq)
                              │           · get diff
                              │           · LLM review
                              │           · comment on PR
                              ▼              ▼
                         PostgreSQL ◄── 조회 / 통계 API
```

자세한 설명은 [docs/architecture.md](docs/architecture.md)를 보세요.

## 기술 스택

- Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic
- Redis + arq, PostgreSQL 16
- httpx (GitHub / LLM), pydantic-settings
- Docker Compose, GitHub Actions (ruff, pytest, docker build)

## 로컬 실행

### 1. 환경 변수

```bash
cp .env.example .env
# 최소: GITHUB_WEBHOOK_SECRET
# 로컬/CI는 LLM_MOCK=true 권장
```

### 2. 스택 기동

```bash
docker compose up --build
```

- API: http://localhost:8000  
- Health: `GET /health` → `{"status":"ok"}`  
- OpenAPI: http://localhost:8000/docs  

마이그레이션(`alembic upgrade head`)은 api 컨테이너가 시작할 때 자동으로 적용되며, worker는 api가 healthy가 된 뒤에 뜹니다.

### 3. 웹훅 테스트

ngrok/smee로 `POST /webhooks/github` 를 공개 URL에 연결하거나, 픽스처 + HMAC 헤더로 직접 호출합니다.  
서명 생성 예시는 `tests/test_webhooks.py`를 참고하세요.

### 4. 주요 API

| Method | Path | 설명 |
|--------|------|------|
| POST | `/webhooks/github` | PR 웹훅 |
| GET | `/repositories` | 저장소 목록 |
| GET | `/repositories/{id}/reviews?status=&page=` | 리뷰 이력 |
| GET | `/reviews/{id}` | 리뷰 상세 + 코멘트 |
| POST | `/reviews/{id}/retry` | failed 재시도 |
| GET | `/stats/summary` | 집계 |

## 데모 시나리오 (E2E)

1. `docker compose up --build` 후 `/health` 확인 (마이그레이션 자동 적용)  
2. 서명된 PR opened 픽스처를 `POST /webhooks/github` — 응답 `queued`  
3. 동일 페이로드 재전송 — 응답 `duplicate_ignored`  
4. 워커 로그에서 review `running` → `done` (mock LLM)  
5. `GET /repositories`, `GET /reviews/{id}`, `GET /stats/summary` 로 결과 확인  
6. (선택) 실패 시 워커가 최대 3회 자동 재시도(10s, 20s 백오프, 같은 review 행 재사용) 후 `failed` 기록 → `POST /reviews/{id}/retry`로 같은 리뷰를 다시 `queued`

LLM·GitHub 실연동 시 `.env`에 `LLM_MOCK=false`, API 키, `GITHUB_TOKEN`을 설정합니다.

## 개발

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check app tests
```

CI: [`.github/workflows/ci.yml`](.github/workflows/ci.yml)

## 완료 체크리스트

- [x] `docker compose up` 한 줄로 전체 스택 실행 (마이그레이션 자동)
- [x] 웹훅 서명 검증과 중복 방지 테스트 통과
- [x] LLM 호출 실패 시 재시도와 `failed` 상태 기록
- [x] pytest로 핵심 로직 검증 (LLM 모킹)
- [ ] GitHub Actions에서 lint, test, docker build 통과 (로컬 ruff·pytest는 통과, 원격 CI 미실행)
- [ ] README에 아키텍처 다이어그램, 실행 방법, 데모 GIF 포함 (데모 GIF 없음)
- [ ] 이슈 → 브랜치 → PR → 머지 기록 15개 이상
- [ ] AI 도구 활용 기록 (`docs/ai-workflow.md`): 실제 경험 기반으로 보강 필요

## AI 활용 기록

[docs/ai-workflow.md](docs/ai-workflow.md)

## 프로젝트 구조

```text
app/
  api/          webhooks, reviews, repositories, stats
  core/         config, security, logging
  db/           models, session
  services/     github_client, llm_reviewer
  worker/       arq settings & tasks
  main.py
alembic/
tests/
docs/
docker-compose.yml
Dockerfile
pyproject.toml
```

## 라이선스

MIT
