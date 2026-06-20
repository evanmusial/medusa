from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import Tag, TagAlias


TAG_MANIFEST_LIMIT = 500


def normalize_tag_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _ensure_flat_tag(tag: Tag) -> Tag:
    if tag.kind != "tag":
        tag.kind = "tag"
    return tag


def resolve_tag_alias(db: Session, name: str) -> Tag | None:
    normalized = normalize_tag_name(name)
    if not normalized:
        return None
    alias = db.get(TagAlias, normalized)
    if alias and alias.target_tag:
        return _ensure_flat_tag(alias.target_tag)
    return None


def get_or_create_tag(db: Session, name: str) -> Tag | None:
    normalized = normalize_tag_name(name)
    if not normalized:
        return None

    alias_target = resolve_tag_alias(db, normalized)
    if alias_target:
        return alias_target

    tag = db.query(Tag).filter(Tag.name == normalized).one_or_none()
    if tag:
        return _ensure_flat_tag(tag)

    tag = Tag(name=normalized, kind="tag")
    db.add(tag)
    db.flush()
    return tag


def existing_tag_manifest(db: Session, *, limit: int = TAG_MANIFEST_LIMIT) -> list[str]:
    rows = db.query(Tag.name).order_by(Tag.name).limit(limit).all()
    return [name for (name,) in rows if normalize_tag_name(name)]


def remember_tag_merge_aliases(
    db: Session,
    *,
    source_tag_ids: list[str],
    source_tag_names: dict[str, str],
    target_tag: Tag,
    metadata: dict[str, Any],
) -> list[str]:
    target_name = normalize_tag_name(target_tag.name)
    remembered: set[str] = set()

    existing_aliases = db.query(TagAlias).filter(TagAlias.target_tag_id.in_(source_tag_ids)).all()
    for alias in existing_aliases:
        if alias.alias_name == target_name:
            db.delete(alias)
            continue
        alias.target_tag = target_tag
        alias.source = "merge"
        alias.alias_metadata = {**(alias.alias_metadata or {}), **metadata}
        remembered.add(alias.alias_name)

    for source_id, source_name in source_tag_names.items():
        alias_name = normalize_tag_name(source_name)
        if not alias_name or alias_name == target_name:
            continue
        alias = db.get(TagAlias, alias_name)
        if alias is None:
            alias = TagAlias(alias_name=alias_name, target_tag=target_tag, source="merge", alias_metadata={})
            db.add(alias)
        else:
            alias.target_tag = target_tag
            alias.source = "merge"
        alias.alias_metadata = {
            **(alias.alias_metadata or {}),
            **metadata,
            "source_tag_id": source_id,
            "source_tag_name": source_name,
        }
        remembered.add(alias_name)

    return sorted(remembered)
