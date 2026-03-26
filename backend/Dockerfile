FROM python:3.11-slim

WORKDIR /app

# ffmpeg/ffprobe: pydub; libreoffice-impress: full-slide PPTX preview (pptx → pdf → png)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libreoffice-impress \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app
ENV PYTHONPATH=/app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
