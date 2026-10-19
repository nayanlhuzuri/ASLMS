#!/bin/sh
# Renders alertmanager.yml.template with the SMTP_* settings and OPS_ALERT_EMAIL, then starts Alertmanager (design
# deployment-checklist, Part B, decision 25). The SMTP password is written to /tmp/smtp_password (mode 600) and read
# by Alertmanager through smtp_auth_password_file; it is never printed or put in the rendered configuration.
set -eu

TEMPLATE=/etc/alertmanager/alertmanager.yml.template
OUT=/tmp/alertmanager.yml

# a value for a single-quoted YAML string and a sed replacement: one line, ' doubled, \ & and | escaped
q() {
  printf '%s' "$1" | tr -d '\r\n' | sed -e "s/'/''/g" -e 's/[\\&|]/\\&/g'
}

umask 077
printf '%s' "${SMTP_PASSWORD:-}" > /tmp/smtp_password

if [ -n "${SMTP_HOST:-}" ] && [ -n "${OPS_ALERT_EMAIL:-}" ]; then
  receiver=ops-email
  case "$(printf '%s' "${SMTP_STARTTLS:-true}" | tr 'A-Z' 'a-z')" in
    false|0|no|off) tls=false ;;
    *) tls=true ;;
  esac
  sed -e '/^# BEGIN email$/d' -e '/^# END email$/d' \
      -e "s|__SMTP_HOST__|$(q "$SMTP_HOST")|g" \
      -e "s|__SMTP_PORT__|$(q "${SMTP_PORT:-587}")|g" \
      -e "s|__SMTP_FROM__|$(q "${SMTP_FROM:-}")|g" \
      -e "s|__SMTP_USER__|$(q "${SMTP_USER:-}")|g" \
      -e "s|__SMTP_REQUIRE_TLS__|$tls|g" \
      -e "s|__OPS_ALERT_EMAIL__|$(q "$OPS_ALERT_EMAIL")|g" \
      -e "s|__RECEIVER__|$receiver|g" \
      "$TEMPLATE" > "$OUT"
  echo "alertmanager: alerts are mailed to OPS_ALERT_EMAIL through SMTP_HOST"
else
  sed -e '/^# BEGIN email$/,/^# END email$/d' -e "s|__RECEIVER__|none|g" "$TEMPLATE" > "$OUT"
  echo "alertmanager: SMTP_HOST or OPS_ALERT_EMAIL is not set; alerts are shown in Alertmanager and Grafana only"
fi

exec /bin/alertmanager \
  --config.file="$OUT" \
  --storage.path=/alertmanager \
  --web.listen-address=:9093 \
  --web.external-url="${ALERTMANAGER_EXTERNAL_URL:-http://127.0.0.1:9093}" \
  "$@"
