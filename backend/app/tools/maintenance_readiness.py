from __future__ import annotations

import argparse
import json

from app.database import init_db, session_scope
from app.services.maintenance import DEFAULT_IDLE_GRACE_SECONDS, maintenance_readiness, override_active_sessions


def main() -> int:
    parser = argparse.ArgumentParser(description="Report whether Medusa maintenance can safely run.")
    parser.add_argument("--idle-grace-seconds", type=int, default=DEFAULT_IDLE_GRACE_SECONDS)
    parser.add_argument("--ignore-active-sessions", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    init_db()
    with session_scope() as db:
        payload = maintenance_readiness(db, idle_grace_seconds=args.idle_grace_seconds)
    if args.ignore_active_sessions:
        payload = override_active_sessions(payload)
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print("Ready" if payload["idle"] else "; ".join(payload["blockers"]))
    return 0 if payload["idle"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
