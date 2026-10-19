#!/bin/sh
# ClamAV offline mode (design deployment-checklist, decision 17): copies main.cvd, daily.cvd and bytecode.cvd from a
# folder filled by `cvdupdate` on a machine with internet access into the clamav container's database volume, then
# restarts clamav. Run from the repository root:  sh infra/clamav/import-signatures.sh <folder>
set -eu

dir="${1:-}"
if [ -z "$dir" ] || [ ! -d "$dir" ]; then
  echo "usage: sh infra/clamav/import-signatures.sh <folder with main.cvd, daily.cvd and bytecode.cvd>" >&2
  exit 2
fi
for f in main.cvd daily.cvd bytecode.cvd; do
  if [ ! -s "$dir/$f" ]; then
    echo "missing or empty: $dir/$f" >&2
    exit 2
  fi
done

container="$(docker compose ps -q clamav)"
if [ -z "$container" ]; then
  echo "the clamav service is not created; run: docker compose up -d clamav" >&2
  exit 1
fi
for f in main.cvd daily.cvd bytecode.cvd; do
  docker cp "$dir/$f" "$container:/var/lib/clamav/$f"
done
docker compose exec -u root clamav chown clamav:clamav /var/lib/clamav/main.cvd /var/lib/clamav/daily.cvd /var/lib/clamav/bytecode.cvd
docker compose restart clamav
echo "signatures imported; clamav restarted (healthy once clamd has loaded them)"
