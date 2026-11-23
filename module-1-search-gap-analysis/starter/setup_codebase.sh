#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/ekmungai/python-accounting"
COMMIT="1fcf6ec2e8ed25519f7228401acf5c687bae2015"
TARGET="$(cd "$(dirname "$0")" && pwd)/python-accounting"

if [ -d "$TARGET/.git" ]; then
  echo "python-accounting is already set up at $TARGET"
  exit 0
fi

git init --quiet "$TARGET"
git -C "$TARGET" remote add origin "$REPO_URL"
git -C "$TARGET" fetch --quiet --depth 1 origin "$COMMIT"
git -C "$TARGET" checkout --quiet FETCH_HEAD
echo "python-accounting is ready at $TARGET ($(git -C "$TARGET" rev-parse --short HEAD))"
