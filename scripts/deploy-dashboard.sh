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
