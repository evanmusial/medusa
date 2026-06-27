from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.services.google_credentials import load_service_account_credentials
from app.services.preferences import get_gcs_bucket, get_google_project_id, get_google_service_account_path


STORAGE_CLASS_LABELS = {
    "STANDARD": "Standard",
    "NEARLINE": "Nearline",
    "COLDLINE": "Coldline",
    "ARCHIVE": "Archive",
    "REGIONAL": "Regional",
    "MULTI_REGIONAL": "Multi-Regional",
    "DURABLE_REDUCED_AVAILABILITY": "Durable Reduced Availability",
}


def _storage_class_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "Unknown"
    return STORAGE_CLASS_LABELS.get(text.upper(), text.replace("_", " ").title())


def _plural(value: int, singular: str, plural: str | None = None) -> str:
    return f"{value} {singular if value == 1 else plural or singular + 's'}"


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _format_date(value: Any) -> str:
    return str(value).split("T", 1)[0]


def _condition_labels(condition: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    age = condition.get("age")
    if isinstance(age, int):
        labels.append(f"after {_plural(age, 'day')}")
    for key, label in (
        ("createdBefore", "created before"),
        ("customTimeBefore", "custom time before"),
        ("noncurrentTimeBefore", "became noncurrent before"),
    ):
        if condition.get(key):
            labels.append(f"{label} {_format_date(condition[key])}")
    days_since_custom_time = condition.get("daysSinceCustomTime")
    if isinstance(days_since_custom_time, int):
        labels.append(f"{_plural(days_since_custom_time, 'day')} after custom time")
    days_since_noncurrent_time = condition.get("daysSinceNoncurrentTime")
    if isinstance(days_since_noncurrent_time, int):
        labels.append(f"{_plural(days_since_noncurrent_time, 'day')} after becoming noncurrent")
    num_newer_versions = condition.get("numNewerVersions")
    if isinstance(num_newer_versions, int):
        labels.append(f"when at least {_plural(num_newer_versions, 'newer version')} exists")
    if "isLive" in condition:
        labels.append("live objects only" if condition.get("isLive") else "noncurrent versions only")
    prefixes = _string_list(condition.get("matchesPrefix"))
    if prefixes:
        labels.append("prefix " + ", ".join(prefixes))
    suffixes = _string_list(condition.get("matchesSuffix"))
    if suffixes:
        labels.append("suffix " + ", ".join(suffixes))
    storage_classes = _string_list(condition.get("matchesStorageClass"))
    if storage_classes:
        labels.append("currently " + ", ".join(_storage_class_label(item) for item in storage_classes))
    return labels or ["all objects"]


def _action_label(action: dict[str, Any]) -> tuple[str, str | None]:
    action_type = str(action.get("type") or "Unknown")
    if action_type == "SetStorageClass":
        storage_class = _storage_class_label(action.get("storageClass"))
        return f"Move to {storage_class}", storage_class
    if action_type == "Delete":
        return "Delete", None
    if action_type == "AbortIncompleteMultipartUpload":
        return "Abort incomplete multipart upload", None
    return action_type.replace("_", " "), None


def _rule_out(raw_rule: dict[str, Any], index: int) -> dict[str, Any]:
    action = raw_rule.get("action") if isinstance(raw_rule.get("action"), dict) else {}
    condition = raw_rule.get("condition") if isinstance(raw_rule.get("condition"), dict) else {}
    action_label, storage_class = _action_label(action)
    condition_labels = _condition_labels(condition)
    return {
        "index": index,
        "action_type": str(action.get("type") or "Unknown"),
        "action_label": action_label,
        "storage_class": storage_class,
        "condition_labels": condition_labels,
        "summary": f"{action_label} when {'; '.join(condition_labels)}.",
    }


def _summary_for_rules(rules: list[dict[str, Any]]) -> str:
    if not rules:
        return "No lifecycle rules are configured. Objects stay in their current storage class until changed or deleted manually."
    transition_count = sum(1 for rule in rules if rule["action_type"] == "SetStorageClass")
    delete_count = sum(1 for rule in rules if rule["action_type"] == "Delete")
    parts = [f"{_plural(len(rules), 'lifecycle rule')} configured"]
    if transition_count:
        parts.append(f"{_plural(transition_count, 'storage-class transition')}")
    if delete_count:
        parts.append(f"{_plural(delete_count, 'delete rule')}")
    return ". ".join(parts) + "."


def gcs_bucket_lifecycle_status(db: Session) -> dict[str, Any]:
    bucket_name = get_gcs_bucket(db)
    checked_at = datetime.now(timezone.utc)
    if not bucket_name:
        return {
            "bucket": "",
            "available": False,
            "status": "not_configured",
            "summary": "No GCS bucket is configured. Medusa is using local storage fallback.",
            "rules": [],
            "checked_at": checked_at,
            "error": None,
        }
    credentials_path = get_google_service_account_path(db)
    if not credentials_path:
        return {
            "bucket": bucket_name,
            "available": False,
            "status": "credentials_missing",
            "summary": "A bucket is configured, but no Google service-account JSON is available for bucket metadata.",
            "rules": [],
            "checked_at": checked_at,
            "error": "Configure a Google service-account JSON to read the bucket lifecycle policy.",
        }
    try:
        from google.cloud import storage

        credentials = load_service_account_credentials(credentials_path)
        project = getattr(credentials, "project_id", None) or get_google_project_id(db)
        client = storage.Client(project=project, credentials=credentials)
        bucket = client.bucket(bucket_name)
        bucket.reload()
        rules = [_rule_out(dict(rule), index + 1) for index, rule in enumerate(bucket.lifecycle_rules)]
        return {
            "bucket": bucket_name,
            "available": True,
            "status": "available",
            "summary": _summary_for_rules(rules),
            "rules": rules,
            "checked_at": checked_at,
            "error": None,
            "storage_class": _storage_class_label(getattr(bucket, "storage_class", None)),
            "location": getattr(bucket, "location", None),
        }
    except Exception as exc:
        return {
            "bucket": bucket_name,
            "available": False,
            "status": "unavailable",
            "summary": "The bucket lifecycle policy could not be read.",
            "rules": [],
            "checked_at": checked_at,
            "error": str(exc),
        }
