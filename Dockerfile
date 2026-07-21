FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# FFmpeg is required by spotDL for conversion to MP3
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

# Run as an unprivileged user; writable dirs are created up front
RUN useradd -m botuser \
    && mkdir -p /app/data /app/logs /app/downloads \
    && chown -R botuser:botuser /app
USER botuser

CMD ["python", "-m", "bot.main"]
