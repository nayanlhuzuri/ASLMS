#!/bin/sh
# Runs in the nginx image's /docker-entrypoint.d/ before the templates are rendered (design deployment-checklist,
# decisions 7-9). Writes the snippets the template includes, from the same values the API reads:
#   server_name.conf  the host of PORTAL_BASE_URL (any other Host is refused with 444)
#   limit-upload.conf client_max_body_size = UPLOAD_MAX_BYTES + 65536 (api/routers/documents.py MULTIPART_OVERHEAD)
#   limit-notes.conf  client_max_body_size = ATTACHMENTS_MAX_FILES x UPLOAD_MAX_BYTES + 65536
#   timeouts.conf     proxy_read_timeout = RELAY_TIMEOUT_SECONDS + 30
#   real_ip.conf      set_real_ip_from PROXY_TRUSTED_UPSTREAM (a load balancer in front, at the SDC), else nothing
# and refuses to start without the certificate. ASLMS_NGINX_DIR, ASLMS_CERT_DIR and NGINX_CONF_D exist for the tests.
set -eu

out="${ASLMS_NGINX_DIR:-/etc/nginx/aslms}"
certs="${ASLMS_CERT_DIR:-/etc/nginx/certs}"
confd="${NGINX_CONF_D:-/etc/nginx/conf.d}"
overhead=65536

number() {
  case "$2" in
    ''|*[!0-9]*) echo "15-aslms-limits: $1 must be a whole number" >&2; exit 1 ;;
  esac
}

upload="${UPLOAD_MAX_BYTES:-20971520}"
files="${ATTACHMENTS_MAX_FILES:-5}"
relay="${RELAY_TIMEOUT_SECONDS:-120}"
number UPLOAD_MAX_BYTES "$upload"
number ATTACHMENTS_MAX_FILES "$files"
number RELAY_TIMEOUT_SECONDS "$relay"

base="${PORTAL_BASE_URL:-}"
case "$base" in
  http://*|https://*) ;;
  *) echo "15-aslms-limits: PORTAL_BASE_URL must start with https:// (or http://)" >&2; exit 1 ;;
esac
host="${base#*://}"
host="${host%%/*}"
host="${host%%:*}"
if [ -z "$host" ]; then
  echo "15-aslms-limits: PORTAL_BASE_URL has no host" >&2
  exit 1
fi

for f in fullchain.pem privkey.pem; do
  if [ ! -s "$certs/$f" ]; then
    echo "15-aslms-limits: $certs/$f is missing; make one with 'aslms ops make-cert' (see docs/operations.md)" >&2
    exit 1
  fi
done

mkdir -p "$out"
echo "server_name $host;" > "$out/server_name.conf"
echo "client_max_body_size $((upload + overhead));" > "$out/limit-upload.conf"
echo "client_max_body_size $((files * upload + overhead));" > "$out/limit-notes.conf"
printf 'proxy_read_timeout %ss;\nproxy_send_timeout %ss;\n' "$((relay + 30))" "$((relay + 30))" > "$out/timeouts.conf"
if [ -n "${PROXY_TRUSTED_UPSTREAM:-}" ]; then
  printf 'set_real_ip_from %s;\nreal_ip_header X-Forwarded-For;\nreal_ip_recursive on;\n' \
    "$PROXY_TRUSTED_UPSTREAM" > "$out/real_ip.conf"
else
  echo "# no trusted upstream: \$remote_addr is the connecting client" > "$out/real_ip.conf"
fi
# the image's welcome page would answer on port 80 for Host localhost
rm -f "$confd/default.conf"
echo "15-aslms-limits: host $host; upload $((upload + overhead)) B; notes $((files * upload + overhead)) B"
