#!/usr/bin/env python3
"""Removes what install.sh created in Octopus (used by uninstall.sh).

  cleanup.py target   deletes the agent's deployment target (AGENT_NAME)
  cleanup.py space    deletes the whole space (OCTOPUS_SPACE_NAME) with everything in it
"""
import sys

from config import SETTINGS
from octopus_api import SPACE_NAME, api, find_by_name, find_space


def delete_target():
    if find_space() is None:
        return
    target = find_by_name("machines", SETTINGS["AGENT_NAME"])
    if target:
        api("DELETE", f"{target['SpaceId']}/machines/{target['Id']}")
        print(f"Deleted deployment target {target['Name']}")


def delete_space():
    space = find_space()
    if space is None:
        print(f"Space {SPACE_NAME} doesn't exist")
        return
    space["TaskQueueStopped"] = True  # a space must stop its task queue before it can be deleted
    api("PUT", f"spaces/{space['Id']}", space)
    api("DELETE", f"spaces/{space['Id']}")
    print(f"Deleted space {SPACE_NAME} ({space['Id']})")


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "target":
        delete_target()
    elif command == "space":
        delete_space()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
