#!/bin/sh
# Prepare the mounted data disk, build the catalog once from the open-data package, then serve as the app user.
set -eu

DATA="${OPENEPW_DATA_ROOT:-/var/data/openepw}"
mkdir -p "$DATA"
# Render mounts disks as root; hand the data folder to the unprivileged app user.
if [ "$(stat -c %u "$DATA")" != "10001" ]; then
  chown -R app:app "$DATA"
fi

setpriv --reuid=app --regid=app --init-groups python -m openepw.deploy install-catalog --data-root "$DATA"

exec setpriv --reuid=app --regid=app --init-groups \
  openepw --data-root "$DATA" serve --host 0.0.0.0 --port "${PORT:-10000}"
