#!/bin/sh
# Run on the Docker host. Certbot never receives the Docker socket.
set -eu
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE=${DEPLOY_ENV_FILE:-"$ROOT_DIR/.env.production"}

dc() {
    docker compose --project-directory "$ROOT_DIR" --env-file "$ENV_FILE" \
        -f "$ROOT_DIR/compose.production.yml" "$@"
}

reload_nginx() {
    dc exec -T nginx nginx -t
    dc exec -T nginx nginx -s reload
}

case "${1:-}" in
    bootstrap)
        # The .env file stays in https mode; this override is for initial issuance only.
        TLS_MODE=http dc up -d --build --wait api nginx
        ;;
    issue)
        dc run --rm --entrypoint /bin/sh certbot /opt/doctrace/issue.sh
        TLS_MODE=https dc up -d --wait nginx
        reload_nginx
        ;;
    renew)
        dc run --rm certbot renew --non-interactive
        # Renewal can be a no-op; a graceful reload twice daily is harmless.
        # On any certbot/config error, set -e stops before sending the reload signal.
        reload_nginx
        ;;
    *)
        echo "Usage: sh deploy/certificates.sh {bootstrap|issue|renew}" >&2
        exit 2
        ;;
esac
