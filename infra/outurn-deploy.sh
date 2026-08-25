#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/outurn"
STATE_DIR="/var/lib/outurn"
SUCCESS_FILE="${STATE_DIR}/last-successful-sha"
LOCK_FILE="${STATE_DIR}/deploy.lock"
COMPOSE=(docker compose -f docker-compose.prod.yml)

install -d -m 0755 "${STATE_DIR}"
exec 9>"${LOCK_FILE}"
flock -n 9 || exit 0

cd "${APP_DIR}"
git fetch --quiet origin main
TARGET_SHA="$(git rev-parse origin/main)"
LAST_SUCCESSFUL_SHA="$(cat "${SUCCESS_FILE}" 2>/dev/null || true)"

if [[ "${TARGET_SHA}" == "${LAST_SUCCESSFUL_SHA}" ]]; then
  exit 0
fi

git checkout -B main "${TARGET_SHA}"
"${COMPOSE[@]}" up -d --build --remove-orphans

for _ in $(seq 1 72); do
  postgres="$("${COMPOSE[@]}" ps -q postgres 2>/dev/null || true)"
  backend="$("${COMPOSE[@]}" ps -q backend 2>/dev/null || true)"
  postgres_status="$(docker inspect --format '{{.State.Health.Status}}' "${postgres}" 2>/dev/null || true)"
  backend_status="$(docker inspect --format '{{.State.Health.Status}}' "${backend}" 2>/dev/null || true)"

  if [[ "${postgres_status}" == healthy && "${backend_status}" == healthy ]]; then
    if curl --fail --silent --show-error http://127.0.0.1:3000/login >/dev/null; then
      printf '%s\n' "${TARGET_SHA}" > "${SUCCESS_FILE}"
      exit 0
    fi
  fi
  sleep 5
done

"${COMPOSE[@]}" ps >&2 || true
"${COMPOSE[@]}" logs --tail=80 >&2 || true
exit 1
