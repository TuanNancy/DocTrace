#!/bin/sh
set -eu

: "${API_DOMAIN:?Set API_DOMAIN}"
case "$API_DOMAIN" in
    *[!a-zA-Z0-9.-]*|.*|-*|*.)
        echo "API_DOMAIN must be a DNS hostname, without scheme, port or path." >&2
        exit 1
        ;;
esac

case "${TLS_MODE:-https}" in
    http) template=/opt/doctrace/bootstrap.conf.template ;;
    https)
        for file in fullchain.pem privkey.pem; do
            if [ ! -s "/etc/letsencrypt/live/doctrace/$file" ]; then
                echo "TLS certificate missing. Run: sh deploy/certificates.sh bootstrap, then issue." >&2
                exit 1
            fi
        done
        template=/opt/doctrace/https.conf.template
        ;;
    *) echo "TLS_MODE must be http or https." >&2; exit 1 ;;
esac

# Substitute only our variable; preserve Nginx's $host, $scheme, $request_uri, etc.
envsubst '${API_DOMAIN}' < "$template" > /etc/nginx/conf.d/default.conf
exec /docker-entrypoint.sh nginx -g 'daemon off;'
