# -*- coding: utf-8 -*-
"""
Horus Flow API — US equity session context for AI agents.

Answers "can I trade US stocks right now, and what is unusual today?":
NYSE/Nasdaq session phase, holidays and early closes, next open/close,
and the trading halts currently published by Nasdaq Trader (free RSS).
"""
import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import aiohttp

logger = logging.getLogger("API.USMarket")
ET_TZ = ZoneInfo("America/New_York")

# NYSE full-day holidays (verify yearly against nyse.com/markets/hours-calendars)
HOLIDAYS = {
    date(2026, 1, 1): "New Year's Day",
    date(2026, 1, 19): "Martin Luther King Jr. Day",
    date(2026, 2, 16): "Washington's Birthday",
    date(2026, 4, 3): "Good Friday",
    date(2026, 5, 25): "Memorial Day",
    date(2026, 6, 19): "Juneteenth",
    date(2026, 7, 3): "Independence Day (observed)",
    date(2026, 9, 7): "Labor Day",
    date(2026, 11, 26): "Thanksgiving Day",
    date(2026, 12, 25): "Christmas Day",
    date(2027, 1, 1): "New Year's Day",
    date(2027, 1, 18): "Martin Luther King Jr. Day",
    date(2027, 2, 15): "Washington's Birthday",
    date(2027, 3, 26): "Good Friday",
    date(2027, 5, 31): "Memorial Day",
    date(2027, 6, 18): "Juneteenth (observed)",
    date(2027, 7, 5): "Independence Day (observed)",
    date(2027, 9, 6): "Labor Day",
    date(2027, 11, 25): "Thanksgiving Day",
    date(2027, 12, 24): "Christmas Day (observed)",
}
# Early closes at 13:00 ET
EARLY_CLOSES = {
    date(2026, 11, 27): "Day after Thanksgiving",
    date(2026, 12, 24): "Christmas Eve",
    date(2027, 11, 26): "Day after Thanksgiving",
}
CALENDAR_COVERS_UNTIL = date(2027, 12, 31)

PRE_OPEN, REG_OPEN, REG_CLOSE, EARLY_CLOSE, AFTER_CLOSE = dtime(4, 0), dtime(9, 30), dtime(16, 0), dtime(13, 0), dtime(20, 0)

HALTS_URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"
HALT_REASONS = {
    "LUDP": "Volatility pause (LULD)", "LUDS": "Volatility pause, straddle condition", "T1": "News pending",
    "T2": "News released", "T5": "Single stock trading pause", "T6": "Extraordinary market activity",
    "T12": "Additional information requested", "H4": "Non-compliance", "H10": "SEC trading suspension",
    "H11": "Regulatory concern", "M1": "Corporate action", "M2": "Quotation not available",
    "MWC1": "Market-wide circuit breaker level 1", "MWC2": "Market-wide circuit breaker level 2",
    "MWC3": "Market-wide circuit breaker level 3", "IPO1": "IPO not yet trading", "D": "Security deletion",
}
_halts: Dict[str, Any] = {"items": [], "fetched_at": 0.0, "error": None}


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def close_time(d: date) -> dtime:
    return EARLY_CLOSE if d in EARLY_CLOSES else REG_CLOSE


def _at(d: date, t: dtime) -> datetime:
    return datetime.combine(d, t, tzinfo=ET_TZ)


def next_trading_day(d: date) -> date:
    n = d + timedelta(days=1)
    while not is_trading_day(n):
        n += timedelta(days=1)
    return n


def session(now: Optional[datetime] = None) -> Dict[str, Any]:
    now_et = (now or datetime.now(timezone.utc)).astimezone(ET_TZ)
    today = now_et.date()
    t = now_et.time()
    trading = is_trading_day(today)
    close_t = close_time(today)

    if not trading:
        phase = "closed_holiday" if today in HOLIDAYS else "closed_weekend"
    elif t < PRE_OPEN:
        phase = "closed_overnight"
    elif t < REG_OPEN:
        phase = "pre_market"
    elif t < close_t:
        phase = "regular"
    elif t < (dtime(17, 0) if today in EARLY_CLOSES else AFTER_CLOSE):
        phase = "after_hours"
    else:
        phase = "closed_overnight"

    if trading and t < REG_OPEN:
        next_open = _at(today, REG_OPEN)
    else:
        next_open = _at(next_trading_day(today), REG_OPEN)
    if trading and t < close_t:
        next_close = _at(today, close_t)
    else:
        nd = next_trading_day(today)
        next_close = _at(nd, close_time(nd))

    minutes_to_close = int((next_close - now_et).total_seconds() // 60) if phase == "regular" else None
    upcoming = [{"date": d.isoformat(), "name": n} for d, n in sorted(HOLIDAYS.items()) if d >= today][:3]
    upcoming_early = [{"date": d.isoformat(), "name": n, "close_et": "13:00"} for d, n in sorted(EARLY_CLOSES.items()) if d >= today][:2]

    return {
        "now_et": now_et.isoformat(timespec="seconds"),
        "phase": phase,
        "is_regular_session": phase == "regular",
        "is_trading_day": trading,
        "holiday": HOLIDAYS.get(today),
        "early_close_today": EARLY_CLOSES.get(today),
        "regular_hours_et": f"09:30-{close_t.strftime('%H:%M')}" if trading else None,
        "next_open_et": next_open.isoformat(timespec="minutes"),
        "next_close_et": next_close.isoformat(timespec="minutes"),
        "minutes_to_close": minutes_to_close,
        "upcoming_holidays": upcoming,
        "upcoming_early_closes": upcoming_early,
        "calendar_valid_until": CALENDAR_COVERS_UNTIL.isoformat(),
        "agent_hint": {
            "regular": "Regular session: liquidity is normal.",
            "pre_market": "Pre-market: thin liquidity and wide spreads. Many brokers only accept limit orders.",
            "after_hours": "After-hours: thin liquidity and wide spreads. Many brokers only accept limit orders.",
        }.get(phase, "US equity market is closed. Crypto markets keep trading 24/7."),
    }


def parse_halts(xml_text: str) -> List[Dict[str, Any]]:
    ns = {"ndaq": "http://www.nasdaqtrader.com/"}
    root = ET.fromstring(xml_text.lstrip("﻿"))
    out = []
    for item in root.iter("item"):
        g = lambda tag: (item.findtext(f"ndaq:{tag}", default="", namespaces=ns) or "").strip()
        code = g("ReasonCode")
        out.append({
            "symbol": g("IssueSymbol"),
            "name": g("IssueName"),
            "market": g("Market"),
            "reason_code": code,
            "reason": HALT_REASONS.get(code, code),
            "halt_date": g("HaltDate"),
            "halt_time_et": g("HaltTime"),
            "resumption_date": g("ResumptionDate") or None,
            "resumption_trade_time_et": g("ResumptionTradeTime") or None,
        })
    return out


def _resumed(h: Dict[str, Any], now_et: datetime) -> bool:
    if not h["resumption_trade_time_et"] or not h["resumption_date"]:
        return False
    try:
        dt = datetime.strptime(f"{h['resumption_date']} {h['resumption_trade_time_et'][:8]}", "%m/%d/%Y %H:%M:%S")
        return dt.replace(tzinfo=ET_TZ) <= now_et
    except ValueError:
        return False


def halts_view(now: Optional[datetime] = None, limit: int = 25) -> Dict[str, Any]:
    now_et = (now or datetime.now(timezone.utc)).astimezone(ET_TZ)
    items = _halts["items"]
    active = [h for h in items if not _resumed(h, now_et)]
    return {
        "source": "Nasdaq Trader trade halts RSS (all US listings)",
        "fetched_at_utc": datetime.fromtimestamp(_halts["fetched_at"], timezone.utc).isoformat() if _halts["fetched_at"] else None,
        "active_count": len(active),
        "today_count": len(items),
        "active": active[:limit],
        "error": _halts["error"],
    }


async def halts_loop():
    async with aiohttp.ClientSession(headers={"User-Agent": "HorusFlow/1.0 (+https://flow.horustek.pro)"}) as s:
        while True:
            phase = session()["phase"]
            try:
                async with s.get(HALTS_URL, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        _halts.update(items=parse_halts(await r.text()), fetched_at=time.time(), error=None)
                    else:
                        _halts["error"] = f"HTTP {r.status}"
            except Exception as e:
                _halts["error"] = repr(e)[:200]
                logger.error(f"halts fetch failed: {e!r}")
            ok = _halts["error"] is None
            await asyncio.sleep(60 if phase in ("pre_market", "regular", "after_hours") or not ok else 900)
