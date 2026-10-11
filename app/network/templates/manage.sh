#!/bin/sh
# Offline deployment helper. Platform and paths are fixed at export.
set -eu
umask 077
PLATFORM='@PLATFORM@'
case "$PLATFORM" in
 debian) PROGRAM=/usr/local/lib/smooth-caddy; STATE=/var/lib/smooth-caddy; RUN=/run/smooth-caddy ;;
 openwrt) PROGRAM=/usr/lib/smooth-caddy; STATE=/etc/smooth-caddy/state; RUN=/tmp/smooth-caddy ;;
 *) echo 'Unknown package platform' >&2; exit 1 ;;
esac
CONFIG=/etc/smooth-caddy
RELEASES=$CONFIG/releases
fail() { echo "ERROR: $*" >&2; exit 1; }
field() { sed -n "s/^$2=//p" "$1/manifest"; }
# Accept legacy timestamps and current collision-resistant deployment identities.
RELEASE_PATTERN='[0-9]{8}-[0-9]{6}(-[a-f0-9]{8})?'
valid_release() {
 case "$1" in ''|*[!0-9a-f-]*) fail 'Invalid release name' ;; esac
 printf '%s\n' "$1" | grep -Eq "^$RELEASE_PATTERN$" || fail 'Invalid release name'
}
release_names() {
 find "$RELEASES" -maxdepth 1 -type l | sed 's|.*/||' | grep -E "^$RELEASE_PATTERN$" | sort
}
cleanup_objects() {
 for obj in "$RELEASES"/.objects/*; do
  referenced=0
  for name in $(release_names); do
   [ "$(readlink -f "$RELEASES/$name")" != "$obj" ] || referenced=1
  done
  [ "$referenced" = 1 ] || rm -rf "$obj"
 done
}
manager_pid() {
 if [ "$PLATFORM" = debian ]; then
  systemctl show smooth-caddy.service --property=MainPID --value
 else
  ubus call service list '{"name":"smooth-caddy"}' | jsonfilter -e '@["smooth-caddy"].instances.main.pid'
 fi
}
observe() {
 # procd restart returns before the old instance has necessarily exited.
 # Require a new PID after restart, then three consecutive stable intervals.
 previous_pid=${1:-}
 observed=''
 stable=0
 attempt=0
 while [ "$attempt" -lt 30 ]; do
  attempt=$((attempt + 1))
  current_pid=$(manager_pid) || current_pid=''
  case "$current_pid" in
   ''|0|*[!0-9]*) observed=''; stable=0 ;;
   *)
    if [ "$current_pid" = "$previous_pid" ] || ! kill -0 "$current_pid" 2>/dev/null; then
     observed=''; stable=0
    elif [ "$current_pid" = "$observed" ]; then
     stable=$((stable + 1))
     [ "$stable" -lt 3 ] || return 0
    else
     observed=$current_pid; stable=0
    fi
    ;;
  esac
  sleep 1 || return 1
 done
 return 1
}
lock() {
 mkdir -p "$RUN"
 if ! mkdir "$RUN/install.lock" 2>/dev/null; then
  owner=$(cat "$RUN/install.lock/pid" 2>/dev/null || true)
  case "$owner" in ''|*[!0-9]*) fail 'Installation lock is incomplete; inspect it before retrying' ;; esac
  if kill -0 "$owner" 2>/dev/null; then fail 'Another installation is running'; fi
  rm -rf "$RUN/install.lock"
  mkdir "$RUN/install.lock" || fail 'Unable to acquire installation lock'
 fi
 echo $$ > "$RUN/install.lock/pid"
 trap 'rm -rf "$RUN/install.lock"' EXIT
 trap 'exit 130' INT
 trap 'exit 143' TERM
}
select_release() {
 selected=$1
 ln -s "releases/$selected" "$CONFIG/.current-$$"
 mv -fT "$CONFIG/.current-$$" "$CONFIG/current"
}
prune() {
 active=$(basename "$(readlink "$CONFIG/current")")
 kept=1
 for name in $(release_names | sort -r); do
  [ "$name" = "$active" ] && continue
  [ -f "$RELEASES/$name/.success" ] || continue
  if [ "$kept" -lt 5 ]; then kept=$((kept + 1)); continue; fi
  target=$(readlink -f "$RELEASES/$name")
  rm "$RELEASES/$name"
  rm -rf "$target"
 done
}
activate() {
 previous_pid=$(manager_pid) || previous_pid=''
 selected=$1
 select_release "$selected"
 if [ "$PLATFORM" = debian ]; then
  systemctl daemon-reload
  systemctl enable smooth-caddy.service
  systemctl restart smooth-caddy.service || fail 'Service restart failed; no automatic rollback'
 else
  /etc/init.d/smooth-caddy enable
  /etc/init.d/smooth-caddy restart || fail 'Service restart failed; no automatic rollback'
 fi
 observe "$previous_pid" || fail 'Caddy did not reach a stable new process within 30 seconds; selected release retained, no rollback'
 touch "$RELEASES/$selected/.success"
 echo "$selected" > "$STATE/.last-success-$$"
 mv -f "$STATE/.last-success-$$" "$STATE/last-success"
 prune
 echo "SUCCESS: $selected"
}
check_binary() {
 material=$1
 version=$(field "$material" caddy_version)
 arch=$(field "$material" arch)
 echo "$version" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$' || fail 'Invalid Caddy version'
 machine=$(uname -m)
 case "$arch:$machine" in
  amd64:x86_64|arm64:aarch64|armv7:armv7l|386:i386|386:i486|386:i586|386:i686) ;;
  *) fail 'Architecture mismatch' ;;
 esac
 binary=$PROGRAM/binaries/$version/$arch/caddy
}
case "${1:-}" in
 run)
  release_dir=$(readlink -f "$CONFIG/current")
  check_binary "$release_dir"
  export XDG_DATA_HOME=$STATE/data XDG_CONFIG_HOME=$STATE/config
  exec "$binary" run --config "$release_dir/caddy.json"
  ;;
 status)
  selected=$(basename "$(readlink "$CONFIG/current" 2>/dev/null || true)")
  printf 'selected=%s\n' "$selected"
  if [ -n "$selected" ] && [ -f "$RELEASES/$selected/.success" ] && observe; then
   printf 'state=running\n'
  else
   printf 'state=unconfirmed\n'
   exit 1
  fi
  ;;
 list)
  for name in $(release_names); do
   status=failed-or-unconfirmed
   [ ! -f "$RELEASES/$name/.success" ] || status=successful
   echo "$name $status"
  done
  ;;
 switch)
  valid_release "${2:-}"
  [ -d "$RELEASES/$2" ] || fail 'Release not found'
  check_binary "$RELEASES/$2"
  [ -x "$binary" ] || fail 'Required Caddy binary is missing'
  [ -f "$binary.sha256" ] || fail 'Binary checksum record missing'
  [ "$(sha256sum "$binary" | cut -d ' ' -f1)" = "$(cat "$binary.sha256")" ] || fail 'Binary checksum mismatch'
  (cd "$RELEASES/$2" && sha256sum -c SHA256SUMS) || fail 'Release files damaged'
  lock
  activate "$2"
  ;;
 install)
  payload=$2
  name=$(field "$payload/release" release)
  valid_release "$name"
  [ "$(field "$payload/release" platform)" = "$PLATFORM" ] || fail 'Platform declaration mismatch'
  check_binary "$payload/release"
  if [ "$PLATFORM" = debian ]; then
   command -v systemctl >/dev/null || fail 'systemctl missing'
   [ -d /run/systemd/system ] || fail 'System systemd manager not available'
  else
   for tool in ubus jsonfilter; do command -v "$tool" >/dev/null || fail "$tool missing"; done
   ubus list service | grep -qx service || fail 'procd service interface not available'
  fi
  for dir in "$PROGRAM" "$STATE" "$CONFIG" "$RELEASES/.objects" "$RUN"; do
   mkdir -p "$dir" || fail "Cannot create $dir"
   probe=$dir/.write-probe-$$
   : > "$probe" || fail "Cannot write $dir"
   rm "$probe"
  done
  lock
  [ "$(field "$payload/release" format)" = 1 ] || fail 'Unsupported package format'
  node_id=$(field "$payload/release" node_id)
  echo "$node_id" | grep -Eq '^[a-f0-9]{32}$' || fail 'Invalid node identity'
  if [ -f "$STATE/node-id" ]; then
   [ "$(cat "$STATE/node-id")" = "$node_id" ] || fail 'Package belongs to a different node'
  fi
  if [ -f "$payload/caddy" ]; then
   mkdir -p "$(dirname "$binary")"
   expected=$(field "$payload/release" binary_sha256)
   actual=$(sha256sum "$binary" 2>/dev/null | cut -d ' ' -f1) || actual=''
   if [ "$actual" != "$expected" ]; then
    cp "$payload/caddy" "$binary.new-$$"
    chmod 755 "$binary.new-$$"
    mv -f "$binary.new-$$" "$binary"
   fi
   echo "$expected" > "$binary.sha256"
  fi
  [ -x "$binary" ] || fail 'Required Caddy binary missing; use a full package'
  expected=$(field "$payload/release" binary_sha256)
  if [ -z "$expected" ]; then
   [ -f "$binary.sha256" ] || fail 'Required binary checksum record missing; use a full package'
   expected=$(cat "$binary.sha256")
  fi
  if [ -n "$expected" ]; then
   [ "$(sha256sum "$binary" | cut -d ' ' -f1)" = "$expected" ] || fail 'Caddy binary checksum mismatch'
  fi
  [ "$("$binary" version | cut -d ' ' -f1)" = "$version" ] || fail 'Caddy version mismatch'
  digest=$(sha256sum "$payload/release/SHA256SUMS" | cut -d ' ' -f1)
  if [ -d "$RELEASES/$name" ] && [ "$(cat "$RELEASES/$name/.digest" 2>/dev/null || true)" = "$digest" ]; then
   if (cd "$RELEASES/$name" && sha256sum -c SHA256SUMS >/dev/null 2>&1) &&
      [ "$(readlink "$CONFIG/current" 2>/dev/null || true)" = "releases/$name" ] && observe; then
    echo "ALREADY INSTALLED: $name"; exit 0
   fi
  fi
  # A release name is an atomic symlink to a fully prepared object directory.
  object=$name-$$
  cp -R "$payload/release" "$RELEASES/.objects/$object"
  (cd "$RELEASES/.objects/$object" && sha256sum -c SHA256SUMS) || fail 'Prepared release checksum failed'
  echo "$digest" > "$RELEASES/.objects/$object/.digest"
  old=''
  if [ -L "$RELEASES/$name" ]; then old=$(readlink -f "$RELEASES/$name"); fi
  ln -s ".objects/$object" "$RELEASES/.release-$$"
  mv -fT "$RELEASES/.release-$$" "$RELEASES/$name"
  cp "$payload/manage.sh" "$PROGRAM/.manage-$$"
  chmod 755 "$PROGRAM/.manage-$$"
  mv -f "$PROGRAM/.manage-$$" "$PROGRAM/manage"
  if [ "$PLATFORM" = debian ]; then
   cp "$payload/service" /etc/systemd/system/smooth-caddy.service
  else
   cp "$payload/service" /etc/init.d/smooth-caddy
   chmod 755 /etc/init.d/smooth-caddy
  fi
  echo "$node_id" > "$STATE/node-id"
  activate "$name"
  if [ -n "$old" ] && [ "$old" != "$RELEASES/.objects/$object" ]; then rm -rf "$old"; fi
  # Remove abandoned preparation objects after successful installation only.
  cleanup_objects
  ;;
 *) echo 'Usage: manage list | switch RELEASE | run | install PAYLOAD' >&2; exit 2 ;;
esac
