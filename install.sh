#!/usr/bin/env bash
# Sets up the whole demo: tools, kind cluster, Octopus space, Kubernetes agent, dashboard,
# Octopus projects and the Argo Rollouts webhook. Every step is re-runnable, so after
# changing config.env or pulling an update, run it again.
#
#   ./install.sh                 # everything
#   ./install.sh octopus argo    # only these steps (see STEPS)
set -euo pipefail
cd "$(dirname "$0")"

STEPS=(check tools cluster space agent dashboard octopus argo)
describe() {
  case "$1" in
    check) echo "Check settings" ;;
    tools) echo "Install missing tools (kind, kubectl, helm, kubectl-argo-rollouts)" ;;
    cluster) echo "Create the kind cluster with ingress-nginx and Argo Rollouts" ;;
    space) echo "Find the Octopus space (or create it) and add its environments" ;;
    agent) echo "Install the Octopus Kubernetes agent" ;;
    dashboard) echo "Build the colour-demo image and deploy the dashboard" ;;
    octopus) echo "Create the Octopus projects and runbooks" ;;
    argo) echo "Connect Argo Rollouts notifications to Octopus" ;;
  esac
}
run() {
  case "$1" in
    check) python3 octopus/config.py check ;;
    tools) scripts/install-tools.sh ;;
    cluster) scripts/create-cluster.sh ;;
    space) python3 octopus/setup_space.py ;;
    agent) scripts/install-octopus-agent.sh ;;
    dashboard) scripts/deploy-dashboard.sh ;;
    octopus) python3 octopus/setup_octopus.py ;;
    argo) python3 octopus/setup_argo_notifications.py ;;
    *) echo "Unknown step '$1'. Steps: ${STEPS[*]}" >&2; exit 1 ;;
  esac
}

command -v python3 >/dev/null || { echo "ERROR: python3 is required." >&2; exit 1; }
# (Not "${selected[@]}" on an empty array: macOS's bash 3.2 treats that as unbound under set -u.)
if [[ $# -gt 0 ]]; then selected=("$@"); else selected=("${STEPS[@]}"); fi
if [[ " ${selected[*]} " != *" check "* ]]; then  # always validate the settings first
  out="$(run check)" || { echo "$out"; exit 1; }
fi

for s in "${selected[@]}"; do
  printf '\n\033[1;34m### %s: %s\033[0m\n' "$s" "$(describe "$s")"
  run "$s"
done

source scripts/config.sh
cat <<EOF

Done. Next:
  Dashboard:   $(scripts/dashboard-url.sh)
  Octopus:     $OCTOPUS_URL (space "$OCTOPUS_SPACE_NAME", projects "Colour Demo - Canary" and "Colour Demo - Blue-Green")
  First deploy: python3 octopus/deploy.py canary        (and: python3 octopus/deploy.py bluegreen)
  Rollback:    python3 octopus/deploy.py canary --colour red
  See README.md for the demo walkthrough and stress tests.
EOF
