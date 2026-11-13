FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

RUN useradd -r -m -u 1001 appuser \
    && mkdir -p /opt/src \
    && chown -R appuser /opt/src /app
USER appuser

EXPOSE 8000

# OBSERVAÇÃO: Garanta que você criou uma rota chamando '/health' no seu app/main.py 
# para o Healthcheck abaixo funcionar e não dar erro depois.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
