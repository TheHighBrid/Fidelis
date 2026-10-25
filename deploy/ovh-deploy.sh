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
  USER="${3:-ubuntu}"

  printf 'Connecting to OVHcloud VPS at %s@%s...\n' "$USER" "$HOST"

  # Sync repository to remote server
  ssh -o StrictHostKeyChecking=no "$USER@$HOST" "mkdir -p /home/$USER/fidelis"
  rsync -avz --exclude='.git' --exclude='.venv' --exclude='dist' ./ "$USER@$HOST:/home/$USER/fidelis/"

  # Run remote deployment
  ssh -t "$USER@$HOST" "cd /home/$USER/fidelis && sudo bash deploy/ovh-deploy.sh local"
  exit 0
fi

if [[ "$MODE" == "local" ]]; then
  printf '=== Fidelis OVHcloud Production Installer ===\n'

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

  # 2. Configure firewall for port 8080 (and standard web ports)
  if command -v ufw >/dev/null 2>&1; then
    printf 'Opening firewall ports (80, 443, 8080)...\n'
    ufw allow 80/tcp || true
    ufw allow 443/tcp || true
    ufw allow 8080/tcp || true
  fi

  # 3. Build and launch container
  printf 'Building and launching Fidelis Studio container...\n'
  docker compose build
  docker compose up -d

  printf '\n=======================================================\n'
  printf ' Fidelis Studio is now running on your OVH VPS!\n'
  printf ' URL: http://%s:8080\n' "$(curl -s https://api.ipify.org || hostname -I | awk '{print $1}')"
  printf '=======================================================\n'
  exit 0
fi

usage
