#!/usr/bin/env python3
"""Runs a project's "Simulate builds" runbook (creates a release every N seconds for M minutes).

  ./simulate_builds.py canary                          # defaults: every 2s for 30 min
  ./simulate_builds.py bluegreen --interval 5 --minutes 10
  ./simulate_builds.py canary --minutes 0.5 --wait     # wait and show the created releases
  ./simulate_builds.py canary --colour uniform-with-red  # releases with this start colour
"""
import argparse
import sys
import time

from config import SETTINGS
from octopus_api import PROJECTS, SERVER, SPACE, api, find_by_name

RUNBOOK = "Simulate builds"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", choices=PROJECTS)
    parser.add_argument("--interval", default="2", help="seconds between releases (default 2)")
    parser.add_argument("--minutes", default="30", help="how long to run (default 30)")
    parser.add_argument("--colour", help="start colour of the releases (default: the project's Start colour)")
    parser.add_argument("--env", default=SETTINGS["OCTOPUS_DEMO_ENVIRONMENT"], help="environment to run the runbook in")
    parser.add_argument("--wait", action="store_true", help="wait for the run and print its output")
    args = parser.parse_args()

    project = find_by_name("projects", PROJECTS[args.project])
    runbook = next(r for r in api("GET", f"{SPACE}/projects/{project['Id']}/runbooks")["Items"] if r["Name"] == RUNBOOK)
    snapshot = api("GET", f"{SPACE}/runbookSnapshots/{runbook['PublishedRunbookSnapshotId']}")
    variables = api("GET", f"{SPACE}/variables/{snapshot['FrozenProjectVariableSetId']}")["Variables"]
    values = {"BuildIntervalSeconds": args.interval, "BuildDurationMinutes": args.minutes}
    if args.colour:
        values["StartColour"] = args.colour
    form = {v["Id"]: values[v["Name"]] for v in variables if v["Name"] in values}
    environment = find_by_name("environments", args.env)

    run = api("POST", f"{SPACE}/runbookRuns", {
        "RunbookId": runbook["Id"], "RunbookSnapshotId": snapshot["Id"],
        "EnvironmentId": environment["Id"], "FormValues": form})
    print(f"Started {RUNBOOK} for {project['Name']}: every {args.interval}s for {args.minutes} min")
    print(f"  {SERVER}/app#/{SPACE}/tasks/{run['TaskId']}")
    if not args.wait:
        return

    while not (task := api("GET", f"{SPACE}/tasks/{run['TaskId']}"))["IsCompleted"]:
        time.sleep(5)
    log = api("GET", f"{SPACE}/tasks/{run['TaskId']}/raw", raw=True)
    keep = ("Start colour", "Restored", "Starting from", "Created release", "Failed to create", "releases; latest", "Error", "Fatal")
    print("\n".join(line.strip() for line in log.splitlines() if any(k in line for k in keep)))
    print(f"Result: {task['State']} ({task['Duration']})")
    sys.exit(0 if task["State"] == "Success" else 1)


if __name__ == "__main__":
    main()
