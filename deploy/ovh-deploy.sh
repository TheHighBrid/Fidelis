#!/usr/bin/env bash
# deploy/ovh-deploy.sh - Automated Deployment Script for OVHcloud VPS & Public Cloud
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./deploy/ovh-deploy.sh local                 # Deploy locally on the OVH VPS machine directly
  ./deploy/ovh-deploy.sh remote HOST [USER]    # Deploy from your workstation to an OVH VPS via SSH

Examples:
  ./deploy/ovh-deploy.sh remote 51.210.12.34 ubuntu
  ./deploy/ovh-deploy.sh remote vps-abc123.vps.ovh.net debian
EOF
  exit 1
}

MODE="${1:-}"
[[ -n "$MODE" ]] || usage

if [[ "$MODE" == "remote" ]]; then
  HOST="${2:-}"
  [[ -n "$HOST" ]] || usage
  deploy_login="${3:-ubuntu}"

  printf 'Connecting to OVHcloud VPS at %s@%s...\n' "$deploy_login" "$HOST"

  # Sync repository to remote server
  ssh "$deploy_login@$HOST" "mkdir -p /home/$deploy_login/fidelis"
  rsync -avz --exclude='.git' --exclude='.venv' --exclude='dist' ./ "$deploy_login@$HOST:/home/$deploy_login/fidelis/"

  # Run remote deployment
  ssh -t "$deploy_login@$HOST" "cd /home/$deploy_login/fidelis && sudo bash deploy/ovh-deploy.sh local"
  exit 0
fi

if [[ "$MODE" == "local" ]]; then
  printf '=== Fidelis local-only development installer ===\n'

  # 1. Ensure Docker & Compose are installed
  if ! command -v docker >/dev/null 2>&1; then
    printf 'Installing Docker and Compose plugin...\n'
    apt-get update
    apt-get install -y ca-certificates curl gnupg lsb-release
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/$(lsb_release -is | tr '[:upper:]' '[:lower:]')/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$(lsb_release -is | tr '[:upper:]' '[:lower:]') $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  fi

  # Host loopback publication is defined in Compose. Do not open public firewall
  # ports or imply that this development service is authenticated for public use.

  # 3. Build and launch container
  printf 'Building and launching Fidelis Studio container...\n'
  docker compose down 2>/dev/null || true
  docker compose build
  docker compose up -d

  printf '\n=======================================================\n'
  printf ' Fidelis development service is bound to host loopback.\n'
  printf ' Local URL: http://127.0.0.1:8080\n'
  printf ' For a remote VPS, use an explicit SSH tunnel to that loopback port.\n'
  printf ' Regional editing requires same-host loopback access; Docker bridge clients remain restricted.\n'
  printf ' This is not an authenticated public deployment.\n'
  printf '=======================================================\n'
  exit 0
fi

usage
