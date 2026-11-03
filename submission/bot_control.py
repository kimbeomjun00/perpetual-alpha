"""Local control panel for the Perpetual Alpha runner.

This program never submits a market action.  It writes a local command that
the *already running* bot reads on its next polling cycle.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).parent
RUNTIME = ROOT / "runtime"
CONTROL_FILE = RUNTIME / "control.json"
STATUS_FILE = RUNTIME / "status.json"


def now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("pause", "resume", "flatten", "status"))
    args = parser.parse_args()

    if args.action == "status":
        status = read_json(STATUS_FILE)
        if status is None:
            print("No status yet. Start the shadow runner first.")
            return 1
        print(json.dumps(status, indent=2))
        return 0

    command = "pause" if args.action == "pause" else "run" if args.action == "resume" else "flatten"
    write_json(CONTROL_FILE, {"command": command, "requested_at_utc": now_utc()})
    messages = {
        "pause": "Pause requested: the runner will not open new positions.",
        "resume": "Resume requested: the runner may evaluate new entries again.",
        "flatten": "STOP & FLATTEN requested: the runner will cancel orders and close positions in live mode, then stop.",
    }
    print(messages[args.action])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
