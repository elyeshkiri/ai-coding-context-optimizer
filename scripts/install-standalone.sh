#!/usr/bin/env sh
set -eu

REPO="elyeshkiri/ai-coding-context-optimizer"
INSTALL_DIR="${ACCO_INSTALL_DIR:-$HOME/.local/bin}"
VERSION="${ACCO_VERSION:-latest}"

case "$(uname -s)" in
  Linux) os="linux" ;;
  Darwin) os="macos" ;;
  *)
    echo "Unsupported OS for this installer. Use 'uv tool install acco'." >&2
    exit 2
    ;;
esac

case "$(uname -m)" in
  x86_64|amd64) arch="x86_64" ;;
  arm64|aarch64) arch="arm64" ;;
  *)
    echo "Unsupported architecture. Use 'uv tool install acco'." >&2
    exit 2
    ;;
esac

if [ "$os" = "linux" ] && [ "$arch" != "x86_64" ]; then
  echo "Linux $arch standalone binary is not published yet. Use 'uv tool install acco'." >&2
  exit 2
fi
if [ "$os" = "macos" ] && [ "$arch" != "arm64" ]; then
  echo "macOS $arch standalone binary is not published yet. Use 'uv tool install acco'." >&2
  exit 2
fi

asset="acco-$os-$arch"
if [ "$VERSION" = "latest" ]; then
  base="https://github.com/$REPO/releases/latest/download"
else
  base="https://github.com/$REPO/releases/download/$VERSION"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
command -v curl >/dev/null 2>&1 || {
  echo "curl is required; alternatively use 'uv tool install acco'." >&2
  exit 2
}

curl -fL "$base/$asset" -o "$tmp/acco"
curl -fL "$base/$asset.sha256" -o "$tmp/acco.sha256"

expected="$(awk '{print $1}' "$tmp/acco.sha256")"
actual="$(python3 - "$tmp/acco" <<'PY'
import hashlib
import pathlib
import sys
print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)"
if [ "$expected" != "$actual" ]; then
  echo "Checksum verification failed." >&2
  exit 1
fi

mkdir -p "$INSTALL_DIR"
chmod 0755 "$tmp/acco"
mv "$tmp/acco" "$INSTALL_DIR/acco"
echo "Installed ACCO to $INSTALL_DIR/acco"
echo "Next: cd /path/to/project && acco setup"
