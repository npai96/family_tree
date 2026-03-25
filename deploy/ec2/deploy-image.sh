#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: deploy-image.sh <release_sha> <domain> <app_image>"
  exit 1
fi

RELEASE_SHA="$1"
DOMAIN="$2"
APP_IMAGE="$3"

APP_ROOT="$HOME/apps/family_tree"
CURRENT_DIR="$APP_ROOT/current"
DATA_DIR="$HOME/family_tree_data/data"
MEDIA_DIR="$HOME/family_tree_data/media"

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
