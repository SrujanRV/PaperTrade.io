"""
services/trading_calendar.py — Market holiday schedules and trading-day calculation.

Handles:
- Trading day detection for IN (NSE/BSE) and US (NYSE/NASDAQ)
- Market holiday calendar for Indian and US markets
- Counting strictly in market trading days (skipping weekends & holidays)
- Shift-earlier resolution: if a calculated date falls on a closed day/holiday,
  resolve to the previous trading day (never hold longer than intended)
- Market close detection: checking if current time is in final 15 minutes of session
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pandas.tseries.holiday import USFederalHolidayCalendar

from config import MARKET_SESSIONS

logger = logging.getLogger(__name__)

# ── Market Holidays ───────────────────────────────────────────────────────────

# Known official NSE/BSE holidays (2024–2027)
# Standard Indian national & exchange holidays
_NSE_HOLIDAYS: set[date] = {
    # 2024
    date(2024, 1, 22), date(2024, 1, 26), date(2024, 3, 8), date(2024, 3, 25),
    date(2024, 3, 29), date(2024, 4, 11), date(2024, 4, 17), date(2024, 5, 1),
    date(2024, 5, 20), date(2024, 6, 17), date(2024, 7, 17), date(2024, 8, 15),
    date(2024, 10, 2), date(2024, 11, 1), date(2024, 11, 15), date(2024, 12, 25),
    # 2025
    date(2025, 1, 26), date(2025, 2, 26), date(2025, 3, 14), date(2025, 3, 31),
    date(2025, 4, 10), date(2025, 4, 14), date(2025, 4, 18), date(2025, 5, 1),
    date(2025, 6, 7), date(2025, 8, 15), date(2025, 8, 27), date(2025, 10, 2),
    date(2025, 10, 21), date(2025, 10, 22), date(2025, 11, 5), date(2025, 12, 25),
    # 2026
    date(2026, 1, 26),  # Republic Day
    date(2026, 2, 16),  # Mahashivratri
    date(2026, 3, 3),   # Holi
    date(2026, 3, 20),  # Id-Ul-Fitr
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 14),  # Dr. Ambedkar Jayanti
    date(2026, 5, 1),   # Maharashtra Day
    date(2026, 5, 27),  # Bakri Id
    date(2026, 8, 15),  # Independence Day
    date(2026, 10, 2),  # Mahatma Gandhi Jayanti
    date(2026, 10, 20), # Dussehra
    date(2026, 11, 8),  # Diwali Laxmi Pujan
    date(2026, 11, 10), # Diwali Balipratipada
    date(2026, 11, 24), # Gurunanak Jayanti
    date(2026, 12, 25), # Christmas
    # 2027
    date(2027, 1, 26), date(2027, 3, 22), date(2027, 3, 26), date(2027, 4, 14),
    date(2027, 5, 1), date(2027, 8, 15), date(2027, 10, 2), date(2027, 12, 25),
}

# US Federal Holidays from pandas (cached 2024–2027) + Good Friday (NYSE holiday)
_US_CALENDAR = USFederalHolidayCalendar()
_US_HOLIDAYS_PANDAS = set(
    d.date() for d in _US_CALENDAR.holidays("2024-01-01", "2027-12-31")
)
# Additional NYSE specific holiday: Good Friday
_NYSE_GOOD_FRIDAYS = {
    date(2024, 3, 29),
    date(2025, 4, 18),
    date(2026, 4, 3),
    date(2027, 3, 26),
}
_US_HOLIDAYS = _US_HOLIDAYS_PANDAS.union(_NYSE_GOOD_FRIDAYS)


def get_market_holidays(market: str) -> set[date]:
    m = market.upper()
    if m == "IN":
        return _NSE_HOLIDAYS
    return _US_HOLIDAYS


def is_trading_day(market: str, dt: date) -> bool:
    """Return True if dt is a normal trading day (not a weekend and not a holiday)."""
    # 5 = Saturday, 6 = Sunday
    if dt.weekday() in (5, 6):
        return False
    holidays = get_market_holidays(market)
    return dt not in holidays


def get_next_trading_day(market: str, dt: date) -> date:
    """Returns the next trading day strictly after dt."""
    curr = dt + timedelta(days=1)
    while not is_trading_day(market, curr):
        curr += timedelta(days=1)
    return curr


def get_previous_trading_day(market: str, dt: date) -> date:
    """Returns the previous trading day strictly before dt."""
    curr = dt - timedelta(days=1)
    while not is_trading_day(market, curr):
        curr -= timedelta(days=1)
    return curr


def resolve_to_valid_trading_day(market: str, dt: date) -> tuple[date, bool, str | None]:
    """
    If dt is a trading day, return it unchanged.
    If dt falls on a non-trading day (weekend/holiday), resolve to the PREVIOUS
    trading day (so holding duration is never exceeded).
    Returns (resolved_date, was_shifted, reason).
    """
    if is_trading_day(market, dt):
        return dt, False, None

    # Step backwards until we hit a trading day
    orig = dt
    curr = dt
    reason = "weekend" if orig.weekday() in (5, 6) else "market holiday"
    while not is_trading_day(market, curr):
        curr -= timedelta(days=1)

    return curr, True, f"Target date ({orig.strftime('%d %b')}) falls on a {reason} — squared off earlier on {curr.strftime('%a, %d %b')} instead."


def calculate_square_off_date(
    market: str,
    start_date: date | None = None,
    holding_days: int = 0,
) -> dict:
    """
    Calculates the square-off date based on market trading days.

    holding_days = 0: Intraday (same day, or shifted to prior trading day if closed)
    holding_days > 0: N market trading days from start_date

    Returns a dict with:
      - square_off_date: ISO date string 'YYYY-MM-DD'
      - is_intraday: bool
      - holding_days: int
      - is_shifted: bool
      - shift_reason: str | None
      - formatted_date: e.g. "Mon, 28 Sep"
    """
    m = market.upper()
    if start_date is None:
        # Local market current date
        tz = MARKET_SESSIONS.get("NSE" if m == "IN" else "NASDAQ", {}).get("tz")
        now_local = datetime.now(tz=tz) if tz else datetime.now()
        start_date = now_local.date()

    if holding_days <= 0:
        # Intraday: must square off on start_date
        resolved_date, shifted, shift_reason = resolve_to_valid_trading_day(m, start_date)
        return {
            "square_off_date": str(resolved_date),
            "is_intraday": True,
            "holding_days": 0,
            "is_shifted": shifted,
            "shift_reason": shift_reason,
            "formatted_date": resolved_date.strftime("%a, %d %b"),
        }

    # For N days: advance strictly in MARKET TRADING DAYS
    curr = start_date
    days_counted = 0
    while days_counted < holding_days:
        curr = get_next_trading_day(m, curr)
        days_counted += 1

    # Safety check: ensure curr is a valid trading day
    final_date, shifted, shift_reason = resolve_to_valid_trading_day(m, curr)

    # Also detect if naive calendar addition (start_date + timedelta(days=holding_days)) differed
    naive_date = start_date + timedelta(days=holding_days)
    if not shifted and naive_date != final_date:
        # Naive calendar day was skipped because of weekends/holidays
        shift_reason = f"Calculated over {holding_days} market trading day(s) (skipping non-trading sessions)."

    return {
        "square_off_date": str(final_date),
        "is_intraday": False,
        "holding_days": holding_days,
        "is_shifted": shifted,
        "shift_reason": shift_reason,
        "formatted_date": final_date.strftime("%a, %d %b"),
    }


def is_near_market_close(market: str, now: datetime | None = None) -> bool:
    """
    Returns True if current time is within the final 15 minutes of the trading session.
    - NSE/BSE: 15:15 to 15:30 IST
    - NYSE/NASDAQ: 15:45 to 16:00 ET
    """
    m = market.upper()
    exchange = "NSE" if m == "IN" else "NASDAQ"
    session = MARKET_SESSIONS.get(exchange)
    if not session:
        return False

    tz = session["tz"]
    now_local = now.astimezone(tz) if now else datetime.now(tz=tz)

    # Must be an open trading day
    if not is_trading_day(m, now_local.date()):
        return False

    close_h, close_m = session["close"]
    close_dt = now_local.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
    # 15 minutes before close
    window_start = close_dt - timedelta(minutes=15)

    return window_start <= now_local < close_dt
