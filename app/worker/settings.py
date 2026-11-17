from typing import Any

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.worker.tasks import MAX_TRIES, run_review

settings = get_settings()


async def startup(ctx: dict[str, Any]) -> None:
    setup_logging()


class WorkerSettings:
    """arq worker settings — referenced by docker-compose command."""

    functions = [run_review]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 5
    max_tries = MAX_TRIES
    job_timeout = 600  # seconds
    keep_result = 3600
