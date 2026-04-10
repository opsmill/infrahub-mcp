#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:?Usage: sync-versions.sh <version>}"

echo "Syncing version to: $VERSION"

# Update pyproject.toml
if [ -f "pyproject.toml" ]; then
  sed -i.bak "s/^version = .*/version = \"$VERSION\"/" pyproject.toml && rm -f pyproject.toml.bak
  echo "  Updated: pyproject.toml"
fi

# Update server.json (top-level .version AND .packages[0].version)
if [ -f "server.json" ]; then
  jq --arg v "$VERSION" \
    '.version = $v | .packages[0].version = $v' server.json > /tmp/server.json \
    && mv /tmp/server.json server.json
  echo "  Updated: server.json"
fi

echo "Done."
