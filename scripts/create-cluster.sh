#!/usr/bin/env bash
# Creates the kind cluster (1 control plane + 2 workers), then installs ingress-nginx and
# Argo Rollouts. Re-runnable: an existing cluster with the same name is reused.
set -euo pipefail
source "$(dirname "$0")/config.sh"

port_in_use() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }  # something accepts connections on it

if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
  echo "Cluster '$CLUSTER_NAME' already exists; reusing it."
  # Host ports are fixed when the cluster is created: changing them in config.env needs a new cluster.
  mapped="$(docker port "$CLUSTER_NAME-control-plane" 80/tcp 2>/dev/null | head -1)"
  if [[ -n "$mapped" && "${mapped##*:}" != "$INGRESS_HTTP_PORT" ]]; then
    echo "ERROR: the cluster's dashboard port is ${mapped##*:}, but INGRESS_HTTP_PORT is $INGRESS_HTTP_PORT." >&2
    echo "Set INGRESS_HTTP_PORT back to ${mapped##*:}, or run ./uninstall.sh and then ./install.sh to recreate the cluster." >&2
    exit 1
  fi
else
  for setting in INGRESS_HTTP_PORT INGRESS_HTTPS_PORT; do
    port="${!setting}"
    if port_in_use "$port"; then
      echo "ERROR: port $port ($setting) is already in use on this machine." >&2
      echo "Set $setting in config.env to a free port (e.g. 8080 for HTTP, 8443 for HTTPS), then run ./install.sh again." >&2
      exit 1
    fi
  done
  step "Creating kind cluster '$CLUSTER_NAME' (ingress on ports $INGRESS_HTTP_PORT/$INGRESS_HTTPS_PORT)"
  # kind switches the current kubectl context to the new cluster; put the user's back afterwards
  # (these scripts always use --context $KUBE_CONTEXT).
  previous_context="$(kubectl config current-context 2>/dev/null || true)"
  [[ -z "$previous_context" ]] || trap 'kubectl config use-context "$previous_context" >/dev/null' EXIT
  # The ingress controller runs on the control-plane node (ingress-ready=true), whose ports
  # 80/443 are mapped to the host, so ingresses work at http://*.localtest.me (127.0.0.1).
  kind create cluster --name "$CLUSTER_NAME" --wait 120s --config - <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    kubeadmConfigPatches:
      - |
        kind: InitConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            node-labels: "ingress-ready=true"
    extraPortMappings:
      - {containerPort: 80, hostPort: $INGRESS_HTTP_PORT, protocol: TCP}
      - {containerPort: 443, hostPort: $INGRESS_HTTPS_PORT, protocol: TCP}
  - role: worker
  - role: worker
EOF
fi

step "Installing ingress-nginx ($INGRESS_NGINX_VERSION)"
# ingress-nginx is archived upstream; controller-v1.15.1 is its final release. Fine for a local demo.
k apply -f "https://raw.githubusercontent.com/kubernetes/ingress-nginx/${INGRESS_NGINX_VERSION}/deploy/static/provider/kind/deploy.yaml"
k wait -n ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=180s

step "Installing Argo Rollouts ($ARGO_ROLLOUTS_VERSION)"
k create namespace argo-rollouts --dry-run=client -o yaml | k apply -f -
# Server-side apply: the CRDs exceed the 256KB last-applied-configuration annotation limit.
k apply --server-side --force-conflicts -n argo-rollouts \
  -f "https://github.com/argoproj/argo-rollouts/releases/download/${ARGO_ROLLOUTS_VERSION}/install.yaml"
k rollout status -n argo-rollouts deployment/argo-rollouts --timeout=180s

k get nodes
