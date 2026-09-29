FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 TZ=Asia/Shanghai

# ffmpeg + chromium 运行库 (patchright/playwright 用于 sau 发布)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git curl ca-certificates \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libasound2 libpangocairo-1.0-0 libxss1 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# social-auto-upload (发布模块)
COPY services/social-auto-upload /opt/sau
RUN pip install --no-cache-dir /opt/sau && patchright install chromium

COPY . .

EXPOSE 8800
VOLUME ["/app/outputs", "/app/assets", "/app/data", "/opt/sau/cookies"]

CMD ["sh", "-c", "uvicorn orchestrator.app.main:app --host 0.0.0.0 --port ${ORCH_PORT:-8800}"]
