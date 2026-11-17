# AI 개발 도구 활용 기록

## 사용 도구와 역할

- **Claude / Grok**: 설계 검토, 스키마·API 초안, 테스트 케이스 아이디어
- **Cursor / Copilot**: 보일러플레이트, 반복 코드, 리팩터링 제안

## 사례

### 사례 1. SQLAlchemy 2.0 모델·마이그레이션

- **문제**: 계획서 SQL을 2.0 `Mapped` 스타일과 Alembic async env로 옮기기
- **프롬프트(핵심)**: “다음 스키마를 SQLAlchemy 2.0 DeclarativeBase + Mapped로, UNIQUE/CHECK/Index 포함해 작성해줘”
- **채택**: 관계·CHECK·인덱스 구조
- **수정**: `ondelete="CASCADE"` 명시, async `env.py`의 `run_sync` 패턴
- **버린 것**: 과도한 mixin / soft-delete
- **검증**: 마이그레이션 upgrade 후 테이블·제약 확인
- **배운 점**: 모델이 source of truth일 때 autogenerate보다 수동 초안이 안전한 경우가 많다

### 사례 2. 웹훅 멱등성

- **문제**: 동일 PR+SHA 재전송 시 중복 리뷰 방지
- **프롬프트**: “Redis SET NX로 멱등 키 설계, FastAPI에서 중복 시 200 + status 반환”
- **채택**: `review:{repo_id}:{pr}:{sha}`, TTL 1h
- **수정**: 키에 `full_name` 대신 numeric id 사용 (안정성)
- **버린 것**: DB unique만으로 처리 (레이스 구간이 남음)
- **검증**: 픽스처로 두 번 POST → 두 번째는 `duplicate_ignored`
- **배운 점**: 웹훅은 at-least-once이므로 큐 앞단 멱등이 필수

### 사례 3. LLM 응답 스키마

- **문제**: 모델이 마크다운/여담을 섞어 JSON 파싱이 깨짐
- **프롬프트**: “JSON only, response_format json_object, severity enum 고정”
- **채택**: system prompt + `response_format`, fence strip 방어 코드
- **수정**: mock 모드 기본 ON으로 로컬/CI 비용·비결정성 제거
- **버린 것**: 자유 형식 prose 파싱
- **검증**: mock 단위 테스트 + 실키 수동 스모크
- **배운 점**: 스키마를 강제하고 실패 시 failed 상태로 남기는 편이 운영에 유리

### 사례 4. 워커 트랜잭션 경계

- **문제**: 긴 HTTP(diff/LLM/GitHub)를 DB 트랜잭션 안에 두면 커넥션 점유
- **프롬프트**: “running 기록 후 커밋 → 외부 호출 → 결과 저장 커밋, 실패 시 failed 갱신”
- **채택**: 두 단계 세션, 예외 시 arq `Retry`로 최대 3회 재시도(같은 review 행 재사용), 마지막 시도에서 failed 기록
- **바로잡은 것**: 초안은 일반 예외를 re-raise하면 arq가 재시도한다고 가정했지만, arq는 `Retry` 예외만 재시도한다. 또 재시도 API가 새 review 행을 만들어 원래 행이 `queued`로 남는 버그가 있어 `review_id`를 넘겨 재사용하도록 고쳤다
- **수정**: GitHub 코멘트 실패는 warning만 남기고 done 유지 (리뷰 데이터는 이미 저장)
- **버린 것**: 단일 거대 트랜잭션
- **검증**: mock으로 github down → status=failed 테스트
- **배운 점**: “상태 머신 + 짧은 트랜잭션”이 워커 안정성의 핵심

### 사례 5. CI에서 Docker build 분리

- **문제**: lint/test와 image build를 한 job에 넣으면 캐시·실패 원인이 섞임
- **프롬프트**: “GitHub Actions에서 ruff/pytest job과 docker build job 분리”
- **채택**: 두 job, Buildx + GHA cache
- **수정**: mypy는 초기엔 `continue-on-error` (점진 강화)
- **버린 것**: 매 PR마다 registry push
- **검증**: 워크플로 파일 리뷰 + 로컬 `docker build`
- **배운 점**: 빌드 검증은 배포 전에 이미지 재현성을 보장한다

## 하지 않은 것 (AI에 맡기지 않은 판단)

- 최종 스키마 UNIQUE 키 선택 (repo+number+sha)
- 웹훅 시크릿·토큰을 코드에 넣지 않을 것
- 프로덕션 배포 대상 환경(VPS vs PaaS) 결정
- 비용 상한(파일/라인 수 truncate)의 수치
