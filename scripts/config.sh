# Sourced by the other scripts: loads the settings (environment, then config.env, then
# defaults; see octopus/config.py) and puts BIN_DIR (default ~/.local/bin), where
# install-tools.sh puts tools, on PATH. Works when sourced from bash or zsh (macOS's default shell).
if [ -n "${ZSH_VERSION:-}" ]; then _config_sh="${(%):-%x}"; else _config_sh="${BASH_SOURCE[0]}"; fi
ROOT="$(cd "$(dirname "$_config_sh")/.." && pwd)"
unset _config_sh
eval "$(python3 "$ROOT/octopus/config.py" shell)"
export PATH="$BIN_DIR:$PATH"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
k() { kubectl --context "${KUBE_CONTEXT:?settings not loaded}" "$@"; }  # always the demo cluster, never the current context
