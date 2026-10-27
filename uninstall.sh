#!/usr/bin/env bash
# Removes the demo.
#
#   ./uninstall.sh                 # delete the kind cluster and its Octopus deployment target
#   ./uninstall.sh --delete-space  # also delete the Octopus space (projects, releases, runbooks:
#                                  # everything in it; needs SpaceDelete)
set -euo pipefail
cd "$(dirname "$0")"
source scripts/config.sh

delete_space=false
case "${1:-}" in
  "") ;;
  --delete-space) delete_space=true ;;
  *) sed -n '2,7p' "$0" >&2; exit 1 ;;
esac

step "Deleting kind cluster '$CLUSTER_NAME'"
kind delete cluster --name "$CLUSTER_NAME"

step "Deleting Octopus deployment target '$AGENT_NAME'"
python3 octopus/cleanup.py target

if $delete_space; then
  step "Deleting Octopus space '$OCTOPUS_SPACE_NAME'"
  python3 octopus/cleanup.py space
fi
