"""User-adjustable defaults stored in the database (Settings page)."""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.misc import AppSetting

DEFAULTS: Dict[str, Any] = {
    "default_max_pages": 10,
    "default_max_depth": 2,
    "default_delay_seconds": 1.0,
    "default_concurrency": 3,
    "default_validate_mx": True,
    "default_tags": "",
    "category_keywords": {},  # {"Category name": ["extra keyword", ...]}
}


def get_all(db: Session) -> Dict[str, Any]:
    values = dict(DEFAULTS)
    for row in db.query(AppSetting).all():
        if row.key in DEFAULTS:
            values[row.key] = row.value
    return values


def update(db: Session, changes: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in changes.items():
        if key not in DEFAULTS:
            continue
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
    db.commit()
    return get_all(db)


def custom_keywords(db: Session) -> Dict[str, List[str]]:
    value = get_all(db).get("category_keywords") or {}
    return value if isinstance(value, dict) else {}
