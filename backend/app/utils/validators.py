"""Input validation. Ids end up inside Gaana URLs, so they are strictly whitelisted."""

from __future__ import annotations

import re

from app.utils.errors import InvalidInput

_SEOKEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,199}$")
_NUMERIC = re.compile(r"^[0-9]{1,20}$")
_LANGUAGE = re.compile(r"^[A-Za-z]+(?: [A-Za-z]+)*$")

QUALITIES = ("very_high", "high", "medium", "low")


def seokey(value: str, what: str = "id") -> str:
    value = (value or "").strip().lower()
    # Gaana seokeys always contain a letter; purely numeric values are ids, not seokeys.
    if not _SEOKEY.match(value) or not re.search(r"[a-z]", value):
        raise InvalidInput(f"Invalid {what}: expected a Gaana seokey like 'believer-224'")
    return value


def numeric_id(value: str, what: str = "id") -> str:
    value = (value or "").strip()
    if not _NUMERIC.match(value):
        raise InvalidInput(f"Invalid {what}: expected a numeric id")
    return value


def is_numeric(value: str) -> bool:
    return bool(_NUMERIC.match((value or "").strip()))


def language(value: str | None, default: str) -> str:
    value = (value or default).strip()
    if len(value) > 30 or not _LANGUAGE.match(value):
        raise InvalidInput("Invalid language: use a name like 'English' or 'Hindi'")
    return value[:1].upper() + value[1:].lower()


def query(value: str) -> str:
    value = " ".join((value or "").split())
    if not value:
        raise InvalidInput("Search query must not be empty")
    if len(value) > 100:
        raise InvalidInput("Search query is too long (max 100 characters)")
    return value


def quality(value: str | None) -> str:
    value = (value or "high").strip().lower()
    if value not in QUALITIES:
        raise InvalidInput(f"Invalid quality: choose one of {', '.join(QUALITIES)}")
    return value
