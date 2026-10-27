#!/usr/bin/env bash
# Installs the Octopus Kubernetes agent (with the Kubernetes monitor) into the demo cluster,
# registered as deployment target AGENT_NAME in the demo space, in every demo environment,
# with target tag OCTOPUS_TARGET_TAG. The agent polls Octopus, so the cluster needs no
# inbound access. Re-runnable (helm upgrade).
#
# The API key goes into a Kubernetes Secret, read from the key file, so it never appears on
# a command line or in the Helm release's values.
set -euo pipefail
source "$(dirname "$0")/config.sh"

RELEASE="$AGENT_NAME"
NAMESPACE="$AGENT_NAMESPACE"

# A target with this name but no agent installed is left over from an earlier cluster.
if ! helm status "$RELEASE" -n "$NAMESPACE" --kube-context "$KUBE_CONTEXT" >/dev/null 2>&1; then
  python3 "$ROOT/octopus/agent.py" remove-stale
fi

k create namespace "$NAMESPACE" --dry-run=client -o yaml | k apply -f -
# api-key: agent registration; SERVER_ACCESS_TOKEN: Kubernetes monitor registration.
k create secret generic octopus-agent-api-key -n "$NAMESPACE" \
  --from-file=api-key=<(tr -d '\r\n' < "$OCTOPUS_API_KEY_FILE") \
  --from-file=SERVER_ACCESS_TOKEN=<(tr -d '\r\n' < "$OCTOPUS_API_KEY_FILE") \
  --dry-run=client -o yaml | k apply -f -

values="$(mktemp)"
trap 'rm -f "$values"' EXIT
python3 "$ROOT/octopus/agent.py" values > "$values"

step "Installing Octopus Kubernetes agent chart $AGENT_CHART_VERSION as '$AGENT_NAME'"
helm upgrade --install --atomic --timeout 10m \
  --kube-context "$KUBE_CONTEXT" --namespace "$NAMESPACE" \
  --version "$AGENT_CHART_VERSION" -f "$values" \
  "$RELEASE" oci://registry-1.docker.io/octopusdeploy/kubernetes-agent

k get pods -n "$NAMESPACE"
