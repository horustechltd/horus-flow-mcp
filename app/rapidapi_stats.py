# -*- coding: utf-8 -*-
"""
Horus Flow API — RapidAPI usage counters.

RapidAPI is the main sales channel, but its dashboard is the only place that shows
who uses what. These counters give the same picture from our side, per UTC day:

  plans    requests per RapidAPI plan (BASIC / PRO / ULTRA / MEGA)
  users    unique subscribers per plan (HyperLogLog: counts only, names are not stored)
  routes   requests per endpoint template, e.g. /v1/flow/crypto/{symbol}
  status   responses per HTTP status
  denied   plan + endpoint + status for 401/403/429, i.e. what subscribers tried but could not get
  previews plan + endpoint served as a reduced preview, i.e. paid features a lower plan is trying
  hosts    Host header seen (tells which base URL RapidAPI is configured with)

Kept 100 days. Read with GET /v1/admin/rapidapi-usage (admin key) or the daily Telegram summary.
"""
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

PREFIX = "horus:api:rapidapi"
KEEP_SECONDS = 100 * 86400
DENIED_STATUSES = (401, 403, 429)


def _day(ts: float = None) -> str:
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).strftime("%Y-%m-%d")


def _k(day: str, kind: str) -> str:
    return f"{PREFIX}:{day}:{kind}"


async def record(redis, plan: str, user: str, route: str, status: int, host: str, preview: bool = False) -> None:
    if not redis:
        return
    day = _day()
    plan = (plan or "UNKNOWN").replace("RAPIDAPI_", "")
    pipe = redis.pipeline()
    pipe.hincrby(_k(day, "plans"), plan, 1)
    pipe.hincrby(_k(day, "routes"), route or "unknown", 1)
    pipe.hincrby(_k(day, "status"), str(status), 1)
    pipe.hincrby(_k(day, "hosts"), (host or "unknown")[:80], 1)
    pipe.pfadd(_k(day, f"users:{plan}"), user or "anonymous")
    keys = [_k(day, x) for x in ("plans", "routes", "status", "hosts", f"users:{plan}")]
    if status in DENIED_STATUSES:
        pipe.hincrby(_k(day, "denied"), f"{plan} {route} {status}", 1)
        keys.append(_k(day, "denied"))
    if preview and status == 200:
        pipe.hincrby(_k(day, "previews"), f"{plan} {route}", 1)
        keys.append(_k(day, "previews"))
    for key in keys:
        pipe.expire(key, KEEP_SECONDS)
    await pipe.execute()


def _ints(d: Dict[str, Any]) -> Dict[str, int]:
    return {k: int(v) for k, v in (d or {}).items()}


def _top(d: Dict[str, int], n: int) -> Dict[str, int]:
    return dict(sorted(d.items(), key=lambda kv: -kv[1])[:n])


async def day_summary(redis, day: str) -> Dict[str, Any]:
    plans = _ints(await redis.hgetall(_k(day, "plans")))
    users = {p: int(await redis.pfcount(_k(day, f"users:{p}"))) for p in plans}
    return {
        "day": day,
        "requests": sum(plans.values()),
        "requests_by_plan": plans,
        "unique_subscribers_by_plan": users,
        "status": _ints(await redis.hgetall(_k(day, "status"))),
        "top_endpoints": _top(_ints(await redis.hgetall(_k(day, "routes"))), 20),
        "denied": _top(_ints(await redis.hgetall(_k(day, "denied"))), 20),
        "previews": _top(_ints(await redis.hgetall(_k(day, "previews"))), 20),
        "hosts": _ints(await redis.hgetall(_k(day, "hosts"))),
    }


async def summary(redis, days: int = 7) -> List[Dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    return [await day_summary(redis, (today - timedelta(days=i)).isoformat()) for i in range(days)]


def telegram_text(s: Dict[str, Any]) -> str:
    """Short Arabic daily report for the owner."""
    if not s["requests"]:
        return f"تقرير RapidAPI ليوم {s['day']}: لا توجد طلبات عبر RapidAPI."
    plans = "، ".join(f"{p}: {n} طلب من {s['unique_subscribers_by_plan'].get(p, 0)} مشترك"
                      for p, n in sorted(s["requests_by_plan"].items(), key=lambda kv: -kv[1]))
    lines = [f"تقرير RapidAPI ليوم {s['day']}",
             f"إجمالي الطلبات: {s['requests']}",
             f"حسب الخطة: {plans}"]
    denied = sum(s["denied"].values())
    if denied:
        top = list(s["denied"].items())[:3]
        lines.append(f"طلبات رُفضت لأنها خارج الخطة: {denied}")
        lines += [f"  {k}: {v}" for k, v in top]
    previews = sum(s.get("previews", {}).values())
    if previews:
        lines.append(f"معاينات مجانية لمزايا مدفوعة: {previews}")
        lines += [f"  {k}: {v}" for k, v in list(s["previews"].items())[:3]]
    top_ep = list(s["top_endpoints"].items())[:3]
    if top_ep:
        lines.append("أكثر النهايات طلباً: " + "، ".join(f"{k} ({v})" for k, v in top_ep))
    return "\n".join(lines)
