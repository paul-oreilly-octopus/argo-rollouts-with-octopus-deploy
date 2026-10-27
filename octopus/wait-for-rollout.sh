# Octopus step: waits for the Argo Rollout applied by the previous step to finish.
# Fails the deployment if Argo Rollouts aborts the update (automatic rollback), so the
# Octopus deployment result reflects what's actually running.
ns="#{Namespace}"
name="#{RolloutName}"
release="#{Octopus.Release.Number}"
timeout_s="#{RolloutTimeoutSeconds}"

highlight() { if declare -F write_highlight >/dev/null; then write_highlight "$1"; else echo "$1"; fi; }
get() { kubectl get rollout "$name" -n "$ns" -o jsonpath="$1"; }

# Wait for the controller to pick up the spec we just applied.
generation="$(get '{.metadata.generation}')"
for _ in $(seq 1 30); do
  [[ "$(get '{.status.observedGeneration}')" == "$generation" ]] && break
  sleep 2
done

# Re-deploying the release Argo just aborted doesn't change the spec, so Argo would
# stay aborted. Treat it as a retry, like `kubectl argo rollouts retry rollout`.
if [[ "$(get '{.status.abort}')" == "true" ]]; then
  echo "Rollout $name is aborted on this same spec; retrying it."
  kubectl patch rollout "$name" -n "$ns" --subresource=status --type=merge -p '{"status":{"abort":false}}'
  sleep 5
fi

last=""
deadline=$((SECONDS + timeout_s))
while (( SECONDS < deadline )); do
  phase="$(get '{.status.phase}')"
  step="$(get '{.status.currentStepIndex}')"
  message="$(get '{.status.message}')"
  line="phase=${phase:-?}${step:+ step=$step}${message:+ - $message}"
  if [[ "$line" != "$last" ]]; then echo "$line"; last="$line"; fi
  case "$phase" in
    Healthy)
      highlight "Rollout $name is Healthy running release $release."
      exit 0 ;;
    Degraded)
      if [[ "$(get '{.status.abort}')" == "true" ]]; then
        highlight "Argo Rollouts aborted release $release and rolled $name back to the stable version: $message"
      else
        highlight "Rollout $name is Degraded: $message"
      fi
      exit 1 ;;
  esac
  sleep 3
done
echo "Timed out after ${timeout_s}s waiting for rollout $name."
exit 1
