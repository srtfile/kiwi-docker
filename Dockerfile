# Kiwi Stream API — Docker Image
# Uses FlareSolverr (separate container) for Cloudflare bypass
# The /e/ endpoint has no CF, so only /f/ needs FlareSolverr

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY extractor.py .
COPY api.py .

EXPOSE 8000

ENV FLARESOLVERR_URL=http://flaresolverr:8191/v1

CMD ["python", "api.py"]
