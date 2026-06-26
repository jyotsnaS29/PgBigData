#!/usr/bin/env bash
# Idempotent deploy of the ACS Explorer on the Hostinger VPS.
# Run from the project directory on the VPS (as root), with a populated .env.
#
#   cd /root/pgbigdata && bash deploy/deploy.sh
set -euo pipefail

DOMAIN="census.datallmai.com"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

say() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }

[ -f .env ] || { echo "Missing .env (copy .env.prod.example and fill it in)"; exit 1; }

say "Building + starting containers"
docker compose -f docker-compose.prod.yml up -d --build

say "Applying schema"
docker compose -f docker-compose.prod.yml run --rm dashboard python -m pgbigdata.cli init-db

say "Ingesting ACS county data (idempotent — skips if already loaded)"
docker compose -f docker-compose.prod.yml run --rm dashboard \
  python -m pgbigdata.cli ingest-acs --year 2022 --geography county

say "Installing nginx site for ${DOMAIN}"
cp "deploy/nginx-${DOMAIN}.conf" "/etc/nginx/sites-available/${DOMAIN}"
ln -sf "/etc/nginx/sites-available/${DOMAIN}" "/etc/nginx/sites-enabled/${DOMAIN}"
nginx -t && systemctl reload nginx

say "Obtaining HTTPS certificate"
certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos \
  -m "vidit.viionn@gmail.com" --redirect || \
  echo "certbot failed — check that ${DOMAIN} resolves to this VPS and port 80 is open"

say "Done — https://${DOMAIN}"
