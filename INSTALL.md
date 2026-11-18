# Installing Pulse

## Requirements

- Linux with `/proc` mounted; Python 3.10 or newer with `curses`.
- Git to clone the repository, or an extracted repository download.
- An interactive terminal at least 72 columns by 18 rows for the dashboard.
- Process controls additionally require Linux pidfd support and the appropriate OS permissions.

No pip packages, root privileges, service manager, or network access during installation are required. Run as your regular user.

## 1. Download into a persistent directory

```bash
git clone https://github.com/mustafakuloglu/pulse-monitor.git
cd pulse-monitor
```

Choose a location you intend to keep. The installed command links to this checkout; deleting or moving the checkout breaks that link.

## 2. Install the `monitor` command

```bash
python3 install.py
```

The installer checks the platform and Python, creates `~/.local/bin` if necessary, makes `monitor.py` executable, and creates a `monitor` symlink. It does not modify shell startup files. An existing link to the same file is treated as already installed. Any other file, directory, or symlink named `monitor` at the destination is left untouched and reported as a conflict.

For a custom directory:

```bash
python3 install.py --bin-dir "$HOME/bin"
```

Use the same directory in the PATH and uninstall commands below.

## 3. Put the command on PATH

For the current Bash or Zsh session:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

To make this persistent, add the following line **once** to `~/.bashrc` for Bash or `~/.zshrc` for Zsh, then open a new terminal:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

For Fish:

```fish
fish_add_path "$HOME/.local/bin"
```

Some Linux distributions already include `~/.local/bin` on PATH. The installer reports whether its destination is present on the inherited PATH, but cannot update the shell that launched it.

```bash
command -v monitor
monitor --help
monitor
```

If your shell defines an alias or function named `monitor`, it may take precedence. Inspect it with `type monitor`, or run `~/.local/bin/monitor` directly.

## Manual binding instead of the installer

From the repository root:

```bash
chmod u+x monitor.py
mkdir -p "$HOME/.local/bin"
ln -s "$PWD/monitor.py" "$HOME/.local/bin/monitor"
export PATH="$HOME/.local/bin:$PATH"
```

Do not add `-f` to `ln`: if another command exists, inspect it before replacing it. The Python installer is preferable for repeated or automated installs because it checks collisions and recognizes an existing installation.

## Agent / noninteractive installation

Read [AGENTS.md](AGENTS.md). From the cloned repository, these commands require no interactive input:

```bash
python3 install.py
"$HOME/.local/bin/monitor" --help
"$HOME/.local/bin/monitor" --snapshot --interval 0.2
```

The installer returns `0` for a successful or already-complete install, `1` for a failed operation, and `2` for invalid arguments. Failures go to stderr. It performs no downloads and never invokes sudo. Use `--bin-dir` to choose a writable location if the agent's sandbox does not permit access to `~/.local/bin`; that directory must be on the user's PATH to enable the bare `monitor` command.

A JSON snapshot is the smoke check for environments without a TTY. Inspect its `errors` field and report partial collection failures. Do not attach the snapshot to public issues or commits without reviewing its machine-specific data.

## Update

From your existing checkout:

```bash
git pull --ff-only
python3 install.py
```

The symlink uses the current checkout. Restart an already-running dashboard after updating.

## Uninstall

From the same checkout used to install:

```bash
python3 install.py --uninstall
```

Or, for a custom location:

```bash
python3 install.py --bin-dir "$HOME/bin" --uninstall
```

Uninstall removes only a symlink pointing to this checkout's `monitor.py`; it refuses to remove unrelated files. An absent command is a successful no-op. You can then remove the checkout if you no longer want it. Keep your PATH entry if other applications use that directory.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `monitor: command not found` | Add the installation directory to PATH or use the full command path. |
| Installer reports a conflict | Inspect the existing destination; choose another `--bin-dir` or resolve the conflict yourself. |
| Command stopped working after moving the checkout | Inspect and remove the old broken symlink, then install from the new checkout. |
| Missing `curses` / `_curses` | Use a Python build with curses support, such as your distribution's system Python. |
| Terminal setup fails | Run inside a real terminal with a valid `TERM`, or use `--snapshot`. |
| Only an enlarge-terminal message appears | Resize to at least 72 × 18. |
| Permission denied for a process action | The OS does not permit your user to signal that process. |
| pidfd action error | Monitoring still works; controls need a kernel and Python with pidfd support. |
| Container totals differ from limits | Pulse reports namespace-visible metrics, not container cgroup limits. |
