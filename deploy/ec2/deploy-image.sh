#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: deploy-image.sh <release_sha> <domain> <app_image>"
  exit 1
fi

RELEASE_SHA="$1"
DOMAIN="$2"
APP_IMAGE="$3"

resolve_home_dir() {
  local candidate=""
  for candidate in \
    "${HOME:-}" \
    "/home/ubuntu" \
    "$(getent passwd "$(id -un)" | cut -d: -f6 2>/dev/null || true)" \
    "/root"
  do
    if [[ -n "$candidate" && -d "$candidate/apps/family_tree" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done

  for candidate in \
    "${HOME:-}" \
    "/home/ubuntu" \
    "$(getent passwd "$(id -un)" | cut -d: -f6 2>/dev/null || true)" \
    "/root"
  do
    if [[ -n "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
}

HOME_DIR="$(resolve_home_dir)"

APP_ROOT="$HOME_DIR/apps/family_tree"
CURRENT_DIR="$APP_ROOT/current"
DATA_DIR="$HOME_DIR/family_tree_data/data"
MEDIA_DIR="$HOME_DIR/family_tree_data/media"
REGISTRY=""
AWS_REGION=""

if [[ ! -d "$CURRENT_DIR" ]]; then
  echo "Expected config directory at $CURRENT_DIR"
  echo "Run the SSH-based deploy once first so compose files exist on the server."
  exit 1
fi

mkdir -p "$DATA_DIR" "$MEDIA_DIR"

if [[ -d "$DATA_DIR/mvp.db" ]]; then
  echo "Found directory at $DATA_DIR/mvp.db from older bind-mount behavior; removing it so SQLite can create a file."
  rmdir "$DATA_DIR/mvp.db" 2>/dev/null || true
fi

if [[ "$APP_IMAGE" == *.dkr.ecr.*.amazonaws.com/* ]]; then
  if ! command -v aws >/dev/null 2>&1; then
    echo "aws CLI is required for ECR-backed deploys. Re-run deploy/ec2/bootstrap.sh on the server."
    exit 1
  fi

  REGISTRY="${APP_IMAGE%%/*}"
  AWS_REGION="$(printf '%s' "$REGISTRY" | awk -F'.' '{print $(NF-2)}')"

  if [[ -z "$AWS_REGION" ]]; then
    echo "Could not infer AWS region from image reference: $APP_IMAGE"
    exit 1
  fi

  aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$REGISTRY"
fi

docker pull "$APP_IMAGE"

cat > "$CURRENT_DIR/.env" <<ENVVARS
DOMAIN=$DOMAIN
APP_IMAGE=$APP_IMAGE
ALLOW_LEGACY_X_USER_ID=false
DATA_DIR=$DATA_DIR
MEDIA_DIR=$MEDIA_DIR
ENVVARS

cd "$CURRENT_DIR"
docker compose -f docker-compose.prod.yml up -d --remove-orphans
docker compose -f docker-compose.prod.yml ps
