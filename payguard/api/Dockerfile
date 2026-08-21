FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY payguard/ payguard/
COPY alembic/ alembic/
COPY alembic.ini .
COPY config/ config/

RUN pip install --no-cache-dir -e .

EXPOSE 8000
CMD ["uvicorn", "payguard.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
