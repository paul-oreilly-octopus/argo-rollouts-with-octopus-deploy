# Sourced by the other scripts: loads the settings (environment, then config.env, then
# defaults; see octopus/config.py) and puts BIN_DIR (default ~/.local/bin), where
# install-tools.sh puts tools, on PATH.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
eval "$(python3 "$ROOT/octopus/config.py" shell)"
export PATH="$BIN_DIR:$PATH"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
k() { kubectl --context "$KUBE_CONTEXT" "$@"; }  # always the demo cluster, never the current context
