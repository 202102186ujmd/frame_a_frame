FROM python:3.11-slim

# System deps: Chromium via Playwright + Xvfb for display
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb \
        libglib2.0-0 \
        libnss3 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libdbus-1-3 \
        libexpat1 \
        libxcb1 \
        libxkbcommon0 \
        libx11-6 \
        libxcomposite1 \
        libxdamage1 \
        libxext6 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libpango-1.0-0 \
        libcairo2 \
        libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium \
    && playwright install-deps chromium

COPY . .

ENV DISPLAY=:99
ENV HTTP_HOST=0.0.0.0
ENV HTTP_PORT=8080

# Healthcheck: service must respond on /health
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

EXPOSE 8080

# Start Xvfb then the service
CMD Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render -noreset & \
    sleep 1 && \
    python main.py
