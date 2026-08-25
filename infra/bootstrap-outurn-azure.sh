#!/usr/bin/env bash
set -Eeuo pipefail

SUBSCRIPTION_ID="${AZURE_SUBSCRIPTION_ID:-3de0660a-4fe0-476c-8815-aa2f05060cad}"
LOCATION="${AZURE_LOCATION:-indonesiacentral}"
RESOURCE_GROUP="${OUTURN_RESOURCE_GROUP:-rg-outurn-test}"
VM_NAME="${OUTURN_VM_NAME:-vm-outurn-test}"
VM_SIZE="${OUTURN_VM_SIZE:-Standard_B2ats_v2}"
KEY_VAULT="${OUTURN_KEY_VAULT:-}"
ADMIN_USER="${OUTURN_ADMIN_USER:-outurnadmin}"
REPO_URL="https://github.com/Compfest18-AgusLaparBuk/Outurn.git"
PUBLIC_DOMAIN=""

command -v az >/dev/null
command -v openssl >/dev/null

az account set --subscription "${SUBSCRIPTION_ID}"
for namespace in Microsoft.KeyVault Microsoft.Compute Microsoft.Network; do
  az provider register --namespace "${namespace}" --wait >/dev/null
done

az group create --name "${RESOURCE_GROUP}" --location "${LOCATION}" --output none

if [[ -z "${KEY_VAULT}" ]]; then
  KEY_VAULT="$(az keyvault list --resource-group "${RESOURCE_GROUP}" --query "[?starts_with(name, 'kv-outurn-test-')].name | [0]" -o tsv)"
  if [[ -z "${KEY_VAULT}" ]]; then
    KEY_VAULT="kv-outurn-test-$(openssl rand -hex 3)"
  fi
fi

ARM_ACCESS_TOKEN="$(az account get-access-token --resource https://management.azure.com --query accessToken -o tsv)"
export ARM_ACCESS_TOKEN
USER_OBJECT_ID="$(python3 - <<'PY'
import base64
import json
import os

payload = os.environ["ARM_ACCESS_TOKEN"].split(".")[1]
payload += "=" * (-len(payload) % 4)
claims = json.loads(base64.urlsafe_b64decode(payload))
print(claims["oid"])
PY
)"
unset ARM_ACCESS_TOKEN

if ! az keyvault show --name "${KEY_VAULT}" --resource-group "${RESOURCE_GROUP}" --output none 2>/dev/null; then
  az keyvault create \
    --name "${KEY_VAULT}" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --enable-rbac-authorization true \
    --output none
fi

KEY_VAULT_ID="$(az keyvault show --name "${KEY_VAULT}" --resource-group "${RESOURCE_GROUP}" --query id -o tsv)"
USER_KV_ROLE_COUNT="$(az role assignment list --assignee-object-id "${USER_OBJECT_ID}" --scope "${KEY_VAULT_ID}" --query "[?roleDefinitionName=='Key Vault Secrets Officer'] | length(@)" -o tsv)"
if [[ "${USER_KV_ROLE_COUNT}" != "1" ]]; then
  az role assignment create \
    --assignee-object-id "${USER_OBJECT_ID}" \
    --assignee-principal-type User \
    --role "Key Vault Secrets Officer" \
    --scope "${KEY_VAULT_ID}" \
    --output none
fi

store_secret() {
  local name="$1"
  local prompt="$2"
  local value
  if ! read -r -s -p "${prompt}: " value </dev/tty; then
    printf '\nUnable to read secret input from the terminal.\n' >&2
    exit 1
  fi
  printf '\n'
  if [[ -z "${value}" ]]; then
    printf 'Secret input cannot be empty.\n' >&2
    exit 1
  fi
  az keyvault secret set --vault-name "${KEY_VAULT}" --name "${name}" --value "${value}" --output none
  unset value
}

store_secret openrouter-api-key "OpenRouter API key (hidden)"

for secret_name in app-api-key webhook-secret-key postgres-password; do
  secret_value="$(openssl rand -hex 32)"
  az keyvault secret set --vault-name "${KEY_VAULT}" --name "${secret_name}" --value "${secret_value}" --output none
  unset secret_value
done

cloud_init="$(mktemp)"
trap 'rm -f "${cloud_init}"' EXIT
cat >"${cloud_init}" <<'CLOUD_INIT'
#cloud-config
package_update: true
packages:
  - ca-certificates
  - curl
  - git
  - docker.io
  - docker-compose-v2
  - apt-transport-https
  - debian-archive-keyring
  - debian-keyring
  - fail2ban
  - gnupg
  - ufw
  - python3
runcmd:
  - [ bash, -lc, "id -u outurnadmin >/dev/null 2>&1 || useradd --create-home --shell /bin/bash outurnadmin" ]
  - [ bash, -lc, "usermod -aG docker outurnadmin; systemctl enable --now docker" ]
  - [ bash, -lc, "fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048; chmod 600 /swapfile; mkswap /swapfile; swapon /swapfile; grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab" ]
  - [ bash, -lc, "ufw default deny incoming; ufw default allow outgoing; ufw allow 80/tcp; ufw allow 443/tcp; ufw --force enable; systemctl enable --now fail2ban" ]
  - [ bash, -lc, "curl -sL https://aka.ms/InstallAzureCLIDeb | bash" ]
  - [ bash, -lc, "curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg; curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list; apt-get update; apt-get install -y caddy" ]
  - [ bash, -lc, "install -d -o outurnadmin -g outurnadmin -m 0700 /opt/outurn /var/lib/outurn" ]
CLOUD_INIT

az vm create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${VM_NAME}" \
  --image Ubuntu2204 \
  --size "${VM_SIZE}" \
  --admin-username "${ADMIN_USER}" \
  --generate-ssh-keys \
  --assign-identity \
  --public-ip-sku Standard \
  --os-disk-size-gb 32 \
  --storage-sku Standard_LRS \
  --custom-data "${cloud_init}" \
  --output none

az vm open-port --resource-group "${RESOURCE_GROUP}" --name "${VM_NAME}" --port 80 --priority 1001 --output none
az vm open-port --resource-group "${RESOURCE_GROUP}" --name "${VM_NAME}" --port 443 --priority 1002 --output none

VM_PRINCIPAL_ID="$(az vm show --resource-group "${RESOURCE_GROUP}" --name "${VM_NAME}" --query identity.principalId -o tsv)"
az role assignment create \
  --assignee-object-id "${VM_PRINCIPAL_ID}" \
  --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" \
  --scope "${KEY_VAULT_ID}" \
  --output none

PUBLIC_IP="$(az vm show --show-details --resource-group "${RESOURCE_GROUP}" --name "${VM_NAME}" --query publicIps -o tsv)"
PUBLIC_DOMAIN="${PUBLIC_IP}.sslip.io"
az keyvault secret set --vault-name "${KEY_VAULT}" --name app-public-origin --value "https://${PUBLIC_DOMAIN}" --output none

sleep 30
az vm run-command invoke \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${VM_NAME}" \
  --command-id RunShellScript \
  --scripts "$(cat <<REMOTE_SCRIPT
set -Eeuo pipefail
until command -v az >/dev/null 2>&1 && command -v docker >/dev/null 2>&1 && command -v caddy >/dev/null 2>&1; do sleep 5; done
az login --identity --allow-no-subscriptions >/dev/null
install -d -o outurnadmin -g outurnadmin -m 0700 /opt/outurn /var/lib/outurn
if [[ ! -d /opt/outurn/.git ]]; then
  git clone --branch main --depth 1 ${REPO_URL} /opt/outurn
else
  git -C /opt/outurn fetch --quiet origin main
  git -C /opt/outurn checkout -B main origin/main
fi
get_secret() { az keyvault secret show --vault-name ${KEY_VAULT} --name "\$1" --query value -o tsv; }
{
  printf '%s\\n' 'APP_ENV=production'
  printf 'APP_PUBLIC_ORIGIN=%s\\n' "\$(get_secret app-public-origin)"
  printf 'CORS_ORIGINS=%s\\n' "\$(get_secret app-public-origin)"
  printf 'APP_API_KEY=%s\\n' "\$(get_secret app-api-key)"
  printf 'WEBHOOK_SECRET_KEY=%s\\n' "\$(get_secret webhook-secret-key)"
  printf 'POSTGRES_PASSWORD=%s\\n' "\$(get_secret postgres-password)"
  printf '%s\\n' 'DATABASE_URL=postgresql+psycopg://outurn:unused@postgres:5432/outurn'
  printf '%s\\n' 'COOKIE_SECURE=true'
  printf '%s\\n' 'DOCUMENT_STORAGE_ROOT=/data/documents'
  printf '%s\\n' 'DOCUMENT_ALLOWED_MIME_TYPES=application/pdf,image/jpeg,image/png'
  printf '%s\\n' 'EXTRACTION_PROVIDER=openrouter'
  printf '%s\\n' 'OPENROUTER_BASE_URL=https://openrouter.ai/api/v1'
  printf '%s\\n' 'OPENROUTER_MODEL=openai/gpt-4o-mini'
  printf 'OPENROUTER_API_KEY=%s\\n' "\$(get_secret openrouter-api-key)"
} >/opt/outurn/.env
chmod 600 /opt/outurn/.env
cat >/etc/caddy/Caddyfile <<CADDY
${PUBLIC_DOMAIN} {
  reverse_proxy 127.0.0.1:3000
}
CADDY
systemctl enable --now caddy
install -m 0755 /opt/outurn/infra/outurn-deploy.sh /usr/local/sbin/outurn-deploy
install -m 0644 /opt/outurn/infra/outurn-deploy.service /etc/systemd/system/outurn-deploy.service
install -m 0644 /opt/outurn/infra/outurn-deploy.timer /etc/systemd/system/outurn-deploy.timer
chown -R outurnadmin:outurnadmin /opt/outurn /var/lib/outurn
systemctl daemon-reload
systemctl enable --now outurn-deploy.timer
systemctl start outurn-deploy.service
REMOTE_SCRIPT
)" \
  --output none

printf 'Resource group: %s\nKey Vault: %s\nVM: %s\nURL: https://%s\nAdmin: admin@outurn.local\nOperator: operator@outurn.local\n' \
  "${RESOURCE_GROUP}" "${KEY_VAULT}" "${VM_NAME}" "${PUBLIC_DOMAIN}"
