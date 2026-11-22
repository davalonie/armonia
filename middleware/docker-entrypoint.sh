#!/bin/sh
set -eu
umask 077
if [ "$(id -u)" = "0" ]; then
    echo "Run Music Homelab with a non-root UID and pre-owned dedicated volumes." >&2
    exit 1
fi
exec "$@"
