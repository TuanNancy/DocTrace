#!/usr/bin/env bash
# Ubuntu host entrypoint. CI sends this script over SSH; secrets stay on the VPS.
set -Eeuo pipefail

ROOT_DIR=${DEPLOY_ROOT:-/opt/DocTrace}
ENV_FILE=${DEPLOY_ENV_FILE:-$ROOT_DIR/.env.production}
SCRIPT_PATH=$(realpath "${BASH_SOURCE[0]}")

dc() {
    docker compose --project-directory "$ROOT_DIR" --env-file "$ENV_FILE" \
        -f "$ROOT_DIR/compose.production.yml" "$@"
}

die() { echo "$*" >&2; exit 1; }

compose_settings() {
    dc config --format json | python3 -c '
import json, sys
c = json.load(sys.stdin)
n = c["services"]["nginx"]["environment"]
print(c["name"], n["API_DOMAIN"], n["TLS_MODE"])
'
}

diagnostics() {
    local status=$?
    trap - ERR
    echo "Deployment failed (exit $status). Last successful release is retained in $STATE_DIR/current." >&2
    dc ps --all || true
    dc logs --tail=80 api worker nginx || true
    echo "Recover with: bash $STATE_DIR/recover.sh rollback" >&2
    exit "$status"
}

write_release() {
    printf '%s %s\n' "$2" "$3" > "$1.tmp"
    mv "$1.tmp" "$1"
}

set_image() {
    # Persist the tag so certificate commands/manual Compose use the same release.
    python3 - "$ENV_FILE" "$1" <<'PY'
import os
from pathlib import Path
import re
import sys
import tempfile

path = Path(sys.argv[1])
lines = [line for line in path.read_text().splitlines()
         if not re.match(r"\s*(?:export\s+)?API_IMAGE\s*=", line)]
with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
    file.write("\n".join([*lines, f"API_IMAGE={sys.argv[2]}", ""]))
    name = file.name
os.replace(name, path)
PY
    export API_IMAGE=$1
}

check_worker() {
    # Match this container, not another/expired RQ worker registered in Redis.
    dc exec -T worker python - <<'PY'
from datetime import datetime, timezone
import socket

from redis import Redis
from rq import Worker
from app.core.config import get_config

config = get_config()
with Redis.from_url(config.redis_url, socket_connect_timeout=5, socket_timeout=5) as connection:
    connection.ping()
    for worker in Worker.all(connection=connection):
        if (worker.hostname == socket.gethostname()
                and worker.pid == 1
                and config.rq_queue_name in worker.queue_names()
                and worker.last_heartbeat is not None
                and (datetime.now(timezone.utc) - worker.last_heartbeat).total_seconds() < worker.worker_ttl):
            print(f"RQ worker registered on {config.rq_queue_name}")
            break
    else:
        raise SystemExit("Current worker has not registered a fresh heartbeat on the configured queue")
PY
}

main() {
    local action=${1:-} target=${2:-} image config project domain tls
    local current_sha current_image old_head api_id worker_id image_id attempt ready=0
    case "$action" in
        deploy) [[ "$target" =~ ^[0-9a-f]{40}$ ]] || die "Usage: bash deploy/deploy.sh deploy <full commit SHA>" ;;
        rollback) [[ $# == 1 ]] || die "Usage: bash deploy/deploy.sh rollback" ;;
        *) die "Usage: bash deploy/deploy.sh {deploy <full commit SHA>|rollback}" ;;
    esac
    cd "$ROOT_DIR"
    [[ "$(git rev-parse --show-toplevel)" == "$ROOT_DIR" ]] || die "DEPLOY_ROOT must be the repository root"
    [[ -f "$ENV_FILE" ]] || die "Missing production env: $ENV_FILE"
    STATE_DIR=$(git rev-parse --absolute-git-dir)/doctrace-deploy
    mkdir -p "$STATE_DIR"
    chmod 700 "$STATE_DIR"
    # Also serialize manual invocations, independent of GitHub concurrency.
    exec 9>"$STATE_DIR/lock"
    flock -n 9 || die "Another deployment is running"
    [[ -z "$(git status --porcelain --untracked-files=no)" ]] || die "Tracked VPS files have local edits; reconcile them before deploying"

    if [[ "$action" == rollback ]]; then
        [[ -f "$STATE_DIR/current" ]] || die "No release recorded yet"
        # The failed checkout may not even have valid Compose config. Restore it
        # before resolving config; use the recorded project to retain volumes.
        project=$(cat "$STATE_DIR/project")
    else
        [[ ! -f "$STATE_DIR/pending" ]] || die "Previous deployment is incomplete; run bash $STATE_DIR/recover.sh rollback first"
        config=$(compose_settings)
        read -r project domain tls <<< "$config"
        [[ "$tls" == https ]] || die "CD requires an already bootstrapped HTTPS deployment"
        if [[ -f "$STATE_DIR/current" ]]; then
            [[ "$project" == "$(cat "$STATE_DIR/project")" ]] || die "Compose project differs from the recorded release"
        fi
        api_id=$(dc ps --all --quiet api)
        [[ -n "$api_id" ]] || die "No existing API in Compose project $project; check COMPOSE_PROJECT_NAME/bootstrap first"
    fi
    export COMPOSE_PROJECT_NAME=$project

    if [[ ! -f "$STATE_DIR/current" ]]; then
        worker_id=$(dc ps --all --quiet worker)
        [[ -n "$worker_id" ]] || die "No existing worker"
        image_id=$(docker inspect --format '{{.Image}}' "$api_id")
        [[ "$image_id" == "$(docker inspect --format '{{.Image}}' "$worker_id")" ]] || die "API and worker must use the same image before enabling CD"
        old_head=$(git rev-parse HEAD)
        current_image=doctrace-api:retained-${image_id#sha256:}
        docker image tag "$image_id" "$current_image"
        printf '%s\n' "$project" > "$STATE_DIR/project"
        write_release "$STATE_DIR/current" "$old_head" "$current_image"
    fi
    read -r current_sha current_image < "$STATE_DIR/current"

    if [[ "$action" == deploy ]]; then
        GIT_TERMINAL_PROMPT=0 git fetch --no-tags origin +refs/heads/main:refs/remotes/origin/main
        git merge-base --is-ancestor "$target" refs/remotes/origin/main || die "Target commit is not on origin/main"
        if [[ "$target" != "$current_sha" ]] && git merge-base --is-ancestor "$target" "$current_sha"; then
            echo "Skipping stale deployment $target; $current_sha is already deployed"
            return
        fi
        git merge-base --is-ancestor "$current_sha" "$target" || die "Deployment history diverged; resolve main history before deploying"
        image=doctrace-api:sha-$target
    elif [[ -f "$STATE_DIR/pending" ]]; then
        target=$current_sha
        image=$current_image
    else
        [[ -f "$STATE_DIR/previous" ]] || die "No previous successful release is recorded"
        read -r target image < "$STATE_DIR/previous"
    fi
    if [[ "$action" == rollback ]]; then
        docker image inspect "$image" > /dev/null
    fi

    # Keep a recovery entrypoint even when rolling back to a commit predating CD.
    if [[ "$SCRIPT_PATH" != "$STATE_DIR/recover.sh" ]]; then
        cp "$SCRIPT_PATH" "$STATE_DIR/recover.sh"
    fi
    write_release "$STATE_DIR/pending" "$target" "$image"
    trap diagnostics ERR
    git checkout --detach "$target"
    if [[ "$action" == deploy ]] && ! docker image inspect "$image" > /dev/null 2>&1; then
        docker build --label "org.opencontainers.image.revision=$target" --tag "$image" "$ROOT_DIR/backend"
    fi
    set_image "$image"
    config=$(compose_settings)
    read -r project domain tls <<< "$config"
    [[ "$tls" == https && "$project" == "$COMPOSE_PROJECT_NAME" ]]
    # --wait-timeout bounds health readiness, not the worker's 16m graceful stop.
    dc up -d --no-build --wait --wait-timeout 180 api worker
    # Mounted templates are not part of Compose's config hash; render them afresh.
    dc up -d --no-build --no-deps --force-recreate --wait --wait-timeout 90 nginx
    dc exec -T nginx nginx -t
    for attempt in {1..12}; do
        if check_worker; then ready=1; break; fi
        echo "Waiting for RQ registration ($attempt/12)" >&2
        sleep 5
    done
    [[ "$ready" == 1 ]]
    curl --fail --silent --show-error --retry 5 --retry-all-errors --retry-delay 3 \
        --connect-timeout 5 --max-time 15 "https://$domain/health"
    echo

    if [[ "$target $image" != "$current_sha $current_image" ]]; then
        write_release "$STATE_DIR/previous" "$current_sha" "$current_image"
    fi
    write_release "$STATE_DIR/current" "$target" "$image"
    rm -f "$STATE_DIR/pending"
    trap - ERR
    dc ps
    echo "Deployed $target ($image) in Compose project $project"
}

main "$@"
