FROM python:3.12-slim

WORKDIR /app

# System deps for asyncpg / build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir -e .

# Migrations (run by the api service on startup)
COPY alembic.ini ./
COPY alembic ./alembic

# Default command (overridden in compose)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
