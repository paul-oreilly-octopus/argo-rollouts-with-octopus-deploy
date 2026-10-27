# secrets/

Everything in this folder except this README is git-ignored.

- `octopus-api-key.txt`: put your Octopus API key here (just the key, e.g. `API-...`), or
  point `OCTOPUS_API_KEY_FILE` in `config.env` at a file somewhere else.

Keep the permissions tight, e.g. `chmod 600 secrets/*.txt`.
