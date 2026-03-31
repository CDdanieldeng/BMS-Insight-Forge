FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    SAL_USE_VCLPLUGIN=svp

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libreoffice-impress-nogui \
    fonts-dejavu-core \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir \
    --trusted-host pypi.org \
    --trusted-host files.pythonhosted.org \
    -r requirements.txt

# 复制代码
COPY . /app

# 启动服务
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]