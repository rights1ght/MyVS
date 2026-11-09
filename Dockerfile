FROM node:22-bookworm-slim AS web
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MYVS_DATA_DIR=/app/data \
    HF_HOME=/app/data/models/hf-cache
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt
COPY backend ./backend
COPY run.py README.md ./
COPY --from=web /build/frontend/dist ./frontend/dist
RUN mkdir -p data/models data/voices data/outputs data/uploads data/tmp data/logs
EXPOSE 8000
CMD ["python", "run.py", "--no-browser", "--skip-install", "--host", "0.0.0.0", "--port", "8000"]
