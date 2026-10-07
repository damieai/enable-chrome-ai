"""Patch Chrome's local AI-related settings, without claiming server eligibility."""

import argparse
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import psutil


COUNTRY = 'us'
VERSION_RE = re.compile(r'\d+\.\d+\.\d+\.\d+')


def get_version_and_user_data_path():
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'Google'
        paths = {name: base / folder / 'User Data' for name, folder in (
            ('stable', 'Chrome'), ('canary', 'Chrome SxS'),
            ('dev', 'Chrome Dev'), ('beta', 'Chrome Beta'),
        )}
    elif sys.platform.startswith('linux'):
        base = Path(os.environ.get('CHROME_CONFIG_HOME') or
                    os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
        paths = {name: base / folder for name, folder in (
            ('stable', 'google-chrome'), ('canary', 'google-chrome-canary'),
            ('dev', 'google-chrome-unstable'), ('beta', 'google-chrome-beta'),
        )}
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support/Google'
        paths = {name: base / folder for name, folder in (
            ('stable', 'Chrome'), ('canary', 'Chrome Canary'),
            ('dev', 'Chrome Dev'), ('beta', 'Chrome Beta'),
        )}
    else:
        raise ValueError(f'Unsupported platform: {sys.platform}')
    return {name: str(path.resolve()) for name, path in paths.items() if path.is_dir()}


def get_last_version(user_data_path):
    path = Path(user_data_path) / 'Last Version'
    if not path.exists():
        return None
    version = path.read_text(encoding='utf-8-sig').strip()
    return version if VERSION_RE.fullmatch(version) else None


def read_local_state(path):
    original = path.read_bytes()
    state = json.loads(original.decode('utf-8-sig'))
    if not isinstance(state, dict):
        raise ValueError('Local State must contain a JSON object')
    return original, state


def profile_cache(state):
    profile = state.get('profile', {})
    if not isinstance(profile, dict) or not isinstance(profile.get('info_cache', {}), dict):
        raise ValueError('profile.info_cache must be a JSON object')
    return profile.get('info_cache', {})


def build_patch(state, last_version):
    """Only touch known settings; eligibility is a cache, not an entitlement."""
    patched = deepcopy(state)
    changes = []

    def set_value(obj, key, value, label=None):
        if key not in obj or type(obj[key]) is not type(value) or obj[key] != value:
            changes.append((label or key, obj.get(key), value))
            obj[key] = value

    for name, entry in profile_cache(patched).items():
        if not isinstance(entry, dict):
            raise ValueError(f'Invalid profile.info_cache entry: {name!r}')
        set_value(entry, 'is_glic_eligible', True,
                  f'profile.info_cache.{name}.is_glic_eligible')

    set_value(patched, 'variations_country', COUNTRY)
    # Chromium's explicit permanent-country override takes precedence over the
    # version-bound country cache, including with newer seed storage formats.
    set_value(patched, 'variations_permanent_overridden_country', COUNTRY)
    if last_version:
        version = last_version.strip()
        if not VERSION_RE.fullmatch(version):
            raise ValueError('Invalid Chrome version')
        set_value(patched, 'variations_permanent_consistency_country', [version, COUNTRY])
    # Safe-seed fields describe a last-known-good experiment snapshot. Preserve
    # them, signed seeds, account capabilities, policies and consent preferences.
    return patched, changes


def print_diagnostics(state, last_version):
    print(f'  Last Version: {last_version or "missing/invalid (version-bound cache will be skipped)"}')
    for key in ('variations_country', 'variations_permanent_consistency_country',
                'variations_permanent_overridden_country'):
        print(f'  {key}: {json.dumps(state.get(key), ensure_ascii=True)}')
    intl = state.get('intl', {})
    print(f'  UI locale: {json.dumps(intl.get("app_locale") if isinstance(intl, dict) else None)}')
    cache = profile_cache(state)
    if not cache:
        print('  No cached profiles; sign in to Chrome and run again.')
    for name, entry in cache.items():
        if not isinstance(entry, dict):
            raise ValueError(f'Invalid profile.info_cache entry: {name!r}')
        print(f'  Profile {name!r}: cached eligibility={entry.get("is_glic_eligible", "missing")}')
        if entry.get('is_managed') == 1:
            print('    Managed profile: administrator settings may prevent Gemini access.')
    print('  Eligibility is recalculated by Chrome. Local values do not prove Gemini access.')


def write_local_state(path, original, patched):
    """Back up exact bytes, then replace atomically; never truncate the live file."""
    if path.read_bytes() != original:
        raise RuntimeError('Local State changed during patching; close Chrome and retry')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = path.with_name(f'{path.name}.backup-{stamp}')
    with backup.open('xb') as fp:
        fp.write(original)
        fp.flush()
        os.fsync(fp.fileno())
    shutil.copymode(path, backup)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.Local-State-', delete=False) as fp:
            temporary = Path(fp.name)
            json.dump(patched, fp, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
            fp.flush()
            os.fsync(fp.fileno())
        shutil.copymode(path, temporary)
        if path.read_bytes() != original:
            raise RuntimeError('Local State changed during patching; close Chrome and retry')
        os.replace(temporary, path)
        _, actual = read_local_state(path)
        if actual != patched:
            raise RuntimeError(f'Write verification failed; backup: {backup}')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return backup


def patch_local_state(user_data_path, last_version, *, dry_run=False, check=False):
    path = Path(user_data_path) / 'Local State'
    original, state = read_local_state(path)
    print_diagnostics(state, last_version)
    patched, changes = build_patch(state, last_version)
    for key, old, new in changes:
        print(f'  {key}: {json.dumps(old)} -> {json.dumps(new)}')
    if not changes:
        print('  Local patch already present (not a Gemini availability check).')
    elif check or dry_run:
        print(f'  {len(changes)} pending local changes; no files written.')
    else:
        assert_chrome_stopped()
        backup = write_local_state(path, original, patched)
        print(f'  Local patch written and verified. Backup: {backup}')
    return bool(changes)


def is_chrome_process(name):
    name = name.casefold()
    if sys.platform == 'darwin':
        return name == 'google chrome' or name.startswith('google chrome ')
    return name in {'chrome', 'chrome.exe', 'google-chrome', 'google-chrome-stable',
                    'google-chrome-beta', 'google-chrome-unstable', 'google-chrome-canary'}


def chrome_processes():
    """Only inspect Chrome belonging to the current OS user."""
    owner = psutil.Process().username().casefold()
    result = []
    for process in psutil.process_iter():
        try:
            name = process.name()
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            continue  # Protected OS processes cannot be identified by name.
        if not is_chrome_process(name):
            continue
        try:
            if process.username().casefold() == owner:
                result.append(process)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as exc:
            raise RuntimeError(f'Cannot inspect Chrome PID {process.pid}; close Chrome manually') from exc
    return result


def assert_chrome_stopped():
    if chrome_processes():
        raise RuntimeError('Chrome is still running; close all Chrome windows/background processes and retry')


@dataclass
class ChromeCommand:
    argv: list[str]
    cwd: str


def shutdown_chrome(restart_commands):
    processes = chrome_processes()
    pids = {process.pid for process in processes}
    commands = {}
    # Gather restart information before terminating anything. Helper processes
    # must never be relaunched as standalone browsers.
    for process in processes:
        try:
            argv = process.cmdline()
            if (process.ppid() not in pids and
                    not any(arg.startswith('--type=') for arg in argv) and
                    'helper' not in process.name().casefold()):
                if not argv:
                    raise RuntimeError(f'Cannot read Chrome command line for PID {process.pid}')
                commands[process.pid] = ChromeCommand([process.exe(), *argv[1:]], process.cwd())
        except psutil.NoSuchProcess:
            continue
    if not processes:
        return
    print('Closing Chrome for the current OS user and waiting for processes to exit...')
    # Stop browser processes first. POSIX terminate sends SIGTERM; on Windows it
    # uses TerminateProcess. Save work before running the script on either OS.
    for process in processes:
        if process.pid not in commands:
            continue
        try:
            process.terminate()
            restart_commands.append(commands[process.pid])
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(processes, timeout=5)
    for process in alive:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(alive, timeout=5)
    if alive:
        raise RuntimeError('Chrome did not exit; no configuration will be written')
    assert_chrome_stopped()


def restart_argv(argv, override_country=False):
    if not override_country:
        return list(argv)
    # Support both --key=value and --key value; retain other startup arguments.
    result = []
    skip = False
    for arg in argv:
        if skip:
            skip = False
            continue
        if arg == '--variations-override-country':
            skip = True
        elif not arg.startswith('--variations-override-country='):
            result.append(arg)
    result.insert(1, f'--variations-override-country={COUNTRY}')
    return result


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-data-dir', type=Path,
                        help='Chrome User Data directory (not Default or Profile 1)')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='preview changes without closing Chrome or writing')
    mode.add_argument('--check', action='store_true', help='read-only local check; exit 1 if changes are pending')
    parser.add_argument('--no-close', action='store_true', help='require Chrome to be closed manually')
    parser.add_argument('--no-restart', action='store_true', help='leave Chrome closed after patching')
    parser.add_argument('--restart-country', action='store_true',
                        help='restart with --variations-override-country=us for this launch only')
    args = parser.parse_args(argv)
    if args.restart_country and (args.no_restart or args.no_close or args.check or args.dry_run):
        parser.error('--restart-country requires normal closing and restarting mode')
    return args


def main(argv=None):
    args = parse_args(argv)
    restart_commands = []
    status = 0
    try:
        paths = ({'custom': str(args.user_data_dir.expanduser().resolve())}
                 if args.user_data_dir else get_version_and_user_data_path())
        if not paths:
            raise ValueError('No Chrome user data directory found; use --user-data-dir')
        # Validate before closing Chrome; read it again after shutdown so that
        # shutdown-time preference writes are included in the patch and backup.
        valid_paths = {}
        for channel, path in paths.items():
            try:
                _, state = read_local_state(Path(path) / 'Local State')
                build_patch(state, get_last_version(path))
                valid_paths[channel] = path
            except (OSError, ValueError) as exc:
                print(f'ERROR [{channel}]: {exc}', file=sys.stderr)
                status = 1
        if not valid_paths:
            return 1
        if not (args.dry_run or args.check):
            if args.no_close:
                assert_chrome_stopped()
            else:
                shutdown_chrome(restart_commands)
        for channel, path in valid_paths.items():
            print(f'[{channel}] {path}')
            try:
                pending = patch_local_state(path, get_last_version(path),
                                            dry_run=args.dry_run, check=args.check)
                if args.check and pending:
                    status = 1
            except (OSError, ValueError, RuntimeError) as exc:
                print(f'ERROR [{channel}]: {exc}', file=sys.stderr)
                status = 1
        print('If Gemini is unavailable, inspect chrome://policy and your account eligibility.\n'
              'Country overrides affect Chrome experiments beyond AI; they do not change server access.')
        if args.restart_country and not restart_commands:
            print('Chrome was not running. Start it manually with --variations-override-country=us.')
    except (OSError, ValueError, RuntimeError, psutil.Error) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        status = 1
    finally:
        if restart_commands and not args.no_restart:
            try:
                assert_chrome_stopped()
                for command in restart_commands:
                    subprocess.Popen(restart_argv(command.argv, args.restart_country),
                                     cwd=command.cwd, stderr=subprocess.DEVNULL)
                print('Restarted Chrome. Local verification does not verify runtime Gemini access.')
            except (OSError, RuntimeError, psutil.Error) as exc:
                print(f'Could not restart Chrome: {exc}. Please start it manually.', file=sys.stderr)
                status = 1
    return status


if __name__ == '__main__':
    sys.exit(main())
