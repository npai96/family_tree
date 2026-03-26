#!/usr/bin/env bash
set -euo pipefail

# Ubuntu 22.04+ bootstrap for cheap single-instance deployment
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release unzip awscli

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

sudo usermod -aG docker "$USER" || true

mkdir -p "$HOME/apps/family_tree/releases"
mkdir -p "$HOME/family_tree_data/data"
mkdir -p "$HOME/family_tree_data/media"

echo "Bootstrap complete. Re-login once so docker group applies."
