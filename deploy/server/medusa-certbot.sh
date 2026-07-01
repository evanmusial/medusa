#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  deploy/server/medusa-certbot.sh issue
  deploy/server/medusa-certbot.sh renew
  deploy/server/medusa-certbot.sh dry-run
  deploy/server/medusa-certbot.sh install-current
  deploy/server/medusa-certbot.sh install-hook

Commands:
  issue           Request/replace the certificate, copy it into data/haproxy,
                  and install the certbot deploy hook.
  renew           Run certbot renew for the configured cert, then copy the
                  current cert into data/haproxy.
  dry-run         Exercise certbot renewal validation without replacing files.
  install-current Copy the current /etc/letsencrypt live cert into data/haproxy.
  install-hook    Install the deploy hook that refreshes data/haproxy after
                  future automatic certbot renewals.

Environment:
  MEDUSA_REPO              Repo checkout. Defaults to this script's repo.
  MEDUSA_ENV_FILE          Env file to read. Defaults to $MEDUSA_REPO/.env.
  MEDUSA_CERTBOT_DOMAIN    Domain override. Defaults to MEDUSA_PUBLIC_HOST.
  MEDUSA_CERTBOT_CERT_NAME Cert name override. Defaults to the domain.
  MEDUSA_CERTBOT_BIND_IP   HTTP-01 bind IP override. Defaults to MEDUSA_BIND_IP.
  MEDUSA_CERTBOT_EMAIL     Contact email for first-time certbot registration.
  MEDUSA_HAPROXY_CERT_GROUP
                           Group that may read the mounted cert files.
                           Defaults to 99, the haproxy image group.

Standalone HTTP-01 validation requires inbound TCP/80 on the bind IP to be free
and publicly reachable. Medusa itself normally uses MEDUSA_HAPROXY_PORT, which
defaults to HTTPS port 3737.
EOF
}

die() {
  printf 'medusa-certbot: %s\n' "$*" >&2
  exit 1
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
default_repo="$(cd -- "${script_dir}/../.." && pwd)"
repo="${MEDUSA_REPO:-$default_repo}"
env_file="${MEDUSA_ENV_FILE:-$repo/.env}"
command_name="${1:-issue}"

if [[ "$command_name" == "-h" || "$command_name" == "--help" ]]; then
  usage
  exit 0
fi

read_env_value() {
  local key="$1"
  [[ -f "$env_file" ]] || return 1
  awk -v key="$key" '
    /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
    index($0, key "=") == 1 {
      value = substr($0, length(key) + 2)
      gsub(/\r$/, "", value)
      if (value ~ /^".*"$/ || value ~ /^\047.*\047$/) {
        value = substr(value, 2, length(value) - 2)
      }
      print value
      exit
    }
  ' "$env_file"
}

normalize_host() {
  local raw="$1"
  raw="${raw#http://}"
  raw="${raw#https://}"
  raw="${raw%%/*}"
  raw="${raw%%:*}"
  printf '%s' "$raw"
}

stat_owner() {
  if stat -c '%U' "$1" >/dev/null 2>&1; then
    stat -c '%U' "$1"
  else
    stat -f '%Su' "$1"
  fi
}

stat_group() {
  if stat -c '%G' "$1" >/dev/null 2>&1; then
    stat -c '%G' "$1"
  else
    stat -f '%Sg' "$1"
  fi
}

shell_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

public_host="${MEDUSA_CERTBOT_DOMAIN:-${MEDUSA_PUBLIC_HOST:-$(read_env_value MEDUSA_PUBLIC_HOST || true)}}"
domain="$(normalize_host "$public_host")"
[[ -n "$domain" ]] || die "set MEDUSA_PUBLIC_HOST in $env_file or MEDUSA_CERTBOT_DOMAIN"

bind_ip="${MEDUSA_CERTBOT_BIND_IP:-${MEDUSA_BIND_IP:-$(read_env_value MEDUSA_BIND_IP || true)}}"
bind_ip="${bind_ip:-0.0.0.0}"
cert_name="${MEDUSA_CERTBOT_CERT_NAME:-$domain}"
certbot_email="${MEDUSA_CERTBOT_EMAIL:-}"

haproxy_dir="$repo/data/haproxy"
fullchain_target="$haproxy_dir/fullchain.pem"
privatekey_target="$haproxy_dir/privatekey.pem"
lineage="/etc/letsencrypt/live/$cert_name"
hook_path="${MEDUSA_CERTBOT_HOOK_PATH:-/etc/letsencrypt/renewal-hooks/deploy/medusa-copy-cert.sh}"
repo_owner="${MEDUSA_CERT_OWNER:-$(stat_owner "$repo")}"
haproxy_cert_group="${MEDUSA_HAPROXY_CERT_GROUP:-99}"

if (( EUID == 0 )); then
  sudo_cmd=()
else
  sudo_cmd=(sudo)
fi

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

has_certbot_account() {
  "${sudo_cmd[@]}" sh -c 'find /etc/letsencrypt/accounts -mindepth 3 -maxdepth 3 -type d -print -quit 2>/dev/null | grep -q .'
}

ensure_certbot_registration_ready() {
  if [[ -n "$certbot_email" ]] || has_certbot_account; then
    return 0
  fi
  die "set MEDUSA_CERTBOT_EMAIL for first-time certbot registration on this host"
}

install_cert_files() {
  "${sudo_cmd[@]}" test -f "$lineage/fullchain.pem" || die "missing $lineage/fullchain.pem"
  "${sudo_cmd[@]}" test -f "$lineage/privkey.pem" || die "missing $lineage/privkey.pem"

  "${sudo_cmd[@]}" install -d -m 750 -o "$repo_owner" -g "$haproxy_cert_group" "$haproxy_dir"
  "${sudo_cmd[@]}" install -m 640 -o "$repo_owner" -g "$haproxy_cert_group" \
    "$lineage/fullchain.pem" "$fullchain_target"
  "${sudo_cmd[@]}" install -m 640 -o "$repo_owner" -g "$haproxy_cert_group" \
    "$lineage/privkey.pem" "$privatekey_target"
  printf 'Installed certificate files:\n  %s\n  %s\n' "$fullchain_target" "$privatekey_target"
}

install_hook() {
  local tmp
  tmp="$(mktemp)"
  cat >"$tmp" <<EOF
#!/bin/sh
set -eu

CERT_NAME=$(shell_quote "$cert_name")
REPO=$(shell_quote "$repo")
OWNER=$(shell_quote "$repo_owner")
HAPROXY_CERT_GROUP=$(shell_quote "$haproxy_cert_group")
LINEAGE="/etc/letsencrypt/live/\${CERT_NAME}"

if [ "\${RENEWED_LINEAGE:-}" != "\${LINEAGE}" ]; then
  exit 0
fi

install -d -m 750 -o "\${OWNER}" -g "\${HAPROXY_CERT_GROUP}" "\${REPO}/data/haproxy"
install -m 640 -o "\${OWNER}" -g "\${HAPROXY_CERT_GROUP}" "\${RENEWED_LINEAGE}/fullchain.pem" "\${REPO}/data/haproxy/fullchain.pem"
install -m 640 -o "\${OWNER}" -g "\${HAPROXY_CERT_GROUP}" "\${RENEWED_LINEAGE}/privkey.pem" "\${REPO}/data/haproxy/privatekey.pem"

if command -v docker >/dev/null 2>&1 && [ -f "\${REPO}/docker-compose.server.yml" ]; then
  cd "\${REPO}"
  docker compose -f docker-compose.yml -f docker-compose.server.yml restart haproxy >/dev/null 2>&1 || true
fi
EOF
  "${sudo_cmd[@]}" install -d -m 755 "$(dirname "$hook_path")"
  "${sudo_cmd[@]}" install -m 755 -o root -g root "$tmp" "$hook_path"
  rm -f "$tmp"
  printf 'Installed certbot deploy hook: %s\n' "$hook_path"
}

restart_haproxy_if_running() {
  local haproxy_id
  command -v docker >/dev/null 2>&1 || return 0
  [[ -f "$repo/docker-compose.server.yml" ]] || return 0
  haproxy_id="$(
    cd "$repo" &&
      docker compose -f docker-compose.yml -f docker-compose.server.yml ps -q haproxy 2>/dev/null || true
  )"
  [[ -n "$haproxy_id" ]] || return 0
  (
    cd "$repo"
    docker compose -f docker-compose.yml -f docker-compose.server.yml restart haproxy
  )
}

run_certonly() {
  local email_args=()
  if [[ -n "$certbot_email" ]]; then
    email_args=(--email "$certbot_email")
  fi

  ensure_certbot_registration_ready
  "${sudo_cmd[@]}" certbot certonly \
    --standalone \
    --preferred-challenges http \
    --http-01-address "$bind_ip" \
    --cert-name "$cert_name" \
    -d "$domain" \
    --non-interactive \
    --agree-tos \
    "${email_args[@]}"
}

run_renew() {
  "${sudo_cmd[@]}" certbot renew \
    --cert-name "$cert_name" \
    --http-01-address "$bind_ip"
}

run_dry_run() {
  "${sudo_cmd[@]}" certbot renew \
    --cert-name "$cert_name" \
    --http-01-address "$bind_ip" \
    --dry-run
}

require_command install
require_command certbot

case "$command_name" in
  issue)
    printf 'Requesting certificate %s for %s on %s using certbot standalone HTTP-01.\n' \
      "$cert_name" "$domain" "$bind_ip"
    run_certonly
    install_cert_files
    install_hook
    restart_haproxy_if_running
    ;;
  renew)
    printf 'Renewing certificate %s on %s using certbot standalone HTTP-01.\n' \
      "$cert_name" "$bind_ip"
    install_hook
    run_renew
    install_cert_files
    restart_haproxy_if_running
    ;;
  dry-run)
    printf 'Dry-running certificate renewal for %s on %s.\n' "$cert_name" "$bind_ip"
    run_dry_run
    ;;
  install-current)
    install_cert_files
    restart_haproxy_if_running
    ;;
  install-hook)
    install_hook
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
