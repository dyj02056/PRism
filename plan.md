# PR Review Assistant 프로젝트 계획

> GitHub PR을 자동으로 리뷰하는 FastAPI 서비스. 채용 공고의 기술 스택과 AI 활용 개발 경험을 한 프로젝트로 증명하는 포트폴리오.

## 0. 목표와 전제

- **목표:** 공고의 자격·우대 요건(Python/FastAPI, PostgreSQL, Redis, Docker, Linux, Git 협업, AI 개발 도구 활용·자동화)을 한 프로젝트로 증명한다.
- **가정(변경 가능):** 1인 개발, 4주, 평일 저녁과 주말 투자, LLM API 비용 최소화.

## 1. 한 줄 결론

GitHub PR이 열리면 웹훅으로 받아 Redis 큐에 넣고, 워커가 LLM으로 리뷰한 뒤 PostgreSQL에 저장하고 PR에 코멘트를 남기는 **AI 코드 리뷰 자동화 서비스**를 만든다.

## 2. 이 주제를 선택한 이유

- "AI를 활용한 개발 프로세스 개선·자동화 경험" 항목을 제품 자체로 증명한다.
- 웹훅 수신, 비동기 큐, 관계형 저장, 조회 API가 모두 들어가 FastAPI, PostgreSQL, Redis, Docker, Linux를 자연스럽게 다룬다.
- "왜 큐를 썼나?", "중복 웹훅은 어떻게 처리했나?" 같은 설계 질문에 답할 거리가 생긴다.

### 요건별 매핑

| 공고 요건 | 프로젝트에서 증명하는 방법 |
|---|---|
| Python, FastAPI | 웹훅·조회 API 서버, 비동기 처리 |
| RESTful API 이해 | 리소스 중심 설계, OpenAPI 문서 자동 생성 |
| SQL, 관계형 DB | PostgreSQL 스키마 설계, 인덱스, 통계 집계 쿼리 |
| Redis | 작업 큐, 웹훅 중복 방지(멱등성 키), 간단한 캐시 |
| Docker, Linux | docker-compose로 전체 스택 구성, Linux 서버(VPS 또는 WSL)에 배포 |
| Git 협업 | 브랜치 전략, PR 템플릿, 이슈 기반 작업, GitHub Actions CI |
| AI 도구 활용 | 개발 과정에서 Claude/Cursor/Copilot 사용, `docs/ai-workflow.md`에 기록 |
| AI 기반 자동화 | 서비스 자체가 PR 리뷰 자동화 |

## 3. 아키텍처

```
GitHub PR 이벤트
      │ (Webhook, HMAC 서명 검증)
      ▼
[FastAPI] ──► Redis (큐 + 중복 방지 키)
      │                 │
      │                 ▼
      │          [Worker (arq 또는 RQ)]
      │                 │  1) diff 가져오기
      │                 │  2) LLM 리뷰 생성
      │                 │  3) GitHub에 코멘트 작성
      ▼                 ▼
        PostgreSQL (repositories, pull_requests, reviews, review_comments)
      ▲
      └── 조회 API: 리뷰 이력, 저장소별 통계
```

**기술 선택:** FastAPI + SQLAlchemy 2.0 + Alembic. 큐는 asyncio 네이티브인 `arq`를 추천하고, 단순함을 우선하면 RQ도 가능하다.

## 4. 4주 단계별 계획

| 주차 | 할 일 | 목적 | 리스크와 대응 |
|---|---|---|---|
| **1주** 기반 | 레포 생성, 브랜치 규칙·PR 템플릿, docker-compose(api, postgres, redis), Alembic 초기 마이그레이션, `/health` | 협업 가능한 뼈대와 재현 가능한 환경 | 환경 이슈가 길어질 수 있다. 첫 이틀 안에 `docker compose up` 한 번으로 뜨게 만든다. |
| **2주** 수신·큐 | GitHub App 또는 웹훅 연동, HMAC 검증, Redis 멱등성 키, 큐 적재, 워커 골격 | 외부 이벤트를 안전하게 받는 구조 | 웹훅 테스트가 번거롭다. 로컬은 ngrok 또는 smee.io, 테스트는 저장된 페이로드 픽스처 사용. |
| **3주** AI 리뷰 | diff 조회, 프롬프트 설계, LLM 호출, 결과 저장 및 PR 코멘트 게시, 실패 시 재시도 | 핵심 가치 구현 | API 비용과 대용량 diff. 파일 수·라인 수 상한, 모킹 모드, 토큰 사용량 기록으로 대응. |
| **4주** 마감 | 조회·통계 API, pytest, GitHub Actions(lint + test + docker build), 배포, README·다이어그램, 데모 GIF | 완성도와 설명 가능성 | 기능 욕심 금지. 4주차에는 기능 추가 없이 문서와 테스트에 집중. |

## 5. 결과물 템플릿

### 5-1. 폴더 구조

```
pr-review-assistant/
├── app/
│   ├── api/            # 라우터 (webhooks.py, reviews.py, stats.py)
│   ├── core/           # config.py, security.py(HMAC), logging.py
│   ├── db/             # session.py, models.py
│   ├── services/       # github_client.py, llm_reviewer.py
│   ├── worker/         # tasks.py, settings.py
│   └── main.py
├── alembic/
├── tests/
├── docs/
│   ├── architecture.md
│   └── ai-workflow.md  # AI 도구 활용 기록 (핵심 차별점)
├── .github/
│   ├── workflows/ci.yml
│   └── pull_request_template.md
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── README.md
```

### 5-2. docker-compose.yml (초안)

```yaml
services:
  api:
    build: .
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    env_file: .env
    ports: ["8000:8000"]
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_started }
  worker:
    build: .
    command: arq app.worker.settings.WorkerSettings
    env_file: .env
    depends_on: [db, redis]
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
      POSTGRES_DB: review
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d review"]
      interval: 5s
      retries: 10
  redis:
    image: redis:7
volumes:
  pgdata:
```

### 5-3. 핵심 테이블 (SQL 초안)

```sql
CREATE TABLE repositories (
  id BIGSERIAL PRIMARY KEY,
  github_repo_id BIGINT UNIQUE NOT NULL,
  full_name TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE pull_requests (
  id BIGSERIAL PRIMARY KEY,
  repository_id BIGINT REFERENCES repositories(id),
  number INT NOT NULL,
  title TEXT,
  head_sha TEXT NOT NULL,
  UNIQUE (repository_id, number, head_sha)
);

CREATE TABLE reviews (
  id BIGSERIAL PRIMARY KEY,
  pull_request_id BIGINT REFERENCES pull_requests(id),
  status TEXT NOT NULL CHECK (status IN ('queued','running','done','failed')),
  summary TEXT,
  model TEXT,
  input_tokens INT,
  output_tokens INT,
  error TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  finished_at TIMESTAMPTZ
);
CREATE INDEX idx_reviews_pr_status ON reviews(pull_request_id, status);

CREATE TABLE review_comments (
  id BIGSERIAL PRIMARY KEY,
  review_id BIGINT REFERENCES reviews(id) ON DELETE CASCADE,
  file_path TEXT,
  line INT,
  severity TEXT,   -- info | warning | critical
  body TEXT NOT NULL
);
```

### 5-4. API 목록

| Method | Path | 설명 |
|---|---|---|
| POST | `/webhooks/github` | PR 이벤트 수신 (서명 검증, 멱등 처리) |
| GET | `/repositories` | 연동된 저장소 목록 |
| GET | `/repositories/{id}/reviews?status=&page=` | 리뷰 이력 (페이지네이션) |
| GET | `/reviews/{id}` | 리뷰 상세와 코멘트 |
| POST | `/reviews/{id}/retry` | 실패한 리뷰 재시도 |
| GET | `/stats/summary` | 저장소별 리뷰 수, 심각도 분포, 토큰 사용량 |

### 5-5. 웹훅 멱등성 처리 (스케치)

```python
# 같은 PR + 같은 커밋(head_sha)이면 한 번만 처리
key = f"review:{repo_id}:{pr_number}:{head_sha}"
if not await redis.set(key, "1", nx=True, ex=3600):
    return {"status": "duplicate_ignored"}
await queue.enqueue_job("run_review", repo_id, pr_number, head_sha)
```

### 5-6. `docs/ai-workflow.md` 템플릿

```markdown
# AI 개발 도구 활용 기록

## 사용 도구와 역할
- Claude: 설계 검토, 테스트 케이스 생성
- Cursor/Copilot: 보일러플레이트, 리팩터링

## 사례 (최소 5개 작성)
### 사례 1. [작업명]
- 문제:
- 프롬프트(핵심):
- AI 결과 중 채택한 것 / 수정한 것 / 버린 것:
- 검증 방법(테스트, 리뷰):
- 배운 점:

## 하지 않은 것 (AI에 맡기지 않은 판단)
- 예: 스키마 설계의 최종 결정, 보안 관련 코드 검증
```

## 6. 완료 체크리스트

- [ ] `docker compose up` 한 줄로 전체 스택 실행
- [ ] 웹훅 서명 검증과 중복 방지 테스트 통과
- [ ] LLM 호출 실패 시 재시도와 `failed` 상태 기록
- [ ] pytest로 핵심 로직 검증 (LLM은 모킹)
- [ ] GitHub Actions에서 lint, test, docker build 통과
- [ ] README에 아키텍처 다이어그램, 실행 방법, 데모 GIF 포함
- [ ] 이슈 → 브랜치 → PR → 머지 기록 15개 이상

## 7. 이력서·면접용 한 줄

> GitHub PR을 자동 리뷰하는 FastAPI 서비스를 설계·구현했습니다. Redis 기반 비동기 큐와 멱등성 처리로 웹훅 중복을 방지했고, PostgreSQL에 리뷰 이력·토큰 사용량을 적재했으며, Docker로 배포하고 CI를 구성했습니다. 개발 전 과정에서 AI 도구 활용 방식을 문서화했습니다.

## 8. 즉시 실행할 일

1. GitHub 레포 생성 후 `main` 보호 규칙, PR 템플릿, 이슈 라벨 설정 (30분)
2. 위 `docker-compose.yml`로 api, db, redis를 띄우고 `/health` 응답 확인 (1주차 첫 목표)
3. 1주차 이슈 5~7개 생성: 컨테이너 구성, 설정 관리, DB 모델, 마이그레이션, CI 골격

## 9. 다음 단계 후보

- 1주차 이슈 목록과 브랜치 전략 상세
- FastAPI 프로젝트 초기 코드 (main.py, config, DB 세션, 첫 마이그레이션)
- 주제 변경 대안 (사내 문서 Q&A, 업무 자동화 봇 등)
