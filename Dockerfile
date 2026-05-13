FROM python:3.13-slim

WORKDIR /app

# 安装 Chromium 所需的系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libexpat1 \
    libatspi2.0-0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libxcb1 \
    libxkbcommon0 \
    libcups2 \
    libdrm2 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖和 Playwright Chromium
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

# 复制应用代码
COPY . .

# Railway 注入 PORT 环境变量
CMD gunicorn server:app --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 600 --worker-class gevent
