"""Explicit, inclusive KST date windows; no network or SDK dependency."""
from __future__ import annotations
import datetime as dt
import re
from typing import Any

KST = dt.timezone(dt.timedelta(hours=9))


def today_kst() -> dt.date:
    return dt.datetime.now(KST).date()


def parse_date(value: Any, field: str = "date") -> dt.date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{field}는 YYYY-MM-DD 형식입니다.")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field}에 존재하는 날짜를 입력하세요.") from None


def resolve_period(*, years: int = 3, include_current_year: bool = False,
                   as_of: str | None = None, period_mode: str = "calendar_years",
                   date_from: str | None = None, date_to: str | None = None,
                   today: dt.date | None = None) -> dict:
    """Split a rolling/calendar/explicit range into bounded calendar-year windows.

    Explicit dates take precedence and both are required. For rolling periods,
    a leap-day anchor clamps to Feb 28 in a non-leap start year. Both endpoints
    are inclusive; a rolling 2-year window usually touches 3 calendar years.
    """
    if type(years) is not int or not 1 <= years <= 5:
        raise ValueError("years는 1~5의 정수입니다.")
    if type(include_current_year) is not bool:
        raise ValueError("include_current_year는 true 또는 false입니다.")
    if period_mode not in ("calendar_years", "rolling_years"):
        raise ValueError("period_mode는 calendar_years 또는 rolling_years입니다.")
    now = today or today_kst()
    anchor = parse_date(as_of, "as_of") if as_of is not None else now
    if anchor > now:
        raise ValueError("as_of는 미래 날짜일 수 없습니다.")
    if date_from is not None or date_to is not None:
        if date_from is None or date_to is None:
            raise ValueError("명시 기간은 date_from과 date_to를 함께 지정하세요.")
        begin, end = parse_date(date_from, "date_from"), parse_date(date_to, "date_to")
        mode, applied_years = "explicit_dates", None
        if end > anchor:
            raise ValueError("date_to는 기준일(as_of 또는 한국시간 오늘)을 넘을 수 없습니다.")
    elif period_mode == "rolling_years":
        end = anchor
        try:
            begin = anchor.replace(year=anchor.year-years)
        except ValueError:
            if anchor.year-years < 1:
                raise ValueError("조회 시작연도는 1 이상이어야 합니다.") from None
            begin = anchor.replace(year=anchor.year-years, day=28)
        mode, applied_years = period_mode, years
    else:
        end_year = anchor.year if include_current_year else anchor.year-1
        start_year = end_year-years+1
        if start_year < 1:
            raise ValueError("조회 시작연도는 1 이상이어야 합니다.")
        begin = dt.date(start_year, 1, 1)
        end = anchor if include_current_year else dt.date(end_year, 12, 31)
        mode, applied_years = period_mode, years
    if begin > end:
        raise ValueError("date_from은 date_to보다 늦을 수 없습니다.")
    if end.year-begin.year > 5:
        raise ValueError("한 번에 최대 6개 달력연도에 걸친 기간만 확인합니다. 기간을 나눠 주세요.")
    windows = [{"meeting_year": year,
                "date_from": max(begin, dt.date(year, 1, 1)).isoformat(),
                "date_to": min(end, dt.date(year, 12, 31)).isoformat()}
               for year in range(begin.year, end.year+1)]
    return {"mode": mode, "as_of": anchor.isoformat(), "date_from": begin.isoformat(),
            "date_to": end.isoformat(), "timezone": "Asia/Seoul", "endpoints": "inclusive",
            "years_applied": applied_years, "windows": windows,
            "basis": "회의일 기준이며 회계연도·원문 게시일과 다릅니다.",
            "include_current_year_applies": mode == "calendar_years"}
