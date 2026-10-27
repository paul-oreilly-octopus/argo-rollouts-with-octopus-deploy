#!/usr/bin/env bash
# Builds the colour-demo image, loads it into the kind nodes, and (re)deploys the dashboard.
# The Octopus projects deploy the same image (Octopus variable "Image").
set -euo pipefail
source "$(dirname "$0")/config.sh"

IMAGE="${IMAGE:-colour-demo:1.2.0}"

step "Building $IMAGE"
docker build -t "$IMAGE" "$ROOT/app"

step "Loading $IMAGE into kind cluster '$CLUSTER_NAME'"
kind load docker-image "$IMAGE" --name "$CLUSTER_NAME"

step "Deploying the dashboard"
k apply -f "$ROOT/k8s/dashboard.yaml"
k rollout restart -n colour-demo-dashboard deployment/colour-demo-dashboard
k rollout status -n colour-demo-dashboard deployment/colour-demo-dashboard --timeout 120s

url="$("$ROOT/scripts/dashboard-url.sh")"
step "Checking the dashboard at $url"
for _ in $(seq 30); do  # the ingress can take a few seconds to pick up the pod
  [[ "$(curl -s -o /dev/null -w '%{http_code}' "$url" || true)" == 200 ]] && { echo "Dashboard: $url"; exit 0; }
  sleep 1
done
echo "WARNING: $url didn't respond with 200 after 30 seconds. Check: kubectl --context $KUBE_CONTEXT -n ingress-nginx get pods" >&2
