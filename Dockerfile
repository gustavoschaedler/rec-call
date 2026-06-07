FROM python:3.12-slim

# uv binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
    libportaudio2 \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Install deps + project (editable). Static assets live under backend/app.
COPY pyproject.toml uv.lock .python-version ./
COPY backend ./backend
RUN uv sync --frozen --no-dev

RUN mkdir -p /app/recordings

ENV RECCALL_RECORDINGS_DIR=/app/recordings
EXPOSE 5055
CMD ["uv", "run", "--frozen", "--no-dev", "reccall"]
