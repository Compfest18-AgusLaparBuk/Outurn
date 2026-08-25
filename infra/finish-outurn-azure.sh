#!/usr/bin/env bash
set -Eeuo pipefail

KEY_VAULT="${1:?Usage: finish-outurn-azure.sh KEY_VAULT PUBLIC_DOMAIN}"
PUBLIC_DOMAIN="${2:?Usage: finish-outurn-azure.sh KEY_VAULT PUBLIC_DOMAIN}"
REPO_URL="https://github.com/Compfest18-AgusLaparBuk/Outurn.git"
ADMIN_USER="outurnadmin"

id -u "${ADMIN_USER}" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "${ADMIN_USER}"
usermod -aG docker "${ADMIN_USER}" 2>/dev/null || true
install -d -o "${ADMIN_USER}" -g "${ADMIN_USER}" -m 0700 /opt/outurn /var/lib/outurn

for _ in $(seq 1 24); do
  if az login --identity --allow-no-subscriptions >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

if [[ ! -d /opt/outurn/.git ]]; then
  rm -rf /opt/outurn
  git clone --branch main --depth 1 "${REPO_URL}" /opt/outurn
else
  git -C /opt/outurn fetch --quiet origin main
  git -C /opt/outurn checkout -B main origin/main
fi

get_secret() {
  local value=""
  for _ in $(seq 1 24); do
    value="$(az keyvault secret show --vault-name "${KEY_VAULT}" --name "$1" --query value -o tsv 2>/dev/null || true)"
    if [[ -n "${value}" ]]; then
      printf '%s' "${value}"
      return 0
    fi
    sleep 5
  done
  printf 'Unable to read required secret: %s\n' "$1" >&2
  exit 1
}

{
  printf '%s\n' 'APP_ENV=production'
  printf 'APP_PUBLIC_ORIGIN=https://%s\n' "${PUBLIC_DOMAIN}"
  printf 'CORS_ORIGINS=https://%s\n' "${PUBLIC_DOMAIN}"
  printf 'APP_API_KEY=%s\n' "$(get_secret app-api-key)"
  printf 'WEBHOOK_SECRET_KEY=%s\n' "$(get_secret webhook-secret-key)"
  printf 'POSTGRES_PASSWORD=%s\n' "$(get_secret postgres-password)"
  printf '%s\n' 'DATABASE_URL=postgresql+psycopg://outurn:unused@postgres:5432/outurn'
  printf '%s\n' 'COOKIE_SECURE=true'
  printf '%s\n' 'DOCUMENT_STORAGE_ROOT=/data/documents'
  printf '%s\n' 'DOCUMENT_ALLOWED_MIME_TYPES=application/pdf,image/jpeg,image/png'
  printf '%s\n' 'EXTRACTION_PROVIDER=openrouter'
  printf '%s\n' 'OPENROUTER_BASE_URL=https://openrouter.ai/api/v1'
  printf '%s\n' 'OPENROUTER_MODEL=openai/gpt-4o-mini'
  printf 'OPENROUTER_API_KEY=%s\n' "$(get_secret openrouter-api-key)"
} >/opt/outurn/.env

chmod 600 /opt/outurn/.env
chown "${ADMIN_USER}:${ADMIN_USER}" /opt/outurn/.env

cat >/etc/caddy/Caddyfile <<CADDY
http://${PUBLIC_DOMAIN} {
  redir https://${PUBLIC_DOMAIN}{uri} permanent
}

https://${PUBLIC_DOMAIN} {
  reverse_proxy 127.0.0.1:3000
}
CADDY

install -m 0755 /opt/outurn/infra/outurn-deploy.sh /usr/local/sbin/outurn-deploy
install -m 0644 /opt/outurn/infra/outurn-deploy.service /etc/systemd/system/outurn-deploy.service
install -m 0644 /opt/outurn/infra/outurn-deploy.timer /etc/systemd/system/outurn-deploy.timer

caddy validate --config /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl restart caddy
systemctl enable --now outurn-deploy.timer
systemctl start outurn-deploy.service

printf 'Deployment finalization completed.\n'
systemctl is-active caddy
ss -lntp | grep -E ':(80|443|3000)\\b' || true
docker compose -f /opt/outurn/docker-compose.prod.yml ps
