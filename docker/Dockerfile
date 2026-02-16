FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    BEETS_CONFIG=/config/config.yaml \
    BEETS_LIBRARY=/data/beets-library.blb \
    APP_PORT=7080 \
    APP_USER=appuser \
    PYTHONPATH="/app"

# ---------------------------------------------------------
# Install runtime dependencies
# ---------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libmagic1 \
    sqlite3 \
    curl \
    git \
    libchromaprint-tools \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    imagemagick \
    flac \
    nano \
    mpc \
    procps \
    coreutils \
    findutils \
    grep \
    sed \
    gawk \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---------------------------------------------------------
# Install Python dependencies
# ---------------------------------------------------------
COPY backend/requirements.txt /app/backend/requirements.txt

RUN pip install --no-cache-dir -r /app/backend/requirements.txt \
 && pip install --no-cache-dir \
        requests \
        pylast \
        pyacoustid \
        langdetect \
        beautifulsoup4 \
        Pillow \
        Wand

# ---------------------------------------------------------
# Create non-root user + directories
# ---------------------------------------------------------
RUN useradd -m -u 1000 ${APP_USER} \
 && mkdir -p /app/data /config /music /app/static \
 && chown -R ${APP_USER}:${APP_USER} /app /app/data /config /music /app/static

# ---------------------------------------------------------
# Copy application code
# ---------------------------------------------------------
COPY backend /app/backend
COPY config /config
COPY scripts /app/scripts
COPY entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh \
 && chmod +x /app/scripts/*.py \
 && chown -R ${APP_USER}:${APP_USER} /app/backend /app/scripts /app/entrypoint.sh

EXPOSE ${APP_PORT}

USER ${APP_USER}

# ---------------------------------------------------------
# Beets config symlink
# ---------------------------------------------------------
RUN mkdir -p /home/${APP_USER}/.config/beets && \
    rm -f /home/${APP_USER}/.config/beets/config.yaml && \
    ln -s /config/config.yaml /home/${APP_USER}/.config/beets/config.yaml

CMD ["/app/entrypoint.sh"]
