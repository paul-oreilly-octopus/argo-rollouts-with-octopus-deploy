#!/usr/bin/env python3
"""Settings for every script in this repo.

Each setting comes from, in order: an environment variable, config.env at the repo root
(git-ignored; copy config.example.env), or the default below. Only OCTOPUS_URL has no
default. config.env is read as KEY=value lines, not executed.

  python3 octopus/config.py check    # validate and print the settings (never the API key)
  eval "$(python3 octopus/config.py shell)"   # what scripts/config.sh does for the bash scripts
"""
import os
import pathlib
import re
import shlex
import sys
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_FILE = pathlib.Path(os.environ.get("CONFIG_FILE") or ROOT / "config.env")


def _read(path):
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            match = re.match(r"\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if match and not line.lstrip().startswith("#"):
                value = match.group(2)
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                values[match.group(1)] = value
    return values


_FILE = _read(CONFIG_FILE)


def get(name, default=""):
    return os.environ.get(name) or _FILE.get(name) or default


def _path(value):
    path = pathlib.Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def _settings():
    url = get("OCTOPUS_URL").rstrip("/")
    host = urllib.parse.urlparse(url).hostname or ""
    cloud = host.endswith(".octopus.app")
    cluster = get("CLUSTER_NAME", "argo-rollouts-demo")
    agent = get("AGENT_NAME", cluster)
    key_file = _path(get("OCTOPUS_API_KEY_FILE", "secrets/octopus-api-key.txt"))
    return {
        # Octopus
        "OCTOPUS_URL": url,
        "OCTOPUS_API_KEY_FILE": str(key_file),
        "OCTOPUS_SPACE_NAME": get("OCTOPUS_SPACE_NAME", "Argo Rollouts Demo"),
        "OCTOPUS_ENVIRONMENTS": get("OCTOPUS_ENVIRONMENTS", "Development,Staging,Production"),
        "OCTOPUS_DEMO_ENVIRONMENT": get("OCTOPUS_DEMO_ENVIRONMENT", "Development"),
        "OCTOPUS_WORKER_POOL": get("OCTOPUS_WORKER_POOL"),  # empty: "Hosted Ubuntu" if present, else the default pool
        "OCTOPUS_TARGET_TAG": get("OCTOPUS_TARGET_TAG", "argo-rollouts"),
        # Octopus Cloud addresses are derived from OCTOPUS_URL; self-hosted servers usually need these set.
        "OCTOPUS_POLLING_URL": get("OCTOPUS_POLLING_URL", f"https://polling.{host}/" if cloud else f"https://{host}:10943/"),
        "OCTOPUS_GRPC_URL": get("OCTOPUS_GRPC_URL", f"grpc://{host}:8443"),
        "KUBERNETES_MONITOR": get("KUBERNETES_MONITOR", "true").lower(),
        # Cluster
        "CLUSTER_NAME": cluster,
        "KUBE_CONTEXT": get("KUBE_CONTEXT", f"kind-{cluster}"),
        "INGRESS_HTTP_PORT": get("INGRESS_HTTP_PORT", "80"),
        "INGRESS_HTTPS_PORT": get("INGRESS_HTTPS_PORT", "443"),
        "AGENT_NAME": agent,
        "AGENT_NAMESPACE": get("AGENT_NAMESPACE", f"octopus-agent-{agent}"),
        "AGENT_CHART_VERSION": get("AGENT_CHART_VERSION", "3.15.3"),
        "ARGO_ROLLOUTS_VERSION": get("ARGO_ROLLOUTS_VERSION", "v1.10.0"),
        "INGRESS_NGINX_VERSION": get("INGRESS_NGINX_VERSION", "controller-v1.15.1"),
    }


SETTINGS = _settings()


def check():
    """Returns a list of problems with the settings (empty when they're usable)."""
    problems = []
    url = SETTINGS["OCTOPUS_URL"]
    if not url:
        problems.append(f"OCTOPUS_URL isn't set (copy config.example.env to {CONFIG_FILE.name} and edit it)")
    elif not re.match(r"https?://[^/\s]+$", url):
        problems.append(f"OCTOPUS_URL should look like https://your-instance.octopus.app, not {url}")
    key = pathlib.Path(SETTINGS["OCTOPUS_API_KEY_FILE"])
    if not key.is_file() or not key.read_text().strip():
        problems.append(f"No API key in {key} (put your Octopus API key in that file, or set OCTOPUS_API_KEY_FILE)")
    for name in ("INGRESS_HTTP_PORT", "INGRESS_HTTPS_PORT"):
        if not SETTINGS[name].isdigit():
            problems.append(f"{name} should be a port number")
    return problems


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    if command == "shell":
        for name, value in SETTINGS.items():
            print(f"export {name}={shlex.quote(value)}")
    elif command == "check":
        print(f"Settings ({CONFIG_FILE if CONFIG_FILE.exists() else 'no config.env; environment and defaults'}):")
        for name, value in SETTINGS.items():
            print(f"  {name:<34} {value}")
        problems = check()
        if problems:
            print("\nPROBLEMS:\n  " + "\n  ".join(problems))
            sys.exit(1)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
