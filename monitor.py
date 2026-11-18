#!/usr/bin/env python3
"""A dependency-free Linux resource dashboard."""

import argparse
from collections import deque
import curses
from dataclasses import dataclass
import json
import os
from pathlib import Path
import pwd
import re
import signal
import socket
import sys
import time


PROC = Path('/proc')
LOCAL_FILESYSTEMS = {'ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'zfs', 'vfat',
                     'exfat', 'ntfs', 'ntfs3', 'f2fs', 'overlay', 'tmpfs'}
ACTIONS = {'t': ('Terminate', signal.SIGTERM), 'K': ('Force kill', signal.SIGKILL),
           's': ('Suspend', signal.SIGSTOP), 'r': ('Resume', signal.SIGCONT)}


def readable(value):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if abs(value) < 1024 or unit == 'TiB':
            return f'{value:.1f} {unit}'
        value /= 1024


def safe_text(value):
    return ''.join(char if char.isprintable() and ord(char) < 127 else '?' for char in str(value))


@dataclass
class Process:
    pid: int
    name: str
    state: str
    ticks: int
    started: int
    rss: int
    uid: int
    cpu: float = 0.0

    @property
    def identity(self):
        return self.pid, self.started


def parse_process(raw, uid):
    opening, closing = raw.index('('), raw.rindex(')')
    fields = raw[closing + 2:].split()
    return Process(int(raw[:opening].strip()), raw[opening + 1:closing], fields[0],
                   int(fields[11]) + int(fields[12]), int(fields[19]),
                   max(0, int(fields[21])) * os.sysconf('SC_PAGE_SIZE'), uid)


def read_process(pid):
    directory = PROC / str(pid)
    return parse_process((directory / 'stat').read_text(), directory.stat().st_uid)


def send_action(process, action):
    if action not in ACTIONS:
        raise ValueError('Unknown process action')
    if process.pid in (1, os.getpid()):
        raise ValueError('PID 1 and this dashboard are protected')
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise RuntimeError('Process controls require Python 3.9+ and Linux with pidfd support')
    descriptor = os.pidfd_open(process.pid)
    try:
        current = read_process(process.pid)
        if current.identity != process.identity:
            raise ProcessLookupError('Process exited; its PID has been reused')
        signal.pidfd_send_signal(descriptor, ACTIONS[action][1])
    finally:
        os.close(descriptor)


class Sampler:
    def __init__(self):
        self.previous_cpu = {}
        self.previous_processes = {}
        self.previous_network = {}
        self.previous_disks = {}
        self.previous_time = None
        self.ticks_per_second = os.sysconf('SC_CLK_TCK')
        self.history = deque(maxlen=90)
        self.storage = []
        self.storage_time = 0
        self.storage_errors = []
        self.snapshot = {}

    def sample(self):
        now = time.monotonic()
        elapsed = now - self.previous_time if self.previous_time is not None else None
        errors = []
        cpus = {}
        for line in (PROC / 'stat').read_text().splitlines():
            fields = line.split()
            if not fields[0].startswith('cpu'):
                continue
            values = list(map(int, fields[1:9]))
            total, idle = sum(values), values[3] + values[4]
            old_total, old_idle = self.previous_cpu.get(fields[0], (total, idle))
            delta = total - old_total
            cpus[fields[0]] = max(0, min(100, 100 * (delta - idle + old_idle) / delta)) if delta > 0 else 0
            self.previous_cpu[fields[0]] = total, idle
        memory = {}
        for line in (PROC / 'meminfo').read_text().splitlines():
            key, value = line.split(':', 1)
            memory[key] = int(value.split()[0]) * 1024
        processes = []
        denied = 0
        for directory in PROC.iterdir():
            if not directory.name.isdigit():
                continue
            try:
                process = read_process(int(directory.name))
            except (FileNotFoundError, ProcessLookupError):
                continue
            except PermissionError:
                denied += 1
                continue
            except (OSError, ValueError, IndexError) as error:
                errors.append(f'PID {directory.name}: {error}')
                continue
            old_ticks = self.previous_processes.get(process.identity)
            if elapsed and old_ticks is not None:
                process.cpu = max(0, (process.ticks - old_ticks) / self.ticks_per_second / elapsed * 100)
            processes.append(process)
        self.previous_processes = {process.identity: process.ticks for process in processes}
        network = []
        try:
            counters = {}
            for line in (PROC / 'net/dev').read_text().splitlines()[2:]:
                name, values = line.split(':', 1)
                fields = values.split()
                name = name.strip()
                received, sent = int(fields[0]), int(fields[8])
                old_received, old_sent = self.previous_network.get(name, (received, sent))
                network.append({'name': name, 'received': received, 'sent': sent,
                                'rx': max(0, received - old_received) / elapsed if elapsed else 0,
                                'tx': max(0, sent - old_sent) / elapsed if elapsed else 0})
                counters[name] = received, sent
            self.previous_network = counters
        except (OSError, ValueError, IndexError) as error:
            errors.append(f'Network unavailable: {error}')
        disks = []
        try:
            counters = {}
            for line in (PROC / 'diskstats').read_text().splitlines():
                fields = line.split()
                name = fields[2]
                if name.startswith(('loop', 'ram')) or (Path('/sys/class/block') / name / 'partition').exists():
                    continue
                read, written = int(fields[5]) * 512, int(fields[9]) * 512
                old_read, old_written = self.previous_disks.get(name, (read, written))
                disks.append({'name': name,
                              'read': max(0, read - old_read) / elapsed if elapsed else 0,
                              'write': max(0, written - old_written) / elapsed if elapsed else 0})
                counters[name] = read, written
            self.previous_disks = counters
        except (OSError, ValueError, IndexError) as error:
            errors.append(f'Disk I/O unavailable: {error}')
        if now - self.storage_time >= 5:
            self.sample_storage()
            self.storage_time = now
        errors.extend(self.storage_errors)
        self.previous_time = now
        self.history.append(cpus.get('cpu', 0))
        self.snapshot = {'cpus': cpus, 'memory': memory, 'processes': processes,
                         'network': network, 'disks': disks, 'storage': self.storage,
                         'uptime': float((PROC / 'uptime').read_text().split()[0]),
                         'load': os.getloadavg(), 'errors': errors, 'denied': denied}
        return self.snapshot

    def sample_storage(self):
        storage, errors, seen = [], [], set()
        try:
            lines = (PROC / 'self/mountinfo').read_text().splitlines()
        except OSError as error:
            self.storage, self.storage_errors = [], [f'Mounts unavailable: {error}']
            return
        for line in lines:
            before, after = line.split(' - ', 1)
            fields, filesystem = before.split(), after.split()[0]
            if filesystem not in LOCAL_FILESYSTEMS or fields[2] in seen:
                continue
            mount = re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), fields[4])
            try:
                stats = os.statvfs(mount)
            except OSError as error:
                errors.append(f'Storage {mount}: {error.strerror}')
                continue
            seen.add(fields[2])
            total = stats.f_blocks * stats.f_frsize
            if total:
                storage.append({'mount': mount, 'filesystem': filesystem, 'total': total,
                                'used': (stats.f_blocks - stats.f_bfree) * stats.f_frsize,
                                'free': stats.f_bavail * stats.f_frsize})
        self.storage, self.storage_errors = sorted(storage, key=lambda item: item['mount']), errors


class Dashboard:
    tabs = ('Overview', 'Processes', 'Storage', 'Network')

    def __init__(self, screen, interval):
        self.screen, self.interval = screen, interval
        self.sampler = Sampler()
        self.tab, self.offset, self.cursor = 0, 0, 0
        self.selected = None
        self.query, self.sort = '', 'cpu'
        self.editing, self.paused, self.help, self.details = False, False, False, False
        self.pending = None
        self.message = 'Collecting first sample...'
        self.users = {}
        self.filtered = []
        self.colors = False

    def put(self, row, column, text, color=0, bold=False):
        height, width = self.screen.getmaxyx()
        if row < 0 or row >= height or column >= width:
            return
        attribute = curses.A_BOLD if bold else 0
        if self.colors and color:
            attribute |= curses.color_pair(color)
        text = safe_text(text)[:max(0, width - column - 1)]
        if text:
            try:
                self.screen.addstr(row, column, text, attribute)
            except curses.error:
                pass

    def bar(self, row, label, percent, suffix=''):
        width = self.screen.getmaxyx()[1]
        length = max(4, min(32, width - 45))
        filled = round(max(0, min(100, percent)) * length / 100)
        self.put(row, 2, f'{label:<8} [{"|" * filled}{"." * (length - filled)}] {percent:5.1f}%  {suffix}',
                 3 if percent >= 90 else 2 if percent >= 70 else 1)

    def username(self, uid):
        if uid not in self.users:
            try:
                self.users[uid] = pwd.getpwuid(uid).pw_name
            except KeyError:
                self.users[uid] = str(uid)
        return self.users[uid]

    def process_rows(self):
        query = self.query.casefold()
        rows = [process for process in self.sampler.snapshot['processes']
                if query in f'{process.pid} {process.name} {self.username(process.uid)}'.casefold()]
        rows.sort(key=lambda process: getattr(process, self.sort), reverse=self.sort in ('cpu', 'rss'))
        identities = [process.identity for process in rows]
        if self.selected in identities:
            self.cursor = identities.index(self.selected)
        self.cursor = max(0, min(self.cursor, len(rows) - 1))
        self.selected = rows[self.cursor].identity if rows else None
        self.filtered = rows
        return rows

    def draw(self):
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 18 or width < 72:
            self.put(0, 0, 'Enlarge terminal to at least 72 x 18. Press q to quit.')
            self.screen.refresh()
            return
        data = self.sampler.snapshot
        uptime = int(data['uptime'])
        self.put(0, 2, f'PULSE / {socket.gethostname()}     UP {uptime // 86400}d {uptime // 3600 % 24:02}:{uptime // 60 % 60:02}', 1, True)
        self.put(1, 2, '   '.join(f'[{index + 1} {name}]' if index == self.tab else f' {index + 1} {name} '
                                for index, name in enumerate(self.tabs)), 1)
        memory = data['memory']
        used = memory['MemTotal'] - memory.get('MemAvailable', memory['MemFree'])
        self.bar(3, 'CPU', data['cpus']['cpu'], f'{len(data["cpus"]) - 1} cores')
        self.bar(4, 'Memory', used / memory['MemTotal'] * 100, f'{readable(used)} / {readable(memory["MemTotal"])}')
        self.put(5, 2, f'Load {data["load"][0]:.2f} / {data["load"][1]:.2f} / {data["load"][2]:.2f}     {len(data["processes"])} processes     {"PAUSED" if self.paused else "LIVE"}', 2 if self.paused else 0)
        bottom = height - 4
        if self.help:
            lines = ['KEYBOARD', '', '1-4 / Tab   Switch view', 'Up/Down, PgUp/PgDn   Select process / scroll',
                     '/   Filter processes by name, PID, or user; Enter accepts, Esc clears',
                     'c / m / p / n   Sort processes by CPU / memory / PID / name',
                     'Enter   Toggle process details', 't   Terminate (SIGTERM)    K   Force kill (SIGKILL)',
                     's   Suspend (SIGSTOP)      r   Resume (SIGCONT)',
                     'Actions require y confirmation; any other key cancels.',
                     'Space   Pause display     ?   Help     q   Quit',
                     'CPU per process: 100% = one core. Controls use your OS permissions.']
            for row, line in enumerate(lines[:bottom - 7], 7):
                self.put(row, 2, line)
        elif self.tab == 1:
            rows = self.process_rows()
            self.put(7, 2, f'PROCESSES / sort: {self.sort} / filter: {self.query or "(none)"} / {len(rows)} matches', 1, True)
            self.put(8, 2, f'{"PID":>7} {"USER":<12} {"CPU%":>7} {"MEMORY":>11} {"ST":>3}  NAME', 2)
            count = max(1, bottom - 9 - (2 if self.details else 0))
            self.offset = max(0, min(self.offset, self.cursor))
            if self.cursor >= self.offset + count:
                self.offset = self.cursor - count + 1
            for index, process in enumerate(rows[self.offset:self.offset + count], self.offset):
                self.put(9 + index - self.offset, 1, f'{">" if index == self.cursor else " "}{process.pid:7} {self.username(process.uid)[:12]:<12} {process.cpu:7.1f} {readable(process.rss):>11} {process.state:>3}  {process.name}', 1 if index == self.cursor else 0, index == self.cursor)
            if not rows:
                self.put(10, 2, 'No processes match this filter.')
            if self.details and rows:
                process = rows[self.cursor]
                self.put(bottom - 2, 2, f'PID {process.pid} / {process.name} / UID {process.uid} / state {process.state}', 2)
                self.put(bottom - 1, 2, 't terminate | K kill | s suspend | r resume (confirmation required)')
        else:
            lines = self.content(data, width)
            self.offset = max(0, min(self.offset, max(0, len(lines) - (bottom - 7))))
            for row, line in enumerate(lines[self.offset:self.offset + bottom - 7], 7):
                self.put(row, 2, line)
        if self.pending:
            process, action = self.pending
            status = f'{ACTIONS[action][0]} PID {process.pid} ({process.name})? y confirms; any other key cancels'
        elif self.editing:
            status = f'Filter: {self.query}_  (Enter accepts / Esc clears)'
        else:
            status = self.message
            if data['errors']:
                status = data['errors'][0] + f' ({len(data["errors"])} collection errors)'
            elif data['denied']:
                status += f' | {data["denied"]} processes hidden by permissions'
        self.put(height - 3, 2, status, 2)
        self.put(height - 2, 2, '1-4 views | / search | c/m/p/n sort | Enter details | ? help | q quit', 1)
        self.put(height - 1, 2, 't terminate | K kill | s suspend | r resume | Space pause | arrows scroll')
        self.screen.refresh()

    def content(self, data, width):
        if self.tab == 2:
            lines = ['FILESYSTEMS / local mounts / capacity refreshes every 5s', '',
                     f'{"USED":>6} {"TOTAL":>11} {"AVAILABLE":>11}  TYPE     MOUNT']
            for disk in data['storage']:
                lines.append(f'{disk["used"] / disk["total"] * 100:5.1f}% {readable(disk["total"]):>11} {readable(disk["free"]):>11}  {disk["filesystem"]:<8} {disk["mount"]}')
            lines += ['', 'BLOCK DEVICE I/O (devices and mapped devices may overlap)',
                      f'{"DEVICE":<20} {"READ/s":>14} {"WRITE/s":>14}']
            lines += [f'{disk["name"]:<20} {readable(disk["read"]):>14} {readable(disk["write"]):>14}' for disk in data['disks']]
            return lines
        if self.tab == 3:
            return ['NETWORK / current network namespace', '',
                    f'{"INTERFACE":<16} {"RX/s":>12} {"TX/s":>12} {"RECEIVED":>12} {"SENT":>12}'] + [
                        f'{item["name"]:<16} {readable(item["rx"]):>12} {readable(item["tx"]):>12} {readable(item["received"]):>12} {readable(item["sent"]):>12}'
                        for item in data['network']]
        levels = ' .:-=+*#%@'
        history = ''.join(levels[min(9, int(value / 100 * 9))] for value in self.sampler.history)
        memory = data['memory']
        lines = ['CPU HISTORY / one sample per refresh', '[' + history[-(width - 6):].ljust(min(90, width - 6), '.') + ']', '', 'PER-CORE CPU']
        cores = [(name, value) for name, value in data['cpus'].items() if name != 'cpu']
        columns = max(1, (width - 4) // 18)
        for start in range(0, len(cores), columns):
            lines.append(''.join(f'{name:>6} {value:5.1f}%    ' for name, value in cores[start:start + columns]))
        lines += ['', f'SWAP  {readable(memory["SwapTotal"] - memory["SwapFree"])} / {readable(memory["SwapTotal"])}', '', 'BUSIEST PROCESSES']
        for process in sorted(data['processes'], key=lambda process: process.cpu, reverse=True)[:5]:
            lines.append(f'{process.pid:7}  {process.cpu:6.1f}%  {readable(process.rss):>11}  {process.name}')
        lines += ['', 'Use 2 for process controls, 3 for storage, 4 for network.']
        return lines

    def key(self, key):
        if self.pending:
            process, action = self.pending
            self.pending = None
            if key == 'y':
                try:
                    send_action(process, action)
                    self.message = f'{ACTIONS[action][0]} signal sent to PID {process.pid}'
                except (OSError, ValueError, RuntimeError) as error:
                    self.message = f'Action failed: {error}'
            else:
                self.message = 'Action cancelled'
            return True
        if self.editing:
            if key in ('\n', '\r', curses.KEY_ENTER):
                self.editing = False
            elif key == '\x1b':
                self.query, self.editing = '', False
            elif key in (curses.KEY_BACKSPACE, '\x7f', '\b'):
                self.query = self.query[:-1]
            elif isinstance(key, str) and key.isprintable() and len(self.query) < 100:
                self.query += key
            self.selected, self.cursor, self.offset = None, 0, 0
            return True
        if key == 'q':
            return False
        if key == '?':
            self.help = not self.help
        elif key in ('1', '2', '3', '4', '\t'):
            self.tab = (self.tab + 1) % 4 if key == '\t' else int(key) - 1
            self.offset, self.help = 0, False
        elif key == ' ':
            self.paused = not self.paused
        elif key == '/':
            self.tab, self.editing, self.help = 1, True, False
        elif not self.help:
            if key in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_NPAGE, curses.KEY_PPAGE):
                step = {curses.KEY_UP: -1, curses.KEY_DOWN: 1,
                        curses.KEY_NPAGE: max(1, self.screen.getmaxyx()[0] - 14),
                        curses.KEY_PPAGE: -max(1, self.screen.getmaxyx()[0] - 14)}[key]
                if self.tab == 1:
                    self.cursor = max(0, min(len(self.filtered) - 1, self.cursor + step))
                    self.selected = self.filtered[self.cursor].identity if self.filtered else None
                else:
                    self.offset = max(0, self.offset + step)
            elif self.tab == 1:
                if key in ('c', 'm', 'p', 'n'):
                    self.sort = {'c': 'cpu', 'm': 'rss', 'p': 'pid', 'n': 'name'}[key]
                    self.selected, self.cursor, self.offset = None, 0, 0
                elif key in ('\n', '\r', curses.KEY_ENTER):
                    self.details = not self.details
                elif key in ACTIONS and self.filtered:
                    self.pending = self.filtered[self.cursor], key
        return True

    def run(self):
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        if curses.has_colors():
            curses.start_color()
            for index, foreground in enumerate((curses.COLOR_CYAN, curses.COLOR_YELLOW, curses.COLOR_RED), 1):
                curses.init_pair(index, foreground, curses.COLOR_BLACK)
            self.colors = True
        self.screen.keypad(True)
        self.screen.timeout(100)
        next_sample = 0
        while True:
            if time.monotonic() >= next_sample and (not self.paused or not self.sampler.snapshot):
                self.sampler.sample()
                next_sample = time.monotonic() + self.interval
                if self.message == 'Collecting first sample...' and len(self.sampler.history) > 1:
                    self.message = 'Ready / ? for keyboard help'
            self.draw()
            try:
                key = self.screen.get_wch()
            except curses.error:
                continue
            if not self.key(key):
                break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interval', type=float, default=1.0, help='Refresh seconds (0.2 to 60; default: 1)')
    parser.add_argument('--snapshot', action='store_true', help='Print a JSON sample and exit (no terminal needed)')
    arguments = parser.parse_args()
    if not 0.2 <= arguments.interval <= 60:
        parser.error('--interval must be between 0.2 and 60 seconds')
    if sys.platform != 'linux':
        parser.error('This dashboard requires Linux /proc')
    try:
        if arguments.snapshot:
            sampler = Sampler()
            sampler.sample()
            time.sleep(arguments.interval)
            data = sampler.sample()
            data['processes'] = [vars(process) for process in data['processes']]
            print(json.dumps(data, indent=2))
        else:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                parser.error('Run in an interactive terminal, or use --snapshot')
            curses.wrapper(lambda screen: Dashboard(screen, arguments.interval).run())
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, curses.error) as error:
        print(f'Pulse failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
