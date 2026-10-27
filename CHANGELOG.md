# Changelog

Notable changes to the demo. To update your copy, see
[Keeping your copy up to date](README.md#keeping-your-copy-up-to-date). After updating, run
`./install.sh` again and create new releases: existing releases keep the deployment process
they were created with.

## Unreleased

- README: "How the demo works" with diagrams and screenshots; setup for Linux, macOS and
  Windows (WSL 2); which Octopus API key to use (a service account that manages only the demo
  space) and what it needs.
- `AGENT-INSTRUCTIONS.md`: a checklist for AI agents, from forking the repo to a tested demo.
- `install.sh` works with macOS's bash 3.2.
- **One API key for everything.** The installer no longer creates extra API keys for Argo
  Rollouts' webhook and the runbooks: they use the key you provide, which can be an AI agent
  key (Octopus doesn't let agent keys create API keys). `ARGO_NOTIFICATIONS_API_KEY_FILE` is
  gone, and every `./install.sh` run updates the key in the cluster and the projects, so
  replacing it is just updating the file. Production setups should use separate, tightly
  scoped keys.

## 0.1.0

First public version.

- `install.sh`: a single, re-runnable installer for tools, the kind cluster (ingress-nginx,
  Argo Rollouts), the Octopus space, the Kubernetes agent, the dashboard, the projects and the
  Argo Rollouts webhook. `uninstall.sh` removes it all.
- Configuration in `config.env` (git-ignored), with defaults for everything except
  `OCTOPUS_URL`.
- Canary and blue-green Octopus projects with Argo Rollouts analysis, the per-pod colour
  dashboard, and the Simulate builds runbook.
- Rollback sync: Argo Rollouts' notifications run the Record Argo rollback runbook, which
  records the release Argo rolled back to as a record-only deployment, unless a newer
  deployment is queued or running.
- `octopus/stress_test.py` for rapid deployments, with `--chase` and `--cycle`.
- `AGENTS.md` / `CLAUDE.md`: setup instructions for AI agents.
