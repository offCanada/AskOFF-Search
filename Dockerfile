FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY backend backend
COPY data data

WORKDIR /app/backend

RUN useradd --create-home --uid 10001 askoff \
    && chown -R askoff:askoff /app
USER askoff

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
