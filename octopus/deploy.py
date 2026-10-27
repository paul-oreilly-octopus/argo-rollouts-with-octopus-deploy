#!/usr/bin/env python3
"""Creates a release of a Colour Demo project (or reuses one) and deploys it.

  ./deploy.py canary                                  # new release, project's StartColour, demo environment
  ./deploy.py bluegreen --colour red                  # override StartColour: Argo will roll back
  ./deploy.py canary --release 0.0.2 --env Staging    # deploy an existing release
  ./deploy.py canary --no-wait                        # don't wait for the Octopus task
"""
import argparse
import sys
import time

from config import SETTINGS
from octopus_api import PROJECTS, SERVER, SPACE, api, find_by_name


def create_release(project):
    channel = api("GET", f"{SPACE}/projects/{project['Id']}/channels")["Items"][0]
    template = api("GET", f"{SPACE}/deploymentprocesses/{project['DeploymentProcessId']}/template?channel={channel['Id']}")
    return api("POST", f"{SPACE}/releases", {
        "ProjectId": project["Id"], "ChannelId": channel["Id"], "Version": template["NextVersionIncrement"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", choices=PROJECTS)
    parser.add_argument("--env", default=SETTINGS["OCTOPUS_DEMO_ENVIRONMENT"])
    parser.add_argument("--colour", help="override the StartColour prompt (default: the release's value)")
    parser.add_argument("--release", help="existing release version to deploy instead of creating one")
    parser.add_argument("--no-wait", action="store_true")
    args = parser.parse_args()

    project = find_by_name("projects", PROJECTS[args.project])
    environment = find_by_name("environments", args.env)
    if args.release:
        release = api("GET", f"{SPACE}/projects/{project['Id']}/releases/{args.release}")
    else:
        release = create_release(project)
        print(f"Created release {release['Version']}")

    snapshot = api("GET", f"{SPACE}/variables/{release['ProjectVariableSetSnapshotId']}")
    colour_var = next(v for v in snapshot["Variables"] if v["Name"] == "StartColour")
    colour = args.colour or colour_var["Value"]
    deployment = api("POST", f"{SPACE}/deployments", {
        "ReleaseId": release["Id"], "EnvironmentId": environment["Id"],
        "FormValues": {colour_var["Id"]: colour}})
    print(f"Deploying {project['Name']} {release['Version']} to {args.env} (start colour {colour})")
    print(f"  {SERVER}/app#/{SPACE}/tasks/{deployment['TaskId']}")
    if args.no_wait:
        return

    while not (task := api("GET", f"{SPACE}/tasks/{deployment['TaskId']}"))["IsCompleted"]:
        time.sleep(5)
    log = api("GET", f"{SPACE}/tasks/{deployment['TaskId']}/raw", raw=True)
    keep = ("phase=", "Rollout", "Argo", "Cluster:", "release")
    interesting = [line for line in log.splitlines() if any(k in line for k in keep)]
    print("\n".join(interesting[-15:]))
    print(f"Result: {task['State']} ({task['Duration']})")
    sys.exit(0 if task["State"] == "Success" else 1)


if __name__ == "__main__":
    main()
