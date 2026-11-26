# Security policy — gama-learn

Report to **renato@gamatrade.ba** with `[gama-learn-security]`.

## Scope

`gama-learn` is a local-first server (UI, MCP server, sentinel, skill-fix loop) plus
scripts that talk to a fleet. Relevant classes of bug:

- a route or MCP tool that lets a caller read or write outside the catalogue/work dirs;
- the skill-fix loop applying a patch it did not verify, or skipping the rollback;
- a token (`GAMA_LEARN_TOKEN`, Telegram, brain) reaching a log, an error page or the UI;
- the sentinel executing something derived from an unauthenticated input.

## Configuration, not code

Fleet addresses, LLM endpoints and backup paths are **not** committed — they come from
`GAMA_LEARN_API`, `GAMA_LEARN_PEERS`, `GAMA_LEARN_CHECKS`, `GAMA_LLM_URL`,
`GAMA_LEARN_BACKUP_DIR` and `GAMA_FLEET_FILE`. `tools_no_internal_addrs.py` runs in CI
and fails if a CGNAT/RFC1918 address is committed again.

## Deployment

The server has a single shared token and no per-user accounts. It belongs on a trusted
network; exposing it to the internet is a deployment error, not a vulnerability.
