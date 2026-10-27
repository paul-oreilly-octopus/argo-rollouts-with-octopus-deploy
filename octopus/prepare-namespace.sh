# Octopus step: creates the namespace and the Rollout's two Services if they don't exist.
# The Services are created once and then left alone: Argo Rollouts adds the
# rollouts-pod-template-hash to their selectors, and re-applying them would wipe that
# and make Argo treat the next update as an initial deploy (skipping analysis).
ns="#{Namespace}"
kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f -

for suffix in #{ServiceSuffixes}; do
  svc="#{RolloutName}-$suffix"
  if kubectl get service "$svc" -n "$ns" >/dev/null 2>&1; then
    echo "Service $svc already exists; leaving it to Argo Rollouts."
    continue
  fi
  kubectl apply -n "$ns" -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: $svc
spec:
  selector:
    colour-demo/rollout: #{RolloutName}
  ports:
    - name: http
      port: 80
      targetPort: http
EOF
done
