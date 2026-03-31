FROM ubuntu:22.04

# Headless LibreOffice on Jammy: writable profile, SVP backend (no X11)
ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    SAL_USE_VCLPLUGIN=svp

WORKDIR /app

# ffmpeg/ffprobe: pydub
# libreoffice-impress-nogui: PPTX→PDF for full-slide preview (no full desktop stack)
# fonts: avoid empty/box glyphs in PDFs from headless conversion
# Python 3.11: Jammy ships 3.10; deadsnakes matches prior python:3.11-slim image
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        software-properties-common \
    ; \
    add-apt-repository -y ppa:deadsnakes/ppa; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-dejavu-core \
        fonts-liberation \
        libreoffice-impress-nogui \
        python3.11 \
        python3.11-venv \
    ; \
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11; \
    ln -sf /usr/bin/python3.11 /usr/local/bin/python; \
    ln -sf /usr/bin/python3.11 /usr/local/bin/python3; \
    apt-get purge -y --auto-remove curl gnupg software-properties-common; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
