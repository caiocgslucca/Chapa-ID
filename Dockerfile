# ============================================================
# CHAPA ID - Railway
# Frontend React/Vite + Backend FastAPI
# ============================================================

# ---------- FRONTEND ----------
FROM node:22-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./

RUN npm ci

COPY frontend/ ./

RUN npm run build


# ---------- BACKEND ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt

RUN pip install --upgrade pip \
    && pip install -r /app/backend/requirements.txt

COPY backend/ /app/backend/

# Copia o React compilado exatamente para o local esperado pelo FastAPI
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

WORKDIR /app/backend

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
