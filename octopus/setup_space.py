#!/usr/bin/env python3
"""Creates the Octopus space and its environments if they don't exist (re-runnable).

The space is OCTOPUS_SPACE_NAME, with the API key's user as its space manager. Creating a
space needs the SpaceCreate permission; to use an existing space instead, create it in
Octopus first (or set OCTOPUS_SPACE_NAME to it) and this only adds missing environments.
"""
import sys

from config import SETTINGS
from octopus_api import ApiError, api, find_space

LIFECYCLE = "Default Lifecycle"


def main():
    space = find_space()
    if space is None:
        me = api("GET", "users/me")
        try:
            space = api("POST", "spaces", {
                "Name": SETTINGS["OCTOPUS_SPACE_NAME"],
                "Description": "Argo Rollouts with Octopus Deploy demo "
                               "(github.com/paul-oreilly-octopus/argo-rollouts-with-octopus-deploy).",
                "SpaceManagersTeams": [],
                "SpaceManagersTeamMembers": [me["Id"]],
            }, exit_on_error=False)
        except ApiError as e:
            if e.status not in (401, 403):
                raise
            sys.exit(f'Space "{SETTINGS["OCTOPUS_SPACE_NAME"]}" doesn\'t exist, and {me["Username"]} isn\'t '
                     "allowed to create spaces (SpaceCreate). Ask an Octopus administrator to create it with "
                     f"{me['Username']} as a space manager (or set OCTOPUS_SPACE_NAME to a space they manage), "
                     "then run ./install.sh again.")
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
