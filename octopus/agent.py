#!/usr/bin/env python3
"""Helpers for scripts/install-octopus-agent.sh.

  agent.py values         prints the agent's Helm values (JSON) for this config
  agent.py remove-stale   deletes a deployment target named AGENT_NAME left by an earlier
                          cluster (the script calls this only when the agent isn't installed)
"""
import json
import sys

from config import SETTINGS
from octopus_api import SPACE_NAME, api, find_by_name, space_id

SECRET = "octopus-agent-api-key"  # created by install-octopus-agent.sh: keys api-key, SERVER_ACCESS_TOKEN


def values():
    url = SETTINGS["OCTOPUS_URL"] + "/"
    environments = [e.strip() for e in SETTINGS["OCTOPUS_ENVIRONMENTS"].split(",") if e.strip()]
    return {
        "agent": {
            "acceptEula": "Y",
            "name": SETTINGS["AGENT_NAME"],
            "serverUrl": url,
            "serverCommsAddress": SETTINGS["OCTOPUS_POLLING_URL"],
            "space": SPACE_NAME,
            "serverApiKeySecretName": SECRET,
            "deploymentTarget": {
                "enabled": True,
                "initial": {"environments": environments, "tags": [SETTINGS["OCTOPUS_TARGET_TAG"]]},
            },
        },
        # Streams the live status of deployed resources to Octopus.
        "kubernetesMonitor": {
            "enabled": SETTINGS["KUBERNETES_MONITOR"] == "true",
            "monitor": {"serverGrpcUrl": SETTINGS["OCTOPUS_GRPC_URL"]},
            "registration": {
                "register": True,
                "serverApiUrl": url,
                "serverAccessTokenSecretName": SECRET,
                "machineName": SETTINGS["AGENT_NAME"],
                "spaceId": space_id(),
            },
        },
        # kind's default storage class is single-node RWO; script pods run next to the agent.
        "persistence": {"accessModes": ["ReadWriteOnce"], "size": "5Gi"},
    }


def remove_stale():
    target = find_by_name("machines", SETTINGS["AGENT_NAME"])
    if target is None:
        return
    api("DELETE", f"{space_id()}/machines/{target['Id']}")
    print(f"Deleted deployment target {target['Name']} ({target['Id']}), left by an earlier cluster; "
          "the agent registers a new one.")


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "values":
        print(json.dumps(values(), indent=2))
    elif command == "remove-stale":
        remove_stale()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
