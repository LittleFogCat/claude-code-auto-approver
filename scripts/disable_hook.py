"""One-shot: temporarily disable PreToolUse hook in ~/.claude/settings.json.

Usage:
    python scripts/disable_hook.py        # actually disable
    python scripts/disable_hook.py --dry  # preview the change, don't write

To restore, run scripts/install_hook.py.
"""
import argparse, json, pathlib, sys

p = pathlib.Path.home() / ".claude" / "settings.json"

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="print the change but do not write")
    args = ap.parse_args()

    if not p.exists():
        print(f"settings.json not found at {p}", file=sys.stderr)
        return 1
    d = json.loads(p.read_text(encoding="utf-8"))
    d.setdefault("hooks", {})["PreToolUse"] = []
    new = json.dumps(d, indent=2)

    if args.dry:
        print(new)
        return 0
    p.write_text(new, encoding="utf-8")
    print(f"disabled. restore with: python scripts/install_hook.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
