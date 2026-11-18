# Working with Pulse Monitor

This directory is the complete project. Keep changes, Git staging, and publication scoped to it. Do not include neighboring projects, local system snapshots, credentials, or shell configuration.

## Install for the user

When the user asks to install Pulse:

1. Read `README.md` and `INSTALL.md`. Choose a persistent user-owned checkout; the installer links to it.
2. Run `python3 install.py` from the repository root. It is noninteractive, idempotent for the same checkout, and refuses to overwrite unrelated files.
3. Validate with `"$HOME/.local/bin/monitor" --help` and `"$HOME/.local/bin/monitor" --snapshot --interval 0.2`. For `--bin-dir`, substitute that destination.
4. Inspect snapshot `errors` and report any degraded collection. Do not save snapshots into the repository or publish their contents.
5. Check whether the installation directory is on PATH. If authorized to configure the user's shell, preserve existing content and add the documented PATH entry only if needed. Otherwise provide the exact command from `INSTALL.md`.

Do not use sudo, replace another `monitor` command, disable security controls, or bypass tool approval requirements. If the installation destination is outside your writable sandbox, use the environment's normal approval mechanism or a user-approved writable directory. Installing Pulse does not authorize modifying unrelated system processes.

## Use without a terminal

`python3 monitor.py --snapshot --interval 0.2` returns a JSON object after two samples. Units are documented in the README. Check both the exit code and `errors`; partial metrics may be returned with exit code zero. The JSON format is currently unversioned, so tolerate additional fields and do not assume a stable schema across future releases.

Process management is interactive and requires confirmation. Do not automate confirmation or signal processes unless the user explicitly requests the specific action and target. For tests, only control disposable processes the test creates.

## Develop and validate

- Python standard library only; keep compatibility with Python 3.10+ on Linux.
- `monitor.py`: sampling, process controls, terminal UI, and JSON output.
- `install.py`: per-user command binding and uninstall.
- `tests/`: standard-library unittest tests.
- Run `python3 -m unittest discover -s tests -v` after code changes.
- Preserve pidfd-based signaling, start-time checks, confirmation, and OS permission handling.
- Surface meaningful failures. Never collect environment variables or full command-line arguments for diagnostics.
- Do not push, publish, or change repository visibility without the user's authorization.
