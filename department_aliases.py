"""User-declared department aliases, date bounds and explicit provenance.

No organizational-history facts are bundled or inferred. Legacy extra_terms
keeps its old documented alias meaning, but is marked as an unverified input.
"""
from __future__ import annotations
import datetime as dt
import re
import unicodedata
from period_core import parse_date


def normalize_aliases(department: str, aliases: list[dict] | None = None,
                      legacy_terms: list[str] | None = None) -> list[dict]:
    if aliases is not None and not isinstance(aliases, list):
        raise ValueError("department_aliases는 목록입니다.")
    if legacy_terms is not None and not isinstance(legacy_terms, list):
        raise ValueError("extra_terms는 부서명 문자열 목록입니다.")
    if len(aliases or []) > 2 or len(legacy_terms or []) > 2:
        raise ValueError("과거 부서명은 최대 2개입니다.")
    rows = []
    for item in aliases or []:
        if not isinstance(item, dict) or set(item)-{"name", "valid_from", "valid_to", "basis"}:
            raise ValueError("부서 별칭 필드: name, valid_from, valid_to, basis")
        name, basis = item.get("name"), item.get("basis")
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 100:
            raise ValueError("별칭 name은 2~100자 부서명입니다.")
        if not isinstance(basis, str) or not 1 <= len(basis.strip()) <= 300:
            raise ValueError("basis에 부서 이력의 확인 근거를 1~300자로 입력하세요. 자동 검증하지는 않습니다.")
        lo, hi = item.get("valid_from"), item.get("valid_to")
        start = parse_date(lo, "valid_from") if lo is not None else None
        end = parse_date(hi, "valid_to") if hi is not None else None
        if start and end and start > end:
            raise ValueError("별칭 valid_from은 valid_to보다 늦을 수 없습니다.")
        rows.append({"name": name.strip(), "valid_from": lo, "valid_to": hi,
                     "basis": basis.strip(), "source_kind": "USER_PROVIDED", "verified_by_server": False})
    for value in legacy_terms or []:
        if not isinstance(value, str) or not 2 <= len(value.strip()) <= 100:
            raise ValueError("extra_terms에는 2~100자 과거 부서명만 지정하세요.")
        rows.append({"name": value.strip(), "valid_from": None, "valid_to": None,
                     "basis": "기존 extra_terms 인자에 담당자가 지정한 명칭(적용기간 미지정)",
                     "source_kind": "USER_PROVIDED", "verified_by_server": False})
    out, seen = [], set()
    canon = lambda s: re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))
    for row in rows:
        if canon(row["name"]) == canon(department):
            continue
        key = canon(row["name"])
        if key in seen:
            # Conflicting validity intervals must not be silently merged.
            previous = next(r for r in out if canon(r["name"]) == key)
            if (previous["valid_from"], previous["valid_to"]) != (row["valid_from"], row["valid_to"]):
                raise ValueError("같은 별칭의 적용기간이 충돌합니다.")
            continue
        seen.add(key)
        out.append(row)
    if len(out) > 2:
        raise ValueError("department_aliases와 extra_terms를 합쳐 최대 2개 부서 별칭만 지정하세요.")
    return out


def event_date(event: dict) -> dt.date | None:
    raw = str((event.get("metadata") or {}).get("meeting_date") or "")
    digits = re.sub(r"\D", "", raw)
    if len(digits) != 8:
        return None
    try:
        return dt.date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None


def applicable_names(event: dict, department: str, aliases: list[dict]) -> tuple[list[str], list[str]]:
    names, date_pending = [department], []
    day = event_date(event)
    for alias in aliases:
        lo, hi = alias.get("valid_from"), alias.get("valid_to")
        if (lo or hi) and day is None:
            date_pending.append(alias["name"])
            continue
        if day and ((lo and day < parse_date(lo)) or (hi and day > parse_date(hi))):
            continue
        names.append(alias["name"])
    return names, date_pending
