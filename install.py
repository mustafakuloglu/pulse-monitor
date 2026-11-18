#!/usr/bin/env python3
"""Install or remove the per-user monitor command without external dependencies."""

import argparse
import os
from pathlib import Path
import shlex
import stat
import sys


def bind_command(source, bin_dir, uninstall=False):
    source = source.resolve()
    bin_dir = bin_dir.expanduser().absolute()
    destination = bin_dir / 'monitor'
    exists = os.path.lexists(destination)
    ours = destination.is_symlink() and destination.resolve() == source
    if exists and not ours:
        raise FileExistsError(f'Refusing to replace or remove unrelated path: {destination}')
    if uninstall:
        if ours:
            destination.unlink()
        return destination, 'Removed' if ours else 'Already absent'
    if not source.is_file():
        raise FileNotFoundError(f'Missing application: {source}')
    source.chmod(source.stat().st_mode | stat.S_IXUSR)
    if ours:
        return destination, 'Already installed'
    bin_dir.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(source)
    return destination, 'Installed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin-dir', type=Path, default=Path.home() / '.local/bin',
                        help='Command directory (default: ~/.local/bin)')
    parser.add_argument('--uninstall', action='store_true', help='Remove only this checkout\'s monitor link')
    arguments = parser.parse_args()
    try:
        if not arguments.uninstall:
            if sys.platform != 'linux' or sys.version_info < (3, 10):
                raise RuntimeError('Pulse requires Linux and Python 3.10 or newer')
            if not Path('/proc/stat').is_file():
                raise RuntimeError('Pulse requires a mounted /proc filesystem')
            try:
                import curses
            except ImportError as error:
                raise RuntimeError('This Python needs curses support; try your system Python') from error
        destination, status = bind_command(Path(__file__).with_name('monitor.py'),
                                           arguments.bin_dir, arguments.uninstall)
        print(f'{status}: {destination}')
        if not arguments.uninstall:
            path_dirs = [Path(entry).resolve() for entry in os.environ.get('PATH', '').split(os.pathsep) if entry]
            if destination.parent.resolve() not in path_dirs:
                print('Add this directory to PATH (Bash/Zsh):')
                print(f'  export PATH={shlex.quote(str(destination.parent))}:"$PATH"')
                print('See INSTALL.md for persistent shell configuration.')
            print(f'Check: {shlex.quote(str(destination))} --help')
        return 0
    except (OSError, RuntimeError) as error:
        print(f'Pulse installation failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
