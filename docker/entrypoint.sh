#!/bin/sh
# Run Calibre-Web as PUID:PGID (so files it writes belong to the same user/group as the libraries).
# CALIBRE_ADMIN_PASSWORD (optional): on the very first start, the admin account gets this password instead of the
# well-known default "admin123". Remove the variable from the stack once the container has started once.
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
CW="python /app/cps.py -p /config/app.db -o /config/calibre-web.log"

first_start_password() {
    if [ ! -f /config/app.db ] && [ -n "$CALIBRE_ADMIN_PASSWORD" ]; then
        # creates app.db, sets the admin password and exits
        $1 python /app/cps.py -p /config/app.db -o /config/calibre-web.log -s "admin:$CALIBRE_ADMIN_PASSWORD" \
            || { echo "CALIBRE_ADMIN_PASSWORD was not accepted (password rules?)" >&2; exit 1; }
    fi
}

if [ "$(id -u)" = "0" ]; then
    # gosu switches to the numeric uid:gid directly, so no user entry is needed (works with a read-only image)
    export HOME=/config
    mkdir -p /config/cache
    # only Calibre-Web's own folder; the libraries in /books keep their owners
    chown -R "$PUID:$PGID" /config
    umask 002
    first_start_password "gosu $PUID:$PGID"
    exec gosu "$PUID:$PGID" $CW "$@"
fi

first_start_password ""
exec $CW "$@"
