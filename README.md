# Pulse Monitor

**Your Linux system, live in the terminal.**

Watch CPU, memory, storage, network traffic, and running processes in one keyboard-driven dashboard. Find a busy process, inspect it, and suspend, resume, or end it without leaving your terminal.

**Python standard library only · No pip install · No daemon · No telemetry**

```text
  PULSE / linux-box                         UP 2d 04:18
  [1 Overview]    2 Processes    3 Storage    4 Network

  CPU      [||||||||........................]  25.0%  8 cores
  Memory   [||||||||||||....................]  37.5%  6.0 GiB / 16.0 GiB
  Load 1.25 / 0.96 / 0.72     184 processes     LIVE

  CPU HISTORY / one sample per refresh
  [..::--=++=-:::..::---==--:................................]

  PER-CORE CPU
    cpu0  18.0%      cpu1  34.0%      cpu2  22.0%      cpu3  26.0%

  1-4 views | / search | c/m/p/n sort | Enter details | ? help | q quit
```

*Illustrative preview with fictional data, not a captured machine snapshot.*

## Get started

Requires **Linux**, **Python 3.10+ with curses**, and a terminal at least **72 × 18**. Use a Linux terminal locally, over SSH, or inside WSL. Native macOS and Windows are not supported.

```bash
git clone https://github.com/mustafakuloglu/pulse-monitor.git
cd pulse-monitor
python3 install.py
export PATH="$HOME/.local/bin:$PATH"
monitor
```

The installer links `~/.local/bin/monitor` to this checkout. Keep the checkout in place. It requires no root access, downloads nothing, and refuses to replace an unrelated command. Re-running it is safe.

Prefer to run without installing?

```bash
python3 monitor.py
```

See the **[installation guide](INSTALL.md)** for permanent PATH setup, manual command binding, custom locations, upgrades, uninstalling, and troubleshooting.

## Four views, one dashboard

| View | What you can see and do |
| --- | --- |
| **Overview** | Aggregate and per-core CPU, recent CPU history, RAM, swap, load, uptime, and busiest processes |
| **Processes** | Filter by name, PID, or user; sort by CPU or memory; inspect, terminate, force kill, suspend, or resume |
| **Storage** | Local filesystem capacity and available space, plus block-device read/write rates |
| **Network** | Per-interface receive/send rates and cumulative byte counts |

Storage is monitoring-only: Pulse does not delete files, resize partitions, or modify mounts.

## Keyboard controls

| Key | Action |
| --- | --- |
| `1`–`4` / Tab | Switch views |
| Arrows / Page Up / Page Down | Select a process or scroll |
| `/` | Search processes by name, PID, or user |
| Enter / Escape while searching | Accept / clear the search |
| `c` / `m` / `p` / `n` | Sort processes by CPU / memory / PID / name |
| Enter in Processes | Toggle process details |
| `t` / `K` | Terminate / force kill the selected process |
| `s` / `r` | Suspend / resume the selected process |
| `y` at an action prompt | Confirm; any other key cancels |
| Space | Pause / resume the display |
| `?` / `q` | Help / quit |

## CLI and automation

```bash
monitor --help
monitor --interval 0.5
monitor --snapshot --interval 0.2
```

`--snapshot` samples twice and prints one JSON object, without opening a terminal UI. The interval is the delay between samples; allowed values are 0.2–60 seconds. JSON contains `cpus`, `memory`, `processes`, `storage`, `disks`, `network`, `uptime`, `load`, `errors`, and `denied`.

- Memory/storage sizes and network counters are bytes; disk and network rates are bytes per second. Process `ticks` and `started` are kernel clock ticks, not bytes.
- CPU values are percentages. A process at 100% occupies one core and may exceed 100% across multiple cores.
- `errors` lists collection failures; `denied` counts process entries unavailable due to permissions.
- A snapshot can succeed with partial data: agents should check `errors`, not just the exit code.
- Exit code `0` means normal completion, `1` a runtime failure, and `2` invalid CLI usage.

### Let an agent install it

Give your coding agent this instruction:

> Install https://github.com/mustafakuloglu/pulse-monitor in a persistent user-owned directory. Read AGENTS.md and INSTALL.md, run the noninteractive installer, and validate with a JSON snapshot. Make the monitor command available on my PATH. Do not use sudo or overwrite another monitor command.

The repository includes **[agent instructions](AGENTS.md)** with setup commands, validation, and boundaries for process control. Agents can install Pulse using the same installer as people, within their filesystem permissions. No special agent integration or background service is required.

## Safety and privacy

Run Pulse as your normal user. Process actions use your OS permissions and require confirmation. Termination requests graceful exit; force kill can lose unsaved work. Suspended processes keep their resources until resumed.

PID 1 and Pulse itself are protected. Actions use Linux pidfds and check process start time to avoid sending a signal to a reused PID. Kernels without pidfd support can still monitor resources, but process actions report an error.

Pulse makes no network requests and does not collect command-line arguments or environment variables. Screenshots and JSON snapshots can still contain system details such as process names, UIDs, mount paths, and, in the UI, hostnames and usernames. Review them before sharing.

## Reading the numbers

- CPU rates need two samples; the first frame shows zero.
- Process memory is RSS. Shared pages may count toward multiple processes.
- Filesystem capacity refreshes every five seconds. Bind mounts are deduplicated by device, and available space excludes reserved blocks.
- Remote filesystems are excluded. Block devices and their mapped devices can overlap, so their rates should not be summed.
- Metrics reflect the current `/proc`, mount, and network namespaces. Containers may expose host CPU/memory totals rather than cgroup limits.
- Process permission restrictions and collection errors appear in the status line.

## Development

```bash
python3 -m unittest discover -s tests -v
```

Tests cover process parsing, reused-PID protection, confirmations, permission failures, installer behavior, and live sampling. The process-control integration test starts its own disposable child, then suspends, resumes, and terminates it.
