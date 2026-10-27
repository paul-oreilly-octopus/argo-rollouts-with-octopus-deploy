# Octopus step: compares the release Octopus is deploying with the release Argo Rollouts
# is actually running (the stable ReplicaSet), and decides whether to deploy at all.
#
# Output variables (Octopus.Action[Check deployed version].Output.*):
#   StableRelease  release of the stable ReplicaSet: what Argo falls back to if this
#                  deployment is aborted. The Apply step records it on the Rollout as
#                  octopus.com/rollback-release, for the Argo Rollouts webhook.
#   NeedsDeploy    True when the Apply and Wait steps should run: never for a deployment
#                  the Argo webhook triggered, and not when the cluster already runs this release.
#   DeployedAt     now (UTC). Recorded on the Rollout as octopus.com/deployed-at; the Argo
#                  webhook ignores aborts older than it.
#
# A deployment the Argo webhook triggered (ArgoRollback.Triggered=True) is a record, not a
# deployment: it only reads the cluster and reports what's running, so it's quick and can't
# interfere with newer deployments. It succeeds when the cluster runs its release, and fails
# when it doesn't (the notification is out of date), without touching the cluster either way.
ns="#{Namespace}"
name="#{RolloutName}"
release="#{Octopus.Release.Number}"
# Prompted variables the Argo Rollouts webhook sets (read at runtime: the reason is free text).
triggered="$(get_octopusvariable "ArgoRollback.Triggered")"
aborted_release="$(get_octopusvariable "ArgoRollback.AbortedRelease")"
reason="$(get_octopusvariable "ArgoRollback.Reason")"

highlight() { if declare -F write_highlight >/dev/null; then write_highlight "$1"; else echo "$1"; fi; }
output() { echo "$1=$2"; if declare -F set_octopusvariable >/dev/null; then set_octopusvariable "$1" "$2"; fi; }
get() { kubectl get rollout "$name" -n "$ns" -o jsonpath="$1"; }

# The Octopus release a ReplicaSet runs: its pod template's octopus.com/release
# annotation, or APP_VERSION for ReplicaSets created before the annotation existed.
release_of() {
  local rs="$name-$1" value
  value="$(kubectl get rs "$rs" -n "$ns" -o jsonpath='{.spec.template.metadata.annotations.octopus\.com/release}' 2>/dev/null)"
  [[ -n "$value" ]] || value="$(kubectl get rs "$rs" -n "$ns" \
    -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="APP_VERSION")].value}' 2>/dev/null)"
  echo "$value"
}

output NeedsDeploy False  # until decided below, so a failure here never leads to an apply
output DeployedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [[ "$triggered" == "True" ]]; then
  highlight "Triggered by Argo Rollouts: it aborted release ${aborted_release:-?} and rolled $name back to $release.${reason:+ Reason: $reason}"
fi

if ! kubectl get rollout "$name" -n "$ns" >/dev/null 2>&1; then
  if [[ "$triggered" == "True" ]]; then
    highlight "Rollout $name doesn't exist in $ns; can't confirm release $release is running."
    exit 1
  fi
  echo "Rollout $name doesn't exist yet: first deployment."
  output StableRelease ""
  output NeedsDeploy True
  exit 0
fi

stable_hash="$(get '{.status.stableRS}')"
current_hash="$(get '{.status.currentPodHash}')"
phase="$(get '{.status.phase}')"
stable_release="$(release_of "$stable_hash")"
current_release="$(release_of "$current_hash")"
echo "Cluster: stable=${stable_release:-?} ($stable_hash), desired spec=${current_release:-?} ($current_hash), phase=$phase, aborted=$(get '{.status.abort}')"
output StableRelease "$stable_release"

# Argo-triggered: report what's running and stop. No deployment, no changes to the cluster.
if [[ "$triggered" == "True" ]]; then
  ready="$(get '{.status.readyReplicas}')/$(get '{.spec.replicas}')"
  if [[ "$stable_release" == "$release" ]]; then
    highlight "Recorded without deploying: $name in $ns runs release $release ($ready pods ready, ReplicaSet $name-$stable_hash). Rollout phase: $phase."
    exit 0
  fi
  highlight "Not recording: Argo Rollouts reported a rollback to $release, but $name now runs ${stable_release:-an unknown release}. The notification is out of date."
  exit 1
fi

if [[ -z "$stable_release" || "$stable_release" != "$release" ]]; then
  echo "Release $release isn't what's running; deploying it."
  output NeedsDeploy True
  exit 0
fi

if [[ "$current_hash" == "$stable_hash" && "$phase" == "Healthy" ]]; then
  highlight "Release $release is already running in $ns; nothing to deploy."
  output NeedsDeploy False
  exit 0
fi

# Someone redeployed the running release while the Rollout's spec still describes another
# one (typically one Argo aborted). Point the spec back at the stable
# ReplicaSet's template, like `kubectl argo rollouts undo`: Argo sees the spec matches the
# stable ReplicaSet and goes Healthy without creating pods or re-running analysis.
echo "Pods already run release $release; pointing Rollout $name back at its ReplicaSet $name-$stable_hash."
template="$(kubectl get rs "$name-$stable_hash" -n "$ns" -o jsonpath='{.spec.template}')"
kubectl patch rollout "$name" -n "$ns" --type=json -p "[
  {\"op\": \"replace\", \"path\": \"/spec/template\", \"value\": $template},
  {\"op\": \"remove\", \"path\": \"/spec/template/metadata/labels/rollouts-pod-template-hash\"},
  {\"op\": \"add\", \"path\": \"/metadata/annotations/octopus.com~1release\", \"value\": \"$release\"},
  {\"op\": \"add\", \"path\": \"/metadata/annotations/octopus.com~1deployment\", \"value\": \"#{Octopus.Deployment.Id}\"},
  {\"op\": \"add\", \"path\": \"/metadata/annotations/octopus.com~1rollback-release\", \"value\": \"\"}
]"

for _ in $(seq 1 30); do
  sleep 2
  if [[ "$(get '{.status.currentPodHash}')" == "$stable_hash" && "$(get '{.status.phase}')" == "Healthy" ]]; then
    highlight "Rollout $name is Healthy on release $release (no new pods were created)."
    output NeedsDeploy False
    exit 0
  fi
done
echo "Rollout $name didn't settle on $name-$stable_hash: phase=$(get '{.status.phase}') hash=$(get '{.status.currentPodHash}'). $(get '{.status.message}')"
exit 1
