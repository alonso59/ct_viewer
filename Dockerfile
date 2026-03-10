FROM node:20-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_ROOT=/data

WORKDIR /app

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

RUN addgroup --system app && adduser --system --ingroup app app

COPY --chown=app:app backend /app/backend
COPY --chown=app:app --from=frontend-build /build/frontend/dist /app/static

EXPOSE 8000

WORKDIR /app/backend
HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status==200 else 1)"
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
