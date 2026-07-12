#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
observer_cli.py - Real-time CLI observer for the PreToolUse hook.

Tails logs/decisions.jsonl and prints new decisions to stdout as they
arrive, with color coding. No GUI -- just a console app that works
in any terminal.

Usage:
    python scripts/observer_cli.py
    python scripts/observer_cli.py --color=never
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = REPO_ROOT / 'logs' / 'decisions.jsonl'

# ANSI colors (auto-disabled on Windows unless FORCE_COLOR is set or
# the user opts in -- we default to "auto" which uses color only when
# stdout is a TTY).
USE_COLOR = (
    sys.stdout.isatty() and os.environ.get('TERM', '') != 'dumb'
) or os.environ.get('FORCE_COLOR') == '1'


def _c(code: str, text: str) -> str:
    if not USE_COLOR:
        return text
    return f'\x1b[{code}m{text}\x1b[0m'


def fmt(obj: dict) -> str:
    """Format a decision object as a single readable line."""
    ts = obj.get('ts', '?')
    tool = obj.get('tool', '?')
    decision = obj.get('decision', '?')
    perm = obj.get('permission_decision', '?')
    rule = (obj.get('matched_rule') or '-') or '-'
    took = obj.get('took_ms', '?')
    rid = obj.get('request_id', '?')

    perm_color = {
        'allow': '32',   # green
        'deny':  '31',   # red
        'ask':   '33',   # yellow
    }.get(perm, '37')   # white
    perm_str = _c(perm_color, f'{perm:>5}')

    # Shorten the timestamp to HH:MM:SS
    short_ts = ts[11:19] if len(ts) >= 19 else ts

    return (
        f'{_c("90", short_ts)}  '
        f'{_c("1", tool.ljust(8))}  '
        f'{_c("37", decision.ljust(8))}  '
        f'{perm_str}  '
        f'{_c("36", rule.ljust(30))}  '
        f'{_c("90", f"{took}ms".rjust(5))}  '
        f'req={_c("90", rid[:12])}'
    )


def print_header() -> None:
    h = (
        f'{"TIME":<8}  {"TOOL":<8}  {"DECISION":<8}  '
        f'{"PERM":>5}  {"RULE":<30}  {"ms":>5}  request_id'
    )
    print(_c('1;90', h))
    print(_c('90', '-' * len(h)))


def print_full(obj: dict) -> None:
    """Pretty-print the full decision JSON below the row."""
    try:
        print(_c('90', json.dumps(obj, indent=2, ensure_ascii=False)))
    except Exception:
        pass


def follow() -> int:
    if not LOG_FILE.exists():
        print(_c('31', f'log not found: {LOG_FILE}'), file=sys.stderr)
        print(_c('33', 'start the classifier service first'), file=sys.stderr)
        return 1

    # Load existing
    print_header()
    try:
        text = LOG_FILE.read_text(encoding='utf-8', errors='replace')
    except OSError as e:
        print(_c('31', f'read error: {e}'), file=sys.stderr)
        return 2
    last_size = LOG_FILE.stat().st_size

    loaded = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get('message') == 'decision':
            print(fmt(obj))
            loaded += 1
    print(_c('90', f'-- loaded {loaded} historical decisions --'))
    print()

    # Follow
    try:
        while True:
            time.sleep(0.3)
            if not LOG_FILE.exists():
                continue
            try:
                cur = LOG_FILE.stat().st_size
            except OSError:
                continue
            if cur == last_size:
                continue
            if cur < last_size:
                # rotated / truncated
                last_size = 0
            try:
                with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
                    f.seek(last_size)
                    delta = f.read()
                    last_size = f.tell()
            except OSError as e:
                print(_c('31', f'read error: {e}'), file=sys.stderr)
                continue
            for ln in delta.splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    obj = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if obj.get('message') != 'decision':
                    continue
                print(fmt(obj))
                sys.stdout.flush()
    except KeyboardInterrupt:
        print()
        print(_c('90', 'observer stopped.'))
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else '')
    ap.add_argument('--color', choices=['auto', 'always', 'never'], default='auto')
    ap.add_argument('--full', action='store_true',
                    help='also print the full JSON for each new decision')
    args = ap.parse_args()

    global USE_COLOR
    if args.color == 'never':
        USE_COLOR = False
    elif args.color == 'always':
        USE_COLOR = True
        os.environ['FORCE_COLOR'] = '1'

    return follow()


if __name__ == '__main__':
    raise SystemExit(main())