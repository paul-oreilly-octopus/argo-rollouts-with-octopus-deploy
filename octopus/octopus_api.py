"""Minimal Octopus REST client shared by the scripts in this folder (stdlib only).

The server, API key file and space come from config.py. SPACE (the space ID) is looked up
by name the first time a script imports it, so the space must exist (setup_space.py).
"""
import json
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request

from config import SETTINGS

HERE = pathlib.Path(__file__).resolve().parent
SERVER = SETTINGS["OCTOPUS_URL"]
KEY_FILE = pathlib.Path(SETTINGS["OCTOPUS_API_KEY_FILE"])
SPACE_NAME = SETTINGS["OCTOPUS_SPACE_NAME"]

PROJECTS = {"canary": "Colour Demo - Canary", "bluegreen": "Colour Demo - Blue-Green"}

_api_key = None
_space_id = None


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(f"{status} {message}")
        self.status = status


def api_key():
    """The Octopus API key from OCTOPUS_API_KEY_FILE (never print it)."""
    global _api_key
    if _api_key is None:
        try:
            _api_key = KEY_FILE.read_text().strip()
        except OSError:
            sys.exit(f"Can't read the Octopus API key from {KEY_FILE} (see OCTOPUS_API_KEY_FILE).")
    return _api_key


def api(method, path, body=None, raw=False, exit_on_error=True):
    """Calls the API. `path` may be relative to /api/ or a resource's Links value.

    Errors end the script with Octopus's message, or raise ApiError if exit_on_error is False.
    """
    if not SERVER:
        sys.exit("OCTOPUS_URL isn't set: copy config.example.env to config.env and edit it.")
    path = re.sub(r"\{[^}]*\}", "", path)  # drop URI-template parts of Links
    if path.startswith("/api/"):
        path = path[len("/api/"):]
    url = f"{SERVER}/api/{path.lstrip('/')}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "X-Octopus-ApiKey": api_key(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            content = r.read()
    except urllib.error.HTTPError as e:
        message = e.read().decode(errors="replace")
        if not exit_on_error:
            raise ApiError(e.code, message) from None
        sys.exit(f"{method} {url} failed: {e.code} {message}")
    except urllib.error.URLError as e:
        sys.exit(f"{method} {url} failed: {e.reason}")
    if raw:
        return content.decode(errors="replace")
    return json.loads(content) if content else None


def find_space():
    return next((s for s in api("GET", "spaces/all") if s["Name"] == SPACE_NAME), None)


def space_id():
    global _space_id
    if _space_id is None:
        space = find_space()
        if space is None:
            sys.exit(f'Octopus space "{SPACE_NAME}" doesn\'t exist yet: run ./install.sh (or octopus/setup_space.py).')
        _space_id = space["Id"]
    return _space_id


def __getattr__(name):  # `from octopus_api import SPACE` looks the space up on first use
    if name == "SPACE":
        return space_id()
    raise AttributeError(name)


def find_by_name(collection, name):
    return next((item for item in api("GET", f"{space_id()}/{collection}/all") if item["Name"] == name), None)


def kubectl(*args, stdin=None, check=True):
    """Runs kubectl against this demo's cluster (KUBE_CONTEXT), never the current context."""
    result = subprocess.run(["kubectl", "--context", SETTINGS["KUBE_CONTEXT"], *args],
                            input=stdin, text=True, capture_output=True)
    if check and result.returncode:
        sys.exit(f"kubectl {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()
