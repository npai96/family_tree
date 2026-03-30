#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: deploy.sh <release_sha> <domain> <app_image>"
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
RELEASE_DIR="$APP_ROOT/releases/$RELEASE_SHA"
CURRENT_DIR="$APP_ROOT/current"
CONFIG_ARCHIVE_PATH="/tmp/family-tree-config.tgz"
IMAGE_ARCHIVE_PATH="/tmp/family-tree-image.tar"
DATA_DIR="$HOME_DIR/family_tree_data/data"
MEDIA_DIR="$HOME_DIR/family_tree_data/media"

mkdir -p "$RELEASE_DIR" "$DATA_DIR" "$MEDIA_DIR"

if [[ -d "$DATA_DIR/mvp.db" ]]; then
  echo "Found directory at $DATA_DIR/mvp.db from older bind-mount behavior; removing it so SQLite can create a file."
  rmdir "$DATA_DIR/mvp.db" 2>/dev/null || true
fi

if [[ ! -f "$CONFIG_ARCHIVE_PATH" ]]; then
  echo "Missing config archive at $CONFIG_ARCHIVE_PATH"
  exit 1
fi

if [[ ! -f "$IMAGE_ARCHIVE_PATH" ]]; then
  echo "Missing image archive at $IMAGE_ARCHIVE_PATH"
  exit 1
fi

tar -xzf "$CONFIG_ARCHIVE_PATH" -C "$RELEASE_DIR"
ln -sfn "$RELEASE_DIR" "$CURRENT_DIR"

docker load -i "$IMAGE_ARCHIVE_PATH"

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
