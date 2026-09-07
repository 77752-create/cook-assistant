FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    CLOUD_MODE=1 \
    COOK_PORT=8765 \
    COOK_DB=/data/recipes.db

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME /data
EXPOSE 8765

CMD ["gunicorn", "-b", "0.0.0.0:8765", "--workers", "1", "--threads", "8", "--timeout", "300", "app:app"]
