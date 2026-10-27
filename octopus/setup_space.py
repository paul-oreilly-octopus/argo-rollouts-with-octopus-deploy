#!/usr/bin/env python3
"""Finds the Octopus space and adds any missing environments (re-runnable).

The space is OCTOPUS_SPACE_NAME, normally created by an administrator with the API key's
account as a space manager. If no space has that name and the key can create spaces
(SpaceCreate), this creates it, with the key's account as its space manager.
"""
import sys

from config import SETTINGS
from octopus_api import ApiError, api

LIFECYCLE = "Default Lifecycle"


def not_found(name, me, visible):
    """Exits explaining that the key's account can't see a space called name."""
    seen = ", ".join(f'"{s["Name"]}"' for s in visible) if visible else "none"
    sys.exit(f'No space named "{name}" is visible to {me["Username"]}, and it can\'t create spaces '
             f"(SpaceCreate). Spaces it can see: {seen}.\n"
             f'If the space exists, set OCTOPUS_SPACE_NAME in config.env to its exact name. Otherwise ask an '
             f'Octopus administrator to create it with {me["Username"]} as a space manager (see "The Octopus '
             'API key" in README.md). Then run ./install.sh again.')


def main():
    name = SETTINGS["OCTOPUS_SPACE_NAME"]
    visible = api("GET", "spaces/all")
    space = next((s for s in visible if s["Name"] == name), None)
    if space is None:
        me = api("GET", "users/me")
        if "SpaceCreate" not in api("GET", f"users/{me['Id']}/permissions").get("SystemPermissions", []):
            not_found(name, me, visible)
        try:
            space = api("POST", "spaces", {
                "Name": name,
                "Description": "Argo Rollouts with Octopus Deploy demo "
                               "(github.com/paul-oreilly-octopus/argo-rollouts-with-octopus-deploy).",
                "SpaceManagersTeams": [],
                "SpaceManagersTeamMembers": [me["Id"]],
            }, exit_on_error=False)
        except ApiError as e:
            if e.status not in (401, 403):
                raise
            not_found(name, me, visible)
        print(f"Created space {space['Name']} ({space['Id']})")
    else:
        print(f"Using space {space['Name']} ({space['Id']})")
    sid = space["Id"]

    existing = {e["Name"] for e in api("GET", f"{sid}/environments/all")}
    for name in (n.strip() for n in SETTINGS["OCTOPUS_ENVIRONMENTS"].split(",") if n.strip()):
        if name not in existing:
            api("POST", f"{sid}/environments", {"Name": name})
            print(f"  created environment {name}")

    # No phases: releases can go to any environment in any order.
    if not any(lc["Name"] == LIFECYCLE for lc in api("GET", f"{sid}/lifecycles/all")):
        api("POST", f"{sid}/lifecycles", {"Name": LIFECYCLE, "Phases": []})
        print(f"  created lifecycle {LIFECYCLE}")


if __name__ == "__main__":
    main()
