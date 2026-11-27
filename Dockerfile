# Calibre-Web Multi-Library
#   /config  settings (app.db), per-library reading state (libraries/), cache, log
#   /books   library root: every sub-folder with a metadata.db is a library (folders starting with _ or . are skipped)
FROM python:3.12-slim-bookworm

ARG TARGETARCH
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PUID=1000 \
    PGID=1000 \
    CALIBRE_DBPATH=/config \
    CACHE_DIRECTORY=/config/cache \
    CALIBRE_LIBRARY_ROOT=/books \
    CALIBRE_WEB_PORT=8083

# imagemagick: covers from EPUB/PDF; libmagic: file types; gosu: drop root to PUID/PGID
RUN apt-get update \
 && apt-get install -y --no-install-recommends imagemagick ghostscript libmagic1 gosu curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# kepubify for Kobo (Calibre-Web looks for it at this path)
RUN mkdir -p /opt/kepubify \
 && case "${TARGETARCH:-amd64}" in arm64) K=kepubify-linux-arm64 ;; *) K=kepubify-linux-64bit ;; esac \
 && curl -fsSL -o /opt/kepubify/kepubify-linux-64bit "https://github.com/pgaskin/kepubify/releases/latest/download/$K" \
 && chmod 755 /opt/kepubify/kepubify-linux-64bit

WORKDIR /app
COPY requirements.txt optional-requirements.txt ./
# optional features kept: Kobo sync, comics, audio, metadata formats (no LDAP/Google Drive/OAuth)
RUN pip install --no-cache-dir -r requirements.txt \
 && grep -E '^(jsonschema|comicapi|py7zr|rarfile|natsort|mutagen|beautifulsoup4|html2text|markdown2|python-dateutil|faust-cchardet)[<>=]' \
      optional-requirements.txt > /tmp/optional.txt \
 && pip install --no-cache-dir -r /tmp/optional.txt

COPY cps.py ./
COPY cps ./cps
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh && python -m compileall -q cps

VOLUME ["/config", "/books"]
EXPOSE 8083
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s \
  CMD curl -fsS "http://127.0.0.1:${CALIBRE_WEB_PORT}/login" -o /dev/null || exit 1
ENTRYPOINT ["/entrypoint.sh"]
