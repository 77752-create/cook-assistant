FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    CLOUD_MODE=1 \
    COOK_DB=/data/recipes.db

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME /data
EXPOSE 8765

CMD ["sh", "-c", "export COOK_PORT=${PORT:-8765}; exec gunicorn -b 0.0.0.0:${COOK_PORT} --workers 1 --threads 8 --timeout 300 app:app"]
