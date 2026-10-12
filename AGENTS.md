# smooth-caddy

## Project Layout

- `smooth_caddy.py`: main local entry script.
- `app/`: application package.
- `tests/`: unittest test suite.
- `~/.smooth-caddy/`: default runtime data directory (outside the repository).
- `.venv/`: local Python virtual environment; ignored by git.

## Environment

Use the repository-local virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e .
```

The editable install provides the `smooth-caddy` console command, but the root entry
script is still the preferred local entry point.

## Run

```bash
.venv/bin/python smooth_caddy.py
```

The default data directory is `~/.smooth-caddy/` on Linux and Windows, which stores
the database directly at `~/.smooth-caddy/smooth-caddy.db`. Exports always use
`~/smooth-caddy-export/`, including when `--data-dir` is specified.

## Test

```bash
.venv/bin/python -m compileall -q smooth_caddy.py app tests
.venv/bin/python -m unittest discover -s tests
```

## Notes For Codex

- Keep `smooth_caddy.py` in the repository root as the human-facing main program.
- Keep application modules under `app/`; do not reintroduce `src/`.
- Do not add an extra data directory level such as `~/.smooth-caddy/data/`.
- Use `app/` imports inside tests and implementation.
- Prefer small, focused edits and keep CLI behavior covered by `tests/test_app.py`.
- Treat `README.md` as the default Chinese documentation entry point; keep `README.en.md`
  aligned as its English introduction, with reciprocal language links and matching screenshots.
- Keep only current documentation in `docs/`: `usage.md` owns user procedures and upgrade guidance;
  `development.md` owns source setup, testing, versioning and release procedures;
  `product.md` owns product behavior; `ca-lite-interface.md` owns the
  current Python certificate-module contract and `supertaskrunner.md` owns the task-system
  architecture constraints.
- Do not add draft, archive, completed-plan, or duplicated command-inventory
  documents. Git history preserves superseded material; the current TUI and supported entry parser define available operations.
- Update the owning document in the same change when its contract or architecture
  boundary changes.

## Versioning and compatibility

- Follow `docs/development.md`'s version/release contract: tags `vX.Y.Z`, artifacts `X.Y.Z.<short-commit>`; initial tag `v0.1.0`.
- Conventionally increase Z for each commit; persistent data-format changes increase Y and reset Z. This is a documentation convention, not an automated commit gate.
- GitHub release builds are triggered by version-tag pushes, not ordinary branch commits; read the triggering tag and its commit. Initial targets: Linux x64 and Windows x64.
- Data migrations and compatibility layers are permitted. Support starts from the first formal release; back up before migrations and reject writes to newer formats.
- Current database format is 10 (backed-up migration from 2–9). Settings archive / JSON format is 4 (reads 1, 2, 3 and 4). Legacy batch metadata 1–5 is decoded read-only for one-time settings extraction. New runtime materials are ephemeral, not persistent batches. Persist stable identifiers, never translated labels.
- Public repository, MIT project license; preserve third-party license obligations. Keep private data, backups, caches and generated exports out of Git.

- SSH paths are independent of business upstreams: `ssh_hops` stores one IP per hop in a singleton list; host trust is scoped to the route prefix.

- Nodes have a free HTTPS `upstream_url`, no parent references or mode enum. Relay TLS validates the dedicated relay CA and fixed `relay.smooth-caddy.internal` name; relay mTLS has no per-node leaf allowlist. Keep user mTLS authorization separate.

- Region bind addresses use `ips` lists with one shared port set. Generate explicit tcp4/tcp6 listeners; wildcard overlap checks stay within each address family and node.

- Regions hold TLS source and mTLS defaults only. Site-region Service overrides use null for inheritance. Node regions independently own HTTP/HTTPS/relay ports; HTTP is redirect-only.

- Prefer visible radio candidates for small exclusive choices and checkboxes for booleans; avoid dropdowns when practical.

- Verify user-requested changes, but build packages only when requested. For requested local builds, use an explicitly local/dirty build identity for uncommitted work; do not create release tags or push unless requested.

- Origin HTTPS verification belongs to each Site, defaults off, and is edited alongside its source URL. Migrate the former global value to existing sites without changing behavior.
