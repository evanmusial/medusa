from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.database import init_db, session_scope
from app.services.restore import RestoreValidationError, load_export_file, restore_metadata_export


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = load_export_file(str(args.export_path))

    try:
        init_db()
        with session_scope() as db:
            result = restore_metadata_export(
                db,
                payload,
                dry_run=not args.apply,
                preserve_ids=not args.regenerate_ids,
                park_active_jobs=not args.reactivate_jobs,
            )
    except RestoreValidationError as exc:
        print(f"Restore validation failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0

    _print_summary(result)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate, dry-run, or apply a Medusa metadata export restore.")
    parser.add_argument("export_path", type=Path, help="Path to a medusa-metadata JSON export.")
    parser.add_argument("--apply", action="store_true", help="Write restore data to the configured database.")
    parser.add_argument(
        "--regenerate-ids",
        action="store_true",
        help="Create new IDs instead of preserving IDs from the export.",
    )
    parser.add_argument(
        "--reactivate-jobs",
        action="store_true",
        help="Restore queued/running job statuses as-is instead of parking them as restored_paused.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full restore report as JSON.")
    return parser.parse_args(argv)


def _print_summary(result: dict[str, Any]) -> None:
    mode = "APPLY" if result.get("applied") else "DRY RUN"
    print(f"Medusa metadata restore: {mode}")
    print(f"Schema version: {result.get('schema_version')}")
    print(f"Valid: {result.get('valid')}")
    print("")
    print("Sections:")
    for key, value in sorted(result.get("counts", {}).items()):
        print(f"  {key}: {value}")

    restored_counts = result.get("restored_counts") or {}
    if restored_counts:
        print("")
        print("Restored:")
        for key, value in sorted(restored_counts.items()):
            print(f"  {key}: {value}")

    skipped = result.get("skipped") or {}
    skipped_rows = result.get("skipped_rows") or {}
    if skipped or skipped_rows:
        print("")
        print("Skipped:")
        for key, value in sorted({**skipped, **skipped_rows}.items()):
            if value:
                print(f"  {key}: {value}")

    conflicts = result.get("conflicts") or {}
    if conflicts:
        print("")
        print("Existing conflicts/matches:")
        for key, value in sorted(conflicts.items()):
            print(f"  {key}: {len(value)}")

    warnings = result.get("warnings") or []
    if warnings:
        print("")
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")

    if not result.get("applied"):
        print("")
        print("No database writes were made. Re-run with --apply to restore this export.")


if __name__ == "__main__":
    raise SystemExit(main())
