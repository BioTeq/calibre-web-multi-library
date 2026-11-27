#!/bin/sh
# Run Calibre-Web as PUID:PGID (so files it writes belong to the same user/group as the libraries).
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" = "0" ]; then
    group="$(getent group "$PGID" | cut -d: -f1)"
    if [ -z "$group" ]; then
        groupadd -g "$PGID" calibre
        group=calibre
    fi
    if ! getent passwd "$PUID" >/dev/null; then
        useradd -u "$PUID" -g "$PGID" -d /config -s /usr/sbin/nologin -M calibre
    fi
    mkdir -p /config/cache
    # only Calibre-Web's own folder; the libraries in /books keep their owners
    chown -R "$PUID:$PGID" /config
    umask 002
    exec gosu "$PUID:$PGID" python /app/cps.py -p /config/app.db -o /config/calibre-web.log "$@"
fi

exec python /app/cps.py -p /config/app.db -o /config/calibre-web.log "$@"
