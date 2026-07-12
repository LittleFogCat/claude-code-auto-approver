#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
observer_gui.py - Real-time GUI for the PreToolUse classifier hook.

Tails logs/decisions.jsonl and shows every decision as a row in a tkinter
Treeview. Click a row to see the full JSON payload at the bottom.

Pure stdlib (tkinter). Works with the project's .venv Python.

Usage:
    python scripts/observer_gui.py
"""

from __future__ import annotations


def _clf_probe_tk(py: str, timeout: float = 4.0) -> bool:
    """Return True iff the given python executable can build a Tk root."""
    import subprocess
    try:
        r = subprocess.run(
            [py, "-c", "import tkinter; r=tkinter.Tk(); r.destroy()"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return r.returncode == 0
    except Exception:
        return False


def _clf_ensure_tk_works() -> None:
    """Run at module-import time, BEFORE ``import tkinter as tk``.

    Some uv-managed CPython distributions ship a tcl layout the bundled
    _tkinter does not recognize. When that happens, double-clicking
    observer_gui.bat/vbs appears to do nothing because tkinter import
    succeeds but ``tk.Tk()`` raises ``TclError`` and stderr is closed by
    the launcher -- giving the impression that the GUI "does not open".

    This guard:
      1. Subprocess-probes the current Python with a 2-line Tk.destroy().
      2. On failure, walks a list of well-known system Pythons (3.11-3.13
         official installers; the Microsoft ``py`` launcher output; explicit
         ``CLF_GUI_PYTHON`` env override) and finds one that builds a Tk.
      3. Re-launches ``observer_gui.py`` under the chosen Python and exits
         the current process silently.
      4. If no fallback is available, opens a Win32 MessageBox (no tkinter
         required) with copyable remediation steps.
    """
    import os, subprocess, sys
    from pathlib import Path as _P

    if _clf_probe_tk(sys.executable):
        return  # current interpreter is fine -- fast path

    candidates: list[str] = []

    # Highest priority: explicit override.
    env_py = os.environ.get("CLF_GUI_PYTHON", "").strip()
    if env_py:
        candidates.append(env_py)

    # 1) Scan every directory in PATH that contains python[w].exe.
    seen_dirs: set[str] = set()
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d or d in seen_dirs:
            continue
        seen_dirs.add(d)
        for exe in ("pythonw.exe", "python.exe", "python3.exe"):
            p = _P(d) / exe
            if p.exists():
                candidates.append(str(p))

    # 2) Drive letters and common install roots.
    import string
    drives = [f"{c}:\\" for c in string.ascii_uppercase
              if os.path.exists(f"{c}:\\")]
    for drv in drives:
        for prefix in (
            "Python",
            r"\software\Python",
            r"\tools\Python",
            r"\dev\Python",
        ):
            for ver in ("312", "311", "313", "310"):
                for tag in ("", "-64"):
                    for exe in ("pythonw.exe", "python.exe"):
                        p = _P(f"{drv}{prefix}{ver}{tag}\\{exe}")
                        if p.exists():
                            candidates.append(str(p))

    # 3) uv-managed pythons (skip 3.14 -- its tcl layout is broken).
    import glob
    import re as _re_clf
    uv_root = _P.home() / "AppData" / "Roaming" / "uv" / "python"
    if uv_root.exists():
        for sub in glob.glob(str(uv_root) + "/cpython-3.*"):
            m = _re_clf.search(r"cpython-(\d+\.\d+)", sub)
            if m and m.group(1) == "3.14":
                continue
            for exe in ("pythonw.exe", "python.exe"):
                p = _P(sub) / exe
                if p.exists():
                    candidates.append(str(p))

    # 4) AppData\Local\Programs\Python\Python* (Microsoft Store / standard).
    for sub in glob.glob(str(_P.home()) + "/AppData/Local/Programs/Python/Python3*"):
        for exe in ("pythonw.exe", "python.exe"):
            p = _P(sub) / exe
            if p.exists() and "Python314" not in p.name:
                candidates.append(str(p))

    chosen = None
    for cand in candidates:
        if ".venv" in cand or not _P(cand).exists():
            continue
        if _clf_probe_tk(cand):
            chosen = cand
            break

    if chosen:
        try:
            subprocess.Popen(
                [chosen, str(_P(__file__).resolve())],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
        raise SystemExit(0)

    # No fallback -- show a Win32 MessageBox so the user actually sees something.
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None,
            (
                "Could not start the Classifier Observer GUI.\n\n"
                "Project venv Python ({}) could not initialize Tcl/Tk.\n\n"
                "Likely cause: this Python ships a tcl layout the bundled "
                "_tkinter does not recognize, causing tkinter.Tk() to "
                "raise TclError even when init.tcl is on disk.\n\n"
                "Fix options:\n"
                "  1. Set CLF_GUI_PYTHON to a Python with working tkinter, "
                "then double-click observer_gui.bat again.\n"
                "  2. From a regular shell: py -3.12 scripts\\observer_gui.py\n"
                "  3. Recreate .venv: py -3.12 -m venv .venv"
            ).format(sys.executable),
            "Classifier Observer -- Tk unavailable",
            0x10 | 0x1000,  # MB_ICONERROR | MB_SYSTEMMODAL
        )
    except Exception:
        pass
    raise SystemExit(0)


# Run the guard BEFORE the imports below (especially `import tkinter as tk`),
# so we can swap to a working Python (or surface a clear MessageBox error)
# before tkinter caches anything or tries to load its broken tcl library.
_clf_ensure_tk_works()


import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = REPO_ROOT / 'logs' / 'decisions.jsonl'
MAX_ROWS = 500
POLL_MS = 300
HEALTH_POLL_MS = 1000
HEALTH_URL = 'http://127.0.0.1:8765/health'
HEALTH_TIMEOUT_S = 0.5
VBS_PATH = REPO_ROOT / 'scripts' / 'run_hidden.vbs'
PY_EXE = REPO_ROOT / '.venv' / 'Scripts' / 'python.exe'
PYW_EXE = REPO_ROOT / '.venv' / 'Scripts' / 'pythonw.exe'

# A small palette inspired by VS Code dark+ (matches Claude Code's vibe).
BG          = '#1e1e1e'
BG_PANEL    = '#252526'
BG_HEADER   = '#2d2d30'
BG_ROW_ALT  = '#2a2a2c'
FG          = '#e0e0e0'
FG_DIM      = '#a0a0a0'
GRID_LINE   = '#3f3f46'
ACCENT_OK   = '#3fb950'   # green for allow
ACCENT_DENY = '#f85149'   # red for deny
ACCENT_ASK  = '#d29922'   # yellow for ask
FG_NEW_FLASH = '#ffffff'  # flash for new row


class DecisionRow(dict):
    """A dict-like row that also stores the raw JSON for the detail panel."""
    def __init__(self, raw: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self['raw'] = raw


class ObserverApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.rows: list[DecisionRow] = []
        self.last_size = 0
        self.tree_items: dict[str, str] = {}  # iid -> row index in self.rows

        self.health_state: dict = {'status': 'unknown', 'last_ok': None, 'last_attempt': 0.0}
        self._build_ui()
        self._load_existing()
        self._schedule_poll()
        self._schedule_health_poll()
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

    def _build_ui(self) -> None:
        self.root.title('Classifier Observer')
        self.root.configure(bg=BG)
        self.root.geometry('1180x720')
        self.root.minsize(800, 480)

        # Top bar -- split into two rows so the long log path and the
        # buttons don't fight for horizontal space with the title.
        #
        # Row 1: title (left)  |  service status indicator + detail
        # Row 2: log path + mtime + rows count (left)  |  Restart App,
        #        Restart Service, Clear (right)
        #
        # Outer frame holds the two rows.
        top_outer = tk.Frame(self.root, bg=BG_PANEL)
        top_outer.pack(fill='x')
        # Two row frames
        top1 = tk.Frame(top_outer, bg=BG_PANEL)
        top1.pack(fill='x')
        top2 = tk.Frame(top_outer, bg=BG_PANEL)
        top2.pack(fill='x')
        # Keep a back-reference for the legacy _set_status path that
        # used `self.path_label` -- the path now lives in top2.
        top = top1

        # ===== Row 1: title + service status =====
        tk.Label(
            top1, text='PreToolUse Hook Observer',
            bg=BG_PANEL, fg=FG,
            font=('Consolas', 12, 'bold'),
        ).pack(side='left', padx=(12, 0), pady=(8, 2))

        # Service status indicator (left-aligned, after the title)
        self.status_indicator = tk.Label(
            top1, text='  [ ] unknown  ', bg=BG_PANEL, fg='#a0a0a0',
            font=('Consolas', 9, 'bold'),
        )
        self.status_indicator.pack(side='left', padx=(20, 0), pady=(8, 2))
        self.status_detail = tk.Label(
            top1, text='', bg=BG_PANEL, fg=FG_DIM,
            font=('Consolas', 9),
        )
        self.status_detail.pack(side='left', padx=(0, 8), pady=(8, 2))

        # ===== Row 2: log path / mtime / rows (left) + buttons (right) =====
        self.path_label = tk.Label(
            top2, text='', bg=BG_PANEL, fg=FG_DIM,
            font=('Consolas', 9),
            anchor='w',
        )
        self.path_label.pack(side='left', fill='x', expand=True, padx=(12, 8), pady=(0, 6))

        # Buttons on the right of row 2, packed right-to-left so the
        # order reads: [Clear]  [Restart Service]  [Restart App]
        self.count_label = tk.Label(
            top2, text='0 decisions', bg=BG_PANEL, fg=FG_DIM,
            font=('Consolas', 9),
        )
        self.count_label.pack(side='right', padx=4, pady=(0, 6))

        self.clear_btn = tk.Button(
            top2, text='Clear', bg=BG_HEADER, fg=FG,
            activebackground='#094771', activeforeground=FG_NEW_FLASH,
            font=('Consolas', 9, 'bold'),
            relief='flat', bd=0, padx=12, pady=2,
            cursor='hand2', command=self._on_clear,
        )
        self.clear_btn.pack(side='right', padx=(0, 8), pady=(0, 6))
        self.clear_btn.bind('<Enter>', lambda e: self.clear_btn.config(bg='#094771'))
        self.clear_btn.bind('<Leave>', lambda e: self.clear_btn.config(bg=BG_HEADER))

        # Restart service button: restart the uvicorn classifier service.
        self.restart_btn = tk.Button(
            top2, text='Restart Service', bg=BG_HEADER, fg=FG,
            activebackground='#bc3a2f', activeforeground=FG_NEW_FLASH,
            font=('Consolas', 9, 'bold'),
            relief='flat', bd=0, padx=12, pady=2,
            cursor='hand2', command=self._on_restart,
        )
        self.restart_btn.pack(side='right', padx=(0, 4), pady=(0, 6))
        self.restart_btn.bind('<Enter>', lambda e: self.restart_btn.config(bg='#bc3a2f'))
        self.restart_btn.bind('<Leave>', lambda e: self.restart_btn.config(bg=BG_HEADER))

        # Restart App button: restart the GUI itself (re-runs observer_gui.py
        # so code changes take effect). The new GUI is spawned via the
        # same vbs launcher, so no console window flashes.
        self.restart_app_btn = tk.Button(
            top2, text='Restart App', bg=BG_HEADER, fg=FG,
            activebackground='#3fb950', activeforeground=FG_NEW_FLASH,
            font=('Consolas', 9, 'bold'),
            relief='flat', bd=0, padx=12, pady=2,
            cursor='hand2', command=self._on_restart_app,
        )
        self.restart_app_btn.pack(side='right', padx=(0, 4), pady=(0, 6))
        self.restart_app_btn.bind('<Enter>', lambda e: self.restart_app_btn.config(bg='#3fb950'))
        self.restart_app_btn.bind('<Leave>', lambda e: self.restart_app_btn.config(bg=BG_HEADER))

        # Back-reference: legacy code (and _set_count) expects self.path_label
        # to exist. We've moved it to top2; alias it here for clarity.
        # (No-op: path_label is already defined above.)

        # Main paned window: list on top, detail on bottom ---------------
        paned = tk.PanedWindow(
            self.root, orient='vertical', sashwidth=6,
            bg=BG, bd=0, sashpad=2,
        )
        paned.pack(fill='both', expand=True, padx=8, pady=(8, 4))

        # Tree (top)
        tree_frame = tk.Frame(paned, bg=BG_PANEL)
        paned.add(tree_frame, minsize=180, stretch='always')

        columns = ('time', 'tool', 'decision', 'permission', 'rule', 'ms', 'reason')
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show='headings', selectmode='browse',
        )
        widths = {'time': 110, 'tool': 80, 'decision': 90,
                  'permission': 100, 'rule': 280, 'ms': 50, 'reason': 360}
        for col in columns:
            self.tree.heading(col, text=col.title())
            anchor = 'e' if col == 'ms' else 'w'
            self.tree.column(col, width=widths[col], anchor=anchor, stretch=(col == 'reason'))
        self.tree.tag_configure('odd', background=BG_PANEL)
        self.tree.tag_configure('even', background=BG_ROW_ALT)
        self.tree.tag_configure('allow_odd', background=BG_PANEL, foreground=ACCENT_OK)
        self.tree.tag_configure('allow_even', background=BG_ROW_ALT, foreground=ACCENT_OK)
        self.tree.tag_configure('deny_odd', background=BG_PANEL, foreground=ACCENT_DENY)
        self.tree.tag_configure('deny_even', background=BG_ROW_ALT, foreground=ACCENT_DENY)
        self.tree.tag_configure('ask_odd', background=BG_PANEL, foreground=ACCENT_ASK)
        self.tree.tag_configure('ask_even', background=BG_ROW_ALT, foreground=ACCENT_ASK)
        self.tree.tag_configure('flash', background='#094771', foreground=FG_NEW_FLASH)

        # Vertical scrollbar. Standard ttk behavior: visible whenever
        # the row count exceeds the visible area. When the list is
        # short the scrollbar is auto-hidden by Tk -- that is the
        # intended behavior. The yscrollcommand/command pair wires
        # the treeview and the scrollbar together so mouse-wheel and
        # scrollbar drag both work.
        ysb = ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        ysb.pack(side='right', fill='y')

        self.tree.bind('<<TreeviewSelect>>', self._on_select)

        # Detail (bottom)
        detail_frame = tk.Frame(paned, bg=BG_PANEL)
        paned.add(detail_frame, minsize=120, stretch='always')

        tk.Label(
            detail_frame, text='Selected decision (full JSON):',
            bg=BG_PANEL, fg=FG_DIM,
            font=('Consolas', 9),
            anchor='w',
        ).pack(fill='x', padx=8, pady=(6, 0))

        detail_text_frame = tk.Frame(detail_frame, bg=BG_PANEL)
        detail_text_frame.pack(fill='both', expand=True, padx=8, pady=(2, 8))

        self.detail = tk.Text(
            detail_text_frame, bg='#1a1a1a', fg='#d4d4d4',
            insertbackground=FG, relief='flat', wrap='char',
            font=('Consolas', 10), state='disabled',
        )
        d_ysb = ttk.Scrollbar(detail_text_frame, orient='vertical', command=self.detail.yview)
        self.detail.configure(yscrollcommand=d_ysb.set)
        d_ysb.pack(side='right', fill='y')
        self.detail.pack(side='left', fill='both', expand=True)

        # Tags used by _show_detail() to visually separate the three
        # sections (summary / request / raw). Summary is bright white,
        # section headers are dim grey, request body is the standard
        # foreground, raw JSON is even dimmer. The "dim" tag is used
        # when the request field is missing (older log entries that
        # were written before tool_input was added to the logger).
        self.detail.tag_configure("summary", foreground="#ffffff", font=("Consolas", 10, "bold"))
        self.detail.tag_configure("section", foreground=FG_DIM, font=("Consolas", 9, "bold"))
        self.detail.tag_configure("request", foreground=FG)
        self.detail.tag_configure("raw", foreground=FG_DIM)
        self.detail.tag_configure("dim", foreground="#707070")

        # Status bar at very bottom
        self.status = tk.Label(
            self.root, text='', bg=BG_PANEL, fg=FG_DIM,
            font=('Consolas', 9), anchor='w',
        )
        self.status.pack(fill='x', side='bottom')

        # Style the ttk
        style = ttk.Style()
        style.configure('Treeview',
                        background=BG_PANEL, foreground=FG, fieldbackground=BG_PANEL,
                        bordercolor=GRID_LINE, rowheight=22, font=('Consolas', 9))
        style.configure('Treeview.Heading',
                        background=BG_HEADER, foreground=FG,
                        font=('Consolas', 9, 'bold'))
        style.map('Treeview', background=[('selected', '#094771')],
                  foreground=[('selected', '#ffffff')])

    def _set_status(self, text: str) -> None:
        self.status.config(text=text)

    def _set_count(self) -> None:
        n = len(self.rows)
        self.count_label.config(text=f'{n} decision{"s" if n != 1 else ""}')

    # ------------------------------------------------------------------
    # File tail / state
    # ------------------------------------------------------------------
    def _load_existing(self) -> None:
        self.path_label.config(text=f'  |  log: {LOG_FILE}')
        if not LOG_FILE.exists():
            self._set_status(f'log file not found: {LOG_FILE}')
            self._refresh_path_mtime()
            return
        try:
            text = LOG_FILE.read_text(encoding='utf-8', errors='replace')
            self.last_size = LOG_FILE.stat().st_size
        except OSError as e:
            self._set_status(f'cannot read log: {e}')
            return
        for line in text.splitlines():
            self._consume_line(line, initial=True)
        self._set_status(f'loaded {len(self.rows)} historical decisions')
        self._refresh_path_mtime()

    def _refresh_path_mtime(self) -> None:
        # Cheap: just stat the file and update the label. No file
        # reads, no row mutations -- that would be done by
        # _poll_file. Safe to call on every health tick.
        try:
            mtime = LOG_FILE.stat().st_mtime
        except OSError:
            return
        import datetime as _dt
        ts = _dt.datetime.fromtimestamp(mtime).strftime('%H:%M:%S')
        n = len(self.rows)
        try:
            self.path_label.config(
                text=f'  |  log: {LOG_FILE}  |  mtime: {ts}  |  rows: {n}'
            )
        except Exception:
            pass

    @staticmethod
    def _format_time(iso_ts: str) -> str:
        """Render an ISO-8601 timestamp as a compact human-readable time.

        Examples:
          2026-07-11T16:32:18.659247+00:00 -> 16:32:18.659
          2026-07-11T16:32:18.659+00:00    -> 16:32:18.659
          (any other / unparseable)         -> the original string

        The classifier service writes ts in ISO format with sub-second
        precision and a +00:00 suffix. We strip both for display -- the
        GUI window is seconds-level, not microseconds, and timezone
        offset is noise (everything is UTC anyway since the service is
        local).
        """
        if not iso_ts:
            return ""
        # ISO format: YYYY-MM-DDTHH:MM:SS[.ffffff][+HH:MM]
        # We want HH:MM:SS.fff -- so split on T, take the second part,
        # then keep everything up to the first + or Z.
        try:
            t = iso_ts.split("T", 1)[1] if "T" in iso_ts else iso_ts
            # Trim trailing timezone offset ("+00:00", "-05:00", "Z")
            for sep in ("+", "-", "Z"):
                if sep in t[1:]:  # skip leading "-" check, look past index 0
                    idx = t.index(sep, 1)
                    t = t[:idx]
                    break
            # t is now HH:MM:SS[.ffffff]. Trim to milliseconds.
            if "." in t:
                hh, rest = t.split(":", 1)
                mm_ss, frac = rest.split(".", 1)
                frac = (frac + "000")[:3]  # pad to at least 3, then keep 3
                return f"{hh}:{mm_ss}.{frac}"
            return t
        except Exception:
            # Fallback: just return what we have, never crash the GUI.
            return iso_ts

    def _consume_line(self, line: str, initial: bool = False) -> None:
        """Parse one log line into a DecisionRow and insert it into the tree.

        Called both for historical replay (initial=True) and live poll
        tailing (initial=False). Skips non-decision lines, parses JSON,
        inserts at the top of the list (newest-first) and registers the
        row in the Treeview.
        """
        line = line.strip()
        if not line:
            return
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return
        if obj.get('message') != 'decision':
            return

        row = DecisionRow(
            raw=line,
            time=self._format_time(obj.get('ts', '')),
            tool=obj.get('tool', ''),
            decision=obj.get('decision', ''),
            permission=obj.get('permission_decision', ''),
            rule=(obj.get('matched_rule') or '-') or '-',
            ms=obj.get('took_ms', ''),
            reason=obj.get('reason', '') or '',
        )
        # newest first
        self.rows.insert(0, row)
        while len(self.rows) > MAX_ROWS:
            self.rows.pop()

        values = (row['time'], row['tool'], row['decision'], row['permission'],
                  row['rule'], row['ms'], row['reason'])
        idx = 0  # newest
        parity = 'odd' if (len(self.tree.get_children()) % 2 == 0) else 'even'
        perm = (row['permission'] or '').lower()
        if perm == 'allow':
            tag_prefix = 'allow'
        elif perm == 'deny':
            tag_prefix = 'deny'
        elif perm == 'ask':
            tag_prefix = 'ask'
        else:
            tag_prefix = ''
        # Always build a TUPLE so the optional ('flash',) below can be
        # concatenated regardless of whether tag_prefix is set.
        base = (tag_prefix + '_' + parity) if tag_prefix else parity
        if not initial:
            tags = (base, 'flash')
        else:
            tags = (base,)
        # Tk Treeview quirk: insert(..., index=0) does not always
        # place the new item at the visual top -- it depends on the
        # version. Use 'end' + move('', 0) for a reliable "newest
        # first" ordering that matches self.rows (which is itself
        # newest-first via insert(0, ...)).
        iid = self.tree.insert('', 'end', values=values, tags=tags)
        self.tree.move(iid, '', 0)
        self.tree_items[iid] = row['time'] + '|' + row['tool']
        self._set_count()

    def _schedule_poll(self) -> None:
        self._poll_file()
        self.root.after(POLL_MS, self._schedule_poll)

    def _poll_file(self) -> None:
        if not LOG_FILE.exists():
            return
        try:
            cur = LOG_FILE.stat().st_size
        except OSError:
            return
        if cur == self.last_size:
            return
        if cur < self.last_size:
            # truncated/rotated
            self.last_size = 0
        try:
            with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(self.last_size)
                delta = f.read()
                self.last_size = f.tell()
        except OSError as e:
            self._set_status(f'read error: {e}')
            return
        added = 0
        for ln in delta.splitlines():
            before = len(self.rows)
            self._consume_line(ln)
            if len(self.rows) > before:
                added += 1
        if added:
            self._set_status(f'+{added} new decision{"s" if added != 1 else ""} '
                             f'(total: {len(self.rows)})')
            # Force the Treeview to redraw and the label to refresh.
            self._refresh_path_mtime()
            self.tree.update_idletasks()
            self.tree.see(self.tree.get_children()[0] if self.tree.get_children() else '')

    def _on_select(self, _evt=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        values = self.tree.item(iid, 'values')
        if not values:
            return
        # find the row whose signature matches
        sig = values[0] + '|' + values[1]
        for row in self.rows:
            if row['time'] + '|' + row['tool'] == sig:
                self._show_detail(row['raw'])
                return

    def _show_detail(self, raw: str) -> None:
        """Render the selected decision as readable text in the detail panel.

        Layout (top to bottom):
          1. A summary line -- tool + decision + permission + rule + ms
          2. Tool-specific request section -- the actual payload that was
             sent for approval. This is the part the user wants to see
             (e.g. the Bash command, the Edit diff, the Read target).
          3. Full JSON -- everything else (timestamps, request_id, etc.).

        We split rendering this way because the user has said the
        request details are the most useful part of the row, and they
        deserve more visual weight than the surrounding metadata.
        """
        try:
            obj = json.loads(raw)
        except Exception:
            obj = None

        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")

        if obj is None:
            self.detail.insert("1.0", raw)
            self.detail.configure(state="disabled")
            return

        # ----- 1. Summary line -----------------------------------------
        tool = obj.get("tool", "-")
        decision = obj.get("decision", "-")
        perm = obj.get("permission_decision", "-")
        rule = obj.get("matched_rule") or "-"
        took_ms = obj.get("took_ms", "-")
        summary = f"tool: {tool}    decision: {decision}    permission: {perm}    rule: {rule}    took_ms: {took_ms}ms"
        self.detail.insert("end", summary + "\n\n", "summary")

        # ----- 2. Tool-specific request section ------------------------
        tool_input = obj.get("tool_input")
        if tool_input:
            rendered = self._render_tool_input(tool, tool_input)
            if rendered:
                self.detail.insert("end", "---- Request ----\n", "section")
                self.detail.insert("end", rendered + "\n\n", "request")
            else:
                self.detail.insert("end", "---- Request ----\n", "section")
                self.detail.insert("end", json.dumps(tool_input, indent=2, ensure_ascii=False) + "\n\n", "request")
        else:
            self.detail.insert("end", "---- Request ----\n", "section")
            self.detail.insert("end", "(not captured in log -- restart classifier service to see this)\n\n", "dim")

        # ----- 3. Full JSON -------------------------------------------
        self.detail.insert("end", "---- Full log entry ----\n", "section")
        self.detail.insert("end", json.dumps(obj, indent=2, ensure_ascii=False), "raw")

        self.detail.configure(state="disabled")

    @staticmethod
    def _render_tool_input(tool: str, tool_input: Any) -> str:
        """Render a tool_input dict into a human-readable string.

        Returns an empty string if the input is empty or not a dict (the
        caller falls back to a generic JSON dump in that case).

        The rendered output is plain text -- no markup -- because the
        detail Text widget has its own tags ("section", "request", etc.)
        applied by the caller. We just produce the content; the caller
        decides how to tag it.
        """
        if not isinstance(tool_input, dict) or not tool_input:
            return ""

        lines: list[str] = []

        # Most tools have a "command" / "file_path" / "content" / etc.
        # We surface the fields the user actually cares about first, then
        # dump everything else as "key: value" pairs.

        # Tool-specific highlights
        if tool == "Bash":
            cmd = tool_input.get("command", "")
            desc = tool_input.get("description", "")
            if desc:
                lines.append(f"description: {desc}")
            if cmd:
                lines.append("command:")
                # Indent multi-line commands so they read as a block
                for cl in str(cmd).splitlines() or [str(cmd)]:
                    lines.append(f"  {cl}")
        elif tool == "Read":
            fp = tool_input.get("file_path", "")
            offset = tool_input.get("offset")
            limit = tool_input.get("limit")
            if fp:
                lines.append(f"file_path: {fp}")
            if offset is not None:
                lines.append(f"offset: {offset}")
            if limit is not None:
                lines.append(f"limit: {limit}")
        elif tool in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
            fp = tool_input.get("file_path", "") or tool_input.get("notebook_glob", "")
            if fp:
                lines.append(f"file_path: {fp}")
            old = tool_input.get("old_string")
            new = tool_input.get("new_string")
            if old is not None or new is not None:
                lines.append("--- old_string ---")
                if old is not None:
                    for ol in str(old).splitlines() or [str(old)]:
                        lines.append(f"  {ol}")
                lines.append("--- new_string ---")
                if new is not None:
                    for nl in str(new).splitlines() or [str(new)]:
                        lines.append(f"  {nl}")
            content = tool_input.get("content")
            if content is not None:
                lines.append("--- content ---")
                for cl in str(content).splitlines() or [str(content)]:
                    lines.append(f"  {cl}")
            if tool_input.get("replace_all"):
                lines.append("replace_all: true")

        # Generic fallback / extra fields the user might want to see
        # (anything not handled above)
        handled_keys = {
            "command", "description", "file_path", "offset", "limit",
            "old_string", "new_string", "content", "replace_all",
            "notebook_glob",
        }
        extras = {k: v for k, v in tool_input.items() if k not in handled_keys}
        if extras:
            lines.append("--- other fields ---")
            for k, v in extras.items():
                # Truncate very long values to keep the panel readable
                vs = str(v)
                if len(vs) > 400:
                    vs = vs[:400] + "..."
                lines.append(f"{k}: {vs}")

        return "\n".join(lines)

    def _on_close(self) -> None:
        """Window close handler -- bound to WM_DELETE_WINDOW in __init__.

        Also called by Restart App (via self.root.after) after a fresh
        GUI has been spawned and has had a moment to start up.

        The polling/health threads are daemon threads, so they exit
        automatically when the interpreter is about to -- calling
        root.destroy() is enough; we do not need to join them explicitly.
        """
        try:
            self.root.destroy()
        except Exception:
            # If the root is already gone (e.g. we got here via a
            # double-close from WM_DELETE_WINDOW + manual destroy),
            # swallow it rather than crash with an unhelpful TclError.
            pass

    def _on_clear(self) -> None:
        # Clear the in-memory list, the tree, and the detail panel.
        # Does NOT touch the underlying log file -- the next poll will
        # re-read any new lines that arrived while we were empty.
        self.rows.clear()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.tree_items.clear()
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.configure(state='disabled')
        self._set_count()
        self._set_status('cleared')

    # ------------------------------------------------------------------
    # Service health
    # ------------------------------------------------------------------
    def _schedule_health_poll(self) -> None:
        self._check_health()
        self.root.after(HEALTH_POLL_MS, self._schedule_health_poll)

    def _check_health(self) -> None:
        # Run the blocking urllib call in a worker thread to keep the
        # Tk main loop responsive. The result is posted back to the
        # UI thread via root.after.
        t = threading.Thread(target=self._do_health_request, daemon=True)
        t.start()

    def _do_health_request(self) -> None:
        t0 = time.time()
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=HEALTH_TIMEOUT_S) as resp:
                body = resp.read().decode('utf-8', errors='replace')
                latency_ms = int((time.time() - t0) * 1000)
                self.root.after(0, self._apply_health, True, body, latency_ms, None)
        except Exception as e:  # noqa: BLE001
            self.root.after(0, self._apply_health, False, '', 0, e)

    def _apply_health(self, ok: bool, body: str, latency_ms: int, err: Exception | None) -> None:
        # Every health tick (1s), also refresh the log-mtime label so
        # the user can tell at a glance whether new decisions are arriving.
        self._refresh_path_mtime()
        if ok:
            self.health_state = {
                'status': 'ok',
                'last_ok': time.time(),
                'last_attempt': time.time(),
                'latency_ms': latency_ms,
            }
            # Try to extract rules count for the detail line
            detail = ''
            try:
                obj = json.loads(body)
                rules_n = obj.get('rules', '?')
                fb = obj.get('claude_fallback', False)
                detail = f'  {rules_n} rules  claude_fb={fb}  {latency_ms}ms'
            except Exception:
                detail = f'  {latency_ms}ms'
            self.status_indicator.config(text='  [\u25CF] healthy  ', fg=ACCENT_OK)
            self.status_detail.config(text=detail)
        else:
            self.health_state = {
                'status': 'down',
                'last_ok': self.health_state.get('last_ok'),
                'last_attempt': time.time(),
            }
            msg = f'  ({type(err).__name__})' if err else ''
            self.status_indicator.config(text='  [\u25CF] offline  ', fg=ACCENT_DENY)
            self.status_detail.config(text=msg)

    # ------------------------------------------------------------------
    # Restart
    # ------------------------------------------------------------------
    def _on_restart(self) -> None:
        # Confirm with the user (a restart kills the running service).
        ok = messagebox.askyesno(
            'Restart classifier service?',
            'Stop the currently running uvicorn process and start a fresh one.\n'
            'Hook requests in flight may be delayed.\n\n'
            'Proceed?',
        )
        if not ok:
            return
        # Disable the button to prevent double-clicks
        self.restart_btn.config(state='disabled', text='Restarting...')
        self._set_status('restarting classifier service...')
        # Run the actual work in a thread; post completion back to the UI.
        threading.Thread(target=self._do_restart, daemon=True).start()

    def _do_restart(self) -> None:
        def log(msg: str) -> None:
            self.root.after(0, lambda: self._set_status(msg))

        log('stopping existing uvicorn processes...')
        try:
            self._stop_uvicorn()
        except Exception as e:  # noqa: BLE001
            log(f'stop failed: {e}')
        time.sleep(0.8)
        log('starting fresh uvicorn (via run_hidden.vbs)...')
        try:
            self._start_uvicorn()
        except Exception as e:  # noqa: BLE001
            self.root.after(0, lambda: (
                self.restart_btn.config(state='normal', text='Restart Service'),
                messagebox.showerror('Restart failed', f'Could not start uvicorn:\n{e}'),
            ))
            return
        # Wait for health to come back
        log('waiting for /health...')
        deadline = time.time() + 8.0
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(HEALTH_URL, timeout=0.5) as resp:
                    if 200 <= resp.status < 300:
                        self.root.after(0, lambda: (
                            self.restart_btn.config(state='normal', text='Restart Service'),
                            self._set_status('service restarted'),
                        ))
                        return
            except Exception:
                pass
            time.sleep(0.2)
        self.root.after(0, lambda: (
            self.restart_btn.config(state='normal', text='Restart Service'),
            self._set_status('restart timed out (8s)'),
            messagebox.showwarning(
                'Restart timeout',
                'Service did not respond on http://127.0.0.1:8765/health within 8 seconds.\n'
                'Check logs/service.log for details.',
            ),
        ))

    def _stop_uvicorn(self) -> None:
        # Use taskkill to terminate python processes that are running
        # uvicorn with our app. We filter by command-line containing
        # 'classifier.main:app' so we don't kill the observer itself
        # or unrelated python processes.
        ps_cmd = [
            'powershell', '-NoProfile', '-Command',
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -like '*classifier.main:app*' } | "
            "Select-Object -ExpandProperty ProcessId",
        ]
        try:
            r = subprocess.run(
                ps_cmd, capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except Exception as e:
            raise RuntimeError(f'failed to enumerate uvicorn processes: {e}')
        pids = [int(line.strip()) for line in r.stdout.splitlines() if line.strip().isdigit()]
        for pid in pids:
            try:
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(pid)],
                    capture_output=True, timeout=5,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
            except Exception:
                pass

    def _start_uvicorn(self) -> None:
        # Build the inner command: .venv\Scripts\python.exe -m uvicorn
        # classifier.main:app --host 127.0.0.1 --port 8765
        inner = (
            f'\"{PY_EXE}\" -m uvicorn classifier.main:app '
            '--host 127.0.0.1 --port 8765 --log-level info'
        )
        # Use pythonw.exe to avoid a console window flash on the first
        # launch. vbs will run pythonw via wscript, but the launched
        # pythonw.exe is GUI subsystem (no console allocation at all).
        # We still wrap in vbs for belt-and-braces window hiding.
        # Note: using pythonw for uvicorn means log capture is the only
        # stdout path -- we accept that (uvicorn already writes to
        # logs/service.log via the redirect in hook_bridge._spawn_service).
        py_for_uvicorn = PYW_EXE if PYW_EXE.exists() else PY_EXE
        inner_pyw = (
            f'\"{py_for_uvicorn}\" -m uvicorn classifier.main:app '
            '--host 127.0.0.1 --port 8765 --log-level info'
        )
        # Service log file
        log_dir = REPO_ROOT / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        log_fp = open(log_dir / 'service.log', 'ab', buffering=0)
        # Launch via wscript + vbs (no flash). We pass the inner cmd as a
        # single pre-quoted argument (vbs joins WScript.Arguments with
        # re-quoting, so a single pre-quoted token comes through cleanly).
        subprocess.Popen(
            ['wscript.exe', '//nologo', str(VBS_PATH), inner_pyw],
            stdin=subprocess.DEVNULL, stdout=log_fp, stderr=log_fp,
            close_fds=True,
        )

    # ------------------------------------------------------------------
    # Restart App (restart the GUI itself with the latest code)
    # ------------------------------------------------------------------
    def _on_restart_app(self) -> None:
        # Confirm with the user. A restart closes this window and
        # opens a fresh one -- any unsaved UI state is lost (the new
        # GUI re-reads the log on startup, so all decisions are
        # preserved).
        ok = messagebox.askyesno(
            'Restart App?',
            'Close this window and start a fresh GUI process.\n'
            'Use this after editing observer_gui.py -- the new\n'
            'process picks up your code changes automatically.\n\n'
            'Proceed?',
        )
        if not ok:
            return
        # Disable both restart buttons to prevent double-clicks.
        self.restart_app_btn.config(state='disabled', text='Restarting...')
        self.restart_btn.config(state='disabled')
        self._set_status('spawning fresh GUI...')
        # Spawn the new GUI in a worker thread so the current GUI
        # can shut down cleanly without blocking.
        threading.Thread(target=self._do_restart_app, daemon=True).start()

    def _do_restart_app(self) -> None:
        try:
            self._spawn_fresh_gui()
        except Exception as e:  # noqa: BLE001
            self.root.after(0, lambda: (
                self.restart_app_btn.config(state='normal', text='Restart App'),
                self.restart_btn.config(state='normal'),
                messagebox.showerror('Restart failed', f'Could not restart GUI:\n{e}'),
            ))
            return
        # Give the child ~300ms to start, then close this GUI.
        time.sleep(0.3)
        self.root.after(0, self._on_close)

    def _spawn_fresh_gui(self) -> None:
        # Find the vbs launcher (prefer it for zero-console-window spawn).
        vbs_path = VBS_PATH  # module-level constant from earlier patch
        if not vbs_path.exists():
            raise RuntimeError(f'run_hidden.vbs not found at {vbs_path}')
        # Pass a FLAT TOKEN LIST (not a pre-quoted string) to vbs.
        # run_hidden.vbs reads WScript.Arguments and re-quotes each token
        # itself with double quotes -- so a pre-quoted string here would
        # get double-wrapped and WScript.Shell.Run would fail to find
        # the resulting filename (Windows error 80070002).
        #
        # The flat-token form is the same pattern the hook itself uses
        # in ~/.claude/settings.json:
        #     wscript.exe //nologo run_hidden.vbs python.exe -m ...
        #
        # vbs then joins with quoted spaces and calls WScript.Shell.Run
        # with WindowStyle=0 (SW_HIDE) so the new pythonw.exe GUI starts
        # without a console flash. WaitOnReturn=False detaches wscript
        # from the child so it returns immediately.
        subprocess.Popen(
            [
                'wscript.exe',
                '//nologo',
                str(vbs_path),
                str(PYW_EXE),
                str(Path(__file__).resolve()),
            ],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
        )
        # NOTE: we do NOT call self.root.destroy() here. _do_restart_app()
        # waits ~300ms (so the child GUI has a chance to appear first) and
        # then schedules _on_close on the Tk thread via root.after(). Calling
        # destroy() synchronously from this worker thread would close the
        # window before the new process has had time to start, which can
        # leave the user staring at a blank screen for a moment.


def main() -> int:
    root = tk.Tk()
    app = ObserverApp(root)
    root.mainloop()
    return 0

if __name__ == '__main__':
    raise SystemExit(main())