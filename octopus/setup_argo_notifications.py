#!/usr/bin/env python3
"""Connects Argo Rollouts notifications in the demo cluster to Octopus (re-runnable).

- Loads the Octopus API key (OCTOPUS_API_KEY_FILE) into Secret
  argo-rollouts-notification-secret (key octopus-api-key); the key is never printed or passed
  on a command line. A production setup would use a separate, tightly scoped key here.
- Applies k8s/argo-notifications.yaml (the webhook service, trigger and template), pointed
  at OCTOPUS_URL.
"""
import base64
import json

from octopus_api import HERE, SERVER, api_key, kubectl

NAMESPACE = "argo-rollouts"
SECRET = "argo-rollouts-notification-secret"


def main():
    # Built here rather than with --from-file, so a key file saved with a trailing newline (or
    # CRLF) still works; the key goes to kubectl on stdin.
    secret = {"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
              "metadata": {"name": SECRET, "namespace": NAMESPACE},
              "data": {"octopus-api-key": base64.b64encode(api_key().encode()).decode()}}
    print(kubectl("apply", "-f", "-", stdin=json.dumps(secret)))
    config = (HERE.parent / "k8s/argo-notifications.yaml").read_text().replace("__OCTOPUS_URL__", SERVER)
    print(kubectl("apply", "-f", "-", stdin=config))


if __name__ == "__main__":
    main()
