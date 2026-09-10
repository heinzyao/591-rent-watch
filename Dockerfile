FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY rent591.py commands.py store.py notify.py main.py ./

ENV PATH="/app/.venv/bin:$PATH"
# Cloud Run 以 $PORT 指定監聽埠；webhook 會同步抓 3 頁，逾時設 120 秒
CMD exec gunicorn --bind :$PORT --workers 1 --threads 4 --timeout 120 main:app
