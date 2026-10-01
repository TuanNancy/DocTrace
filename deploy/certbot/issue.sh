#!/bin/sh
set -eu
: "${API_DOMAIN:?Set API_DOMAIN}"
: "${ACME_EMAIL:?Set ACME_EMAIL}"

exec certbot certonly \
    --webroot --webroot-path /var/www/certbot \
    --cert-name doctrace --domain "$API_DOMAIN" \
    --email "$ACME_EMAIL" --agree-tos --non-interactive
