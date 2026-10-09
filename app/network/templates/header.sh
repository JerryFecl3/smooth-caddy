#!/bin/sh
# Self-contained offline installation package.
set -eu
umask 077
for tool in awk tail tar gzip sha256sum mktemp uname sed grep cut cp mv ln readlink find sort; do
 command -v "$tool" >/dev/null 2>&1 || { echo "Missing tool: $tool" >&2; exit 1; }
done
work=$(mktemp -d /tmp/smooth-caddy-package.XXXXXX)
trap 'rm -rf "$work"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
line=$(awk '/^__CADDY_PAYLOAD__$/ { print NR+1; exit }' "$0")
tail -n +"$line" "$0" > "$work/payload.tar.gz"
echo '@PAYLOAD_HASH@  '"$work/payload.tar.gz" | sha256sum -c - >/dev/null
mkdir "$work/payload"
tar -xzf "$work/payload.tar.gz" -C "$work/payload"
(cd "$work/payload" && sha256sum -c SHA256SUMS >/dev/null)
sh "$work/payload/manage.sh" install "$work/payload"
exit $?
__CADDY_PAYLOAD__
