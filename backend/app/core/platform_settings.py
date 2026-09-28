"""V25.2 — typed, validated platform settings.

Spec section 19 is explicit: do not store arbitrary settings as an
untyped JSON blob. So the authoritative catalog lives here, in code,
as ``SETTING_DEFINITIONS`` — what exists, what type it is, its
default, its bounds, whether changing it is a sensitive action, and
one line of human-readable help. The ``platform_settings`` table
stores only the *overrides* an administrator has actually made.

Consequences of that split, all of them deliberate:

- A key that is not in this catalog cannot be written (400) and is
  ignored on read. A stray or injected row cannot introduce a setting
  the application doesn't know about.
- Types are enforced on write *and* re-validated on read, so a row
  hand-edited in the database to a nonsense value degrades to the
  declared default rather than propagating a bad type into a code
  path that expected a bool.
- Adding a setting is one entry here. No migration; the table is
  already key/value-with-declared-type.

Reads are cached in-process for a few seconds. ``maintenance_mode``
and ``registration_enabled`` are consulted on effectively every
request, and a DB round-trip per request for a value that changes a
handful of times a year would be a self-inflicted performance problem.
The cache is invalidated immediately on write within the process that
made the change; other replicas pick it up within the TTL, which is
the correct tradeoff for settings whose effects are advisory-fast
rather than security-critical (nothing here is an authorization
decision — those are never cached).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import PlatformSetting

log = logging.getLogger("careeros.platform_settings")

CACHE_TTL_SECONDS = 5.0


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    value_type: str  # "bool" | "int" | "str"
    default: Any
    description: str
    # Sensitive settings require a full platform-admin role, not just
    # the SYSTEM_CONFIGURATION permission (spec section 26).
    sensitive: bool = False
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] | None = None


SETTING_DEFINITIONS: dict[str, SettingDefinition] = {
    d.key: d
    for d in (
        SettingDefinition(
            key="registration_enabled",
            value_type="bool",
            default=True,
            description="Allow new candidate accounts to be registered.",
            sensitive=True,
        ),
        SettingDefinition(
            key="recruiter_registration_enabled",
            value_type="bool",
            default=True,
            description="Allow new recruiter accounts to be registered.",
            sensitive=True,
        ),
        SettingDefinition(
            key="maintenance_mode",
            value_type="bool",
            default=False,
            description=(
                "Serve a maintenance response to non-administrator API traffic. "
                "Platform administrators and health endpoints are never blocked."
            ),
            sensitive=True,
        ),
        SettingDefinition(
            key="maintenance_message",
            value_type="str",
            default="CareerOS is temporarily unavailable for scheduled maintenance. Please try again shortly.",
            description="Message shown to users while maintenance mode is enabled.",
        ),
        SettingDefinition(
            key="job_moderation_required",
            value_type="bool",
            default=True,
            description=(
                "Require platform review before a recruiter-submitted job is published. "
                "Reflects the existing review-queue workflow; turning this off is not "
                "retroactive and never auto-publishes jobs already in review."
            ),
            sensitive=True,
        ),
        SettingDefinition(
            key="announcement_email_enabled",
            value_type="bool",
            default=False,
            description=(
                "Permit platform announcements to be delivered by email as well as in-app. "
                "Off by default so an accidental mass email is impossible without an "
                "explicit, audited opt-in."
            ),
            sensitive=True,
        ),
        SettingDefinition(
            key="announcement_max_recipients",
            value_type="int",
            default=5000,
            minimum=1,
            maximum=1000000,
            description="Hard ceiling on how many recipients one announcement may target.",
        ),
        SettingDefinition(
            key="resume_max_upload_mb",
            value_type="int",
            default=0,
            minimum=0,
            maximum=100,
            description=(
                "Override the configured resume upload limit in megabytes. "
                "0 means 'use the deployment's RESUME_MAX_UPLOAD_MB environment value'."
            ),
        ),
        SettingDefinition(
            key="ai_features_enabled",
            value_type="bool",
            default=True,
            description=(
                "Master switch for AI-backed features. Turning this off does not "
                "delete anything; AI endpoints report the feature as unavailable."
            ),
        ),
        SettingDefinition(
            key="notifications_enabled",
            value_type="bool",
            default=True,
            description="Master switch for outbound platform notification processing.",
        ),
        # --- V25.3 Data Intelligence sample-size thresholds -------------
        # Spec section 21 requires configurable thresholds that are not
        # hardcoded throughout the codebase. They live here, in the
        # existing typed catalog, so they are validated, bounded,
        # audited on change, and read from exactly one place
        # (app.intelligence.thresholds).
        SettingDefinition(
            key="intelligence_min_corpus_jobs",
            value_type="int",
            default=5,
            minimum=1,
            maximum=10000,
            description=(
                "Minimum number of matching jobs before any skill/role/location breakdown "
                "of that job set is reported. Below this, analytics report "
                "'insufficient CareerOS data' rather than a misleading figure."
            ),
        ),
        SettingDefinition(
            key="intelligence_min_trend_observations",
            value_type="int",
            default=10,
            minimum=2,
            maximum=100000,
            description=(
                "Minimum observations required in EACH compared period before a trend "
                "direction (rising/falling) is reported. Prevents trends being claimed "
                "from tiny samples."
            ),
        ),
        SettingDefinition(
            key="intelligence_min_group_size",
            value_type="int",
            default=5,
            minimum=1,
            maximum=1000,
            description=(
                "Privacy floor: a breakdown row backed by fewer than this many distinct "
                "entities is suppressed, so an 'aggregate' can never identify an "
                "individual candidate or a single organization's private activity."
            ),
        ),
    )
}

# --- in-process read cache -------------------------------------------------

_cache: dict[str, Any] = {}
_cache_loaded_at: float = 0.0


def invalidate_cache() -> None:
    global _cache_loaded_at
    _cache_loaded_at = 0.0
    _cache.clear()


def _coerce(definition: SettingDefinition, raw: Any) -> Any:
    """Validate/convert `raw` against the definition, raising
    ValueError with a user-safe message when it doesn't fit."""
    if definition.value_type == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.lower() in {"true", "false"}:
            return raw.lower() == "true"
        raise ValueError(f"{definition.key} must be a boolean")
    if definition.value_type == "int":
        if isinstance(raw, bool) or not isinstance(raw, int):
            try:
                raw = int(str(raw))
            except (TypeError, ValueError):
                raise ValueError(f"{definition.key} must be an integer") from None
        if definition.minimum is not None and raw < definition.minimum:
            raise ValueError(f"{definition.key} must be at least {definition.minimum}")
        if definition.maximum is not None and raw > definition.maximum:
            raise ValueError(f"{definition.key} must be at most {definition.maximum}")
        return raw
    # str
    if not isinstance(raw, str):
        raise ValueError(f"{definition.key} must be a string")
    value = raw.strip()
    if len(value) > 2000:
        raise ValueError(f"{definition.key} must be at most 2000 characters")
    if definition.choices is not None and value not in definition.choices:
        raise ValueError(f"{definition.key} must be one of: {', '.join(definition.choices)}")
    return value


def _load(db: Session) -> dict[str, Any]:
    """Every setting's effective value: catalog defaults overlaid with
    valid stored overrides. A stored row whose key is unknown, or
    whose value no longer validates, is skipped with a warning — the
    default wins rather than a bad value reaching a caller."""
    values = {key: definition.default for key, definition in SETTING_DEFINITIONS.items()}
    for row in db.scalars(select(PlatformSetting)).all():
        definition = SETTING_DEFINITIONS.get(row.key)
        if definition is None:
            log.warning("Ignoring unknown platform setting row: %s", row.key)
            continue
        try:
            values[row.key] = _coerce(definition, json.loads(row.value_json))
        except (ValueError, json.JSONDecodeError):
            log.warning("Ignoring invalid stored value for platform setting %s; using default", row.key)
    return values


def all_settings(db: Session, *, use_cache: bool = True) -> dict[str, Any]:
    global _cache_loaded_at
    now = time.monotonic()
    if use_cache and _cache and (now - _cache_loaded_at) < CACHE_TTL_SECONDS:
        return dict(_cache)
    values = _load(db)
    _cache.clear()
    _cache.update(values)
    _cache_loaded_at = now
    return dict(values)


def peek_cached(key: str) -> tuple[bool, Any]:
    """Read a setting from the in-process cache without a database
    session. Returns (hit, value).

    Exists for the maintenance-mode middleware, which runs on every
    request: opening and closing a database session per request purely
    to re-read a flag that changes a few times a year would be a
    self-inflicted performance problem. On a cache miss the caller
    falls back to the normal, session-backed read.
    """
    if _cache and (time.monotonic() - _cache_loaded_at) < CACHE_TTL_SECONDS and key in _cache:
        return True, _cache[key]
    return False, None


def get_setting(db: Session, key: str, *, use_cache: bool = True) -> Any:
    if key not in SETTING_DEFINITIONS:
        raise KeyError(f"Unknown platform setting: {key}")
    return all_settings(db, use_cache=use_cache)[key]


def get_setting_safe(db: Session, key: str, fallback: Any = None) -> Any:
    """``get_setting`` that can never raise.

    Used from middleware and request-path code where a transient
    database problem must degrade to the default rather than turn
    every request into a 500. The failure is logged, not swallowed
    silently.
    """
    try:
        return get_setting(db, key)
    except Exception:
        log.warning("Falling back to default for platform setting %s", key, exc_info=True)
        definition = SETTING_DEFINITIONS.get(key)
        return definition.default if definition is not None else fallback


def set_setting(db: Session, key: str, raw_value: Any, *, actor_user_id: int | None) -> Any:
    """Write one override. Validates against the catalog first, so an
    invalid value never reaches the table.

    Does not commit — the caller commits together with the audit row
    that records the change, so a setting can never be changed without
    a corresponding audit entry.
    """
    definition = SETTING_DEFINITIONS.get(key)
    if definition is None:
        raise KeyError(f"Unknown platform setting: {key}")
    value = _coerce(definition, raw_value)

    row = db.scalar(select(PlatformSetting).where(PlatformSetting.key == key))
    if row is None:
        row = PlatformSetting(key=key, value_json=json.dumps(value), value_type=definition.value_type)
        db.add(row)
    else:
        row.value_json = json.dumps(value)
        row.value_type = definition.value_type
    row.updated_by_user_id = actor_user_id
    invalidate_cache()
    return value


def describe_settings(db: Session) -> list[dict]:
    """The catalog plus current values, for the admin settings UI."""
    values = all_settings(db, use_cache=False)
    stored = {row.key: row for row in db.scalars(select(PlatformSetting)).all()}
    out = []
    for key, definition in SETTING_DEFINITIONS.items():
        row = stored.get(key)
        out.append(
            {
                "key": key,
                "value": values[key],
                "value_type": definition.value_type,
                "default": definition.default,
                "description": definition.description,
                "sensitive": definition.sensitive,
                "minimum": definition.minimum,
                "maximum": definition.maximum,
                "is_overridden": row is not None,
                "updated_at": row.updated_at if row is not None else None,
                "updated_by_user_id": row.updated_by_user_id if row is not None else None,
            }
        )
    return out
