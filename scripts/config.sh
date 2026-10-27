# Sourced by the other scripts: loads the settings (environment, then config.env, then
# defaults; see octopus/config.py) and puts ~/.local/bin, where install-tools.sh puts tools,
# on PATH.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"
eval "$(python3 "$ROOT/octopus/config.py" shell)"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
k() { kubectl --context "$KUBE_CONTEXT" "$@"; }  # always the demo cluster, never the current context
