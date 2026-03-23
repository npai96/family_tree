#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: deploy.sh <release_sha> <domain>"
  exit 1
fi

RELEASE_SHA="$1"
DOMAIN="$2"

APP_ROOT="$HOME/apps/family_tree"
RELEASE_DIR="$APP_ROOT/releases/$RELEASE_SHA"
CURRENT_DIR="$APP_ROOT/current"
ARCHIVE_PATH="/tmp/family-tree-release.tgz"
DATA_DIR="$HOME/family_tree_data/data"
MEDIA_DIR="$HOME/family_tree_data/media"

mkdir -p "$RELEASE_DIR" "$DATA_DIR" "$MEDIA_DIR"

tar -xzf "$ARCHIVE_PATH" -C "$RELEASE_DIR"
ln -sfn "$RELEASE_DIR" "$CURRENT_DIR"

cat > "$CURRENT_DIR/.env" <<ENVVARS
DOMAIN=$DOMAIN
ALLOW_LEGACY_X_USER_ID=false
DATA_DIR=$DATA_DIR
MEDIA_DIR=$MEDIA_DIR
ENVVARS

cd "$CURRENT_DIR"
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans

docker compose -f docker-compose.prod.yml ps
