# Architecture

## Overview

PR Review Assistant receives GitHub `pull_request` webhooks, enqueues review jobs on Redis (arq), and has a worker that:

1. Fetches the PR unified diff via the GitHub API  
2. Asks an LLM (or mock) for a summary + line comments  
3. Persists results in PostgreSQL  
4. Posts a review/comment back to the PR  

Query APIs expose repositories, review history, and aggregate stats.

```
GitHub PR event
      │  HMAC-SHA256 signature
      ▼
FastAPI  ──► Redis (idempotency key + arq queue)
      │              │
      │              ▼
      │         Worker (arq)
      │           1. get diff
      │           2. LLM review
      │           3. comment on PR
      ▼              ▼
   PostgreSQL (repositories, pull_requests, reviews, review_comments)
      ▲
      └── REST: list repos, reviews, stats, retry
```

## Components

| Component | Role |
|-----------|------|
| `app/api/webhooks.py` | Signature check, event filter, Redis SET NX, enqueue |
| `app/worker/tasks.py` | Full review pipeline, status transitions |
| `app/services/github_client.py` | Diff + comment/review HTTP client |
| `app/services/llm_reviewer.py` | Prompt + OpenAI-compatible call / mock |
| `app/api/reviews.py` | Detail + retry |
| `app/api/repositories.py` | Repo list + paginated review history |
| `app/api/stats.py` | Aggregations |

## Data model

- **repositories** — one row per GitHub repo (`github_repo_id` unique)  
- **pull_requests** — unique on `(repository_id, number, head_sha)`  
- **reviews** — status `queued|running|done|failed`, token counts, error  
- **review_comments** — file/line/severity/body, cascade delete  

## Idempotency

Key: `review:{github_repo_id}:{pr_number}:{head_sha}`  
`SET key 1 NX EX 3600` — duplicates return `duplicate_ignored` without enqueueing.

## Failure & retry

Worker catches exceptions, writes `status=failed` + `error`, re-raises for arq retries.  
`POST /reviews/{id}/retry` only accepts `failed` and re-enqueues with `status=queued`.
