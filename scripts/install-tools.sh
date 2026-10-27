#!/usr/bin/env bash
# Checks the prerequisites and installs any missing CLI tools into ~/.local/bin (no sudo):
# kind, kubectl, helm and the kubectl-argo-rollouts plugin. Tools already on PATH are left
# alone. Linux (including WSL 2) and macOS, amd64 or arm64.
set -euo pipefail

KIND_VERSION="${KIND_VERSION:-v0.33.0}"
KUBECTL_VERSION="${KUBECTL_VERSION:-v1.37.0}"
HELM_VERSION="${HELM_VERSION:-v3.18.5}"
ARGO_ROLLOUTS_VERSION="${ARGO_ROLLOUTS_VERSION:-v1.10.0}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
export PATH="$BIN_DIR:$PATH"

for cmd in docker python3 curl tar; do
  command -v "$cmd" >/dev/null || { echo "ERROR: $cmd is required but not installed." >&2; exit 1; }
done
docker info >/dev/null 2>&1 || {
  echo "ERROR: can't reach Docker. Start Docker (on WSL: enable Docker Desktop's WSL integration for this distro)." >&2
  exit 1
}

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$(uname -m)" in
  x86_64 | amd64) arch=amd64 ;;
  aarch64 | arm64) arch=arm64 ;;
  *) echo "ERROR: unsupported CPU architecture $(uname -m)" >&2; exit 1 ;;
esac
[[ "$os" == linux || "$os" == darwin ]] || { echo "ERROR: unsupported OS $os (use Linux, WSL 2 or macOS)" >&2; exit 1; }

mkdir -p "$BIN_DIR"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

fetch() {  # fetch <name> <url>: download a single binary into BIN_DIR
  echo "==> Installing $1 to $BIN_DIR"
  curl -fsSLo "$tmp/$1" "$2"
  install -m 0755 "$tmp/$1" "$BIN_DIR/$1"
}

command -v kind >/dev/null || fetch kind "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-${os}-${arch}"
command -v kubectl >/dev/null || fetch kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/${os}/${arch}/kubectl"
command -v kubectl-argo-rollouts >/dev/null || fetch kubectl-argo-rollouts \
  "https://github.com/argoproj/argo-rollouts/releases/download/${ARGO_ROLLOUTS_VERSION}/kubectl-argo-rollouts-${os}-${arch}"
if ! command -v helm >/dev/null; then
  echo "==> Installing helm to $BIN_DIR"
  curl -fsSL "https://get.helm.sh/helm-${HELM_VERSION}-${os}-${arch}.tar.gz" | tar -xz -C "$tmp"
  install -m 0755 "$tmp/${os}-${arch}/helm" "$BIN_DIR/helm"
fi

case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "NOTE: add $BIN_DIR to your PATH to use these tools directly." ;; esac
echo "kind:    $(kind version)"
echo "kubectl: $(kubectl version --client 2>/dev/null | head -1)"
echo "helm:    $(helm version --short)"
echo "kubectl-argo-rollouts: $(kubectl-argo-rollouts version --short)"
echo "python3: $(python3 --version)"
