from __future__ import annotations

from datetime import date, datetime, timedelta
from ..time_utils import clock

MONTHS_UA = ["січень","лютий","березень","квітень","травень","червень","липень","серпень","вересень","жовтень","листопад","грудень"]

def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)

def resolve_report_period(period_type: str, *, year: int, month: int | None = None, start_month: int | None = None, end_month: int | None = None, quarter: int | None = None) -> tuple[datetime, datetime, str]:
    year = int(year)
    if not 2020 <= year <= 2100:
        raise ValueError("Некоректний рік")
    if period_type == "week":
        week = int(month or 1)
        if not 1 <= week <= 53: raise ValueError("Некоректний номер тижня")
        try:
            start_day = date.fromisocalendar(year, week, 1)
        except ValueError as exc:
            raise ValueError("Некоректний календарний тиждень (понеділок–неділя)") from exc
        start_dt = datetime.combine(start_day, datetime.min.time())
        return start_dt, start_dt + timedelta(days=7), f"{week}-й тиждень {year} ({start_day.strftime('%d.%m')}–{(start_day + timedelta(days=6)).strftime('%d.%m')})"
    if period_type == "month":
        m = int(month or 1)
        if not 1 <= m <= 12: raise ValueError("Некоректний місяць")
        ny, nm = _next_month(year, m)
        return datetime(year,m,1), datetime(ny,nm,1), f"{MONTHS_UA[m-1]} {year}"
    if period_type == "months":
        sm, em = int(start_month or 1), int(end_month or 12)
        if not (1 <= sm <= 12 and 1 <= em <= 12 and sm <= em): raise ValueError("Некоректний діапазон місяців")
        ny, nm = _next_month(year, em)
        label = f"{MONTHS_UA[sm-1]}–{MONTHS_UA[em-1]} {year}" if sm != em else f"{MONTHS_UA[sm-1]} {year}"
        return datetime(year,sm,1), datetime(ny,nm,1), label
    if period_type == "quarter":
        q = int(quarter or 1)
        if q not in {1,2,3,4}: raise ValueError("Некоректний квартал")
        sm = (q-1)*3+1; em=sm+2; ny,nm=_next_month(year,em)
        return datetime(year,sm,1), datetime(ny,nm,1), f"{q} квартал {year}"
    if period_type == "year":
        return datetime(year,1,1), datetime(year+1,1,1), f"{year} рік"
    raise ValueError("Невідомий тип періоду")

def resolve_report_storage_bounds(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """Map local-calendar report boundaries to legacy naive-UTC DB bounds."""
    return clock.local_period_to_storage_utc(start, end)

def _age(birth: date | None, on: date) -> int | None:
    if not birth: return None
    return on.year-birth.year-((on.month,on.day)<(birth.month,birth.day))

def _age_group(age: int | None) -> str:
    if age is None: return "Не зазначено"
    if age < 14: return "До 14"
    if age <=17: return "14–17"
    if age <=21: return "18–21"
    if age <=25: return "22–25"
    if age <=30: return "26–30"
    if age <=35: return "31–35"
    return "36+"
