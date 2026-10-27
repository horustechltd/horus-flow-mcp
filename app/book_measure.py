# -*- coding: utf-8 -*-
"""
Horus Flow API — the measured information of the order book, as shown to clients.

The status monitor recomputes app/book_value_test.py over the last 30 days once a day and stores it in
Redis; this module turns it into the block that /v1/book/pressure and the flow response carry, so a
client sees how much the number it is reading has told about the next minute, not a promise.
"""
import json
import time
from typing import Any, Dict, Optional

ROLLING_KEY = "horus:api:bookvalue:rolling"
LATEST_KEY = "horus:api:book_pressure"   # written by app/book_recorder.py every 15 s
CACHE_S = 60
_cache: Dict[str, Any] = {"at": 0.0, "block": None}

METHOD = ("Spearman rank correlation between the field and the return over the next minute, on non-overlapping "
          "samples, computed separately in each half of the last 30 days. Consistent = same sign and |t| >= 2 in "
          "both halves. Recomputed daily; the monthly results are kept.")
MEANING = ("A small, steady tilt: when the top five bid levels held more size than the top five asks, the next minute "
           "closed higher slightly more often than not. Per trade it is a fraction of a basis point, below typical "
           "trading costs. Use it as context or for timing an order, not as a trading signal.")


def measured_block(res: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    row = next((x for x in res.get("results", []) if x["feature"] == "top5_imbalance" and x["horizon"] == "1m"), None)
    if not row or row.get("ic_h1") is None or row.get("ic_h2") is None:
        return None
    return {
        "field": "top5_imbalance",
        "horizon": "next 1 minute",
        "rank_correlation": {"first_half": row["ic_h1"], "second_half": row["ic_h2"]},
        "consistent": row["consistent"],
        "samples": row.get("n_h1", 0) + row.get("n_h2", 0),
        "pairs": res.get("symbols"),
        "window": f"{res.get('start')}..{res.get('end')}",
        "method": METHOD,
        "meaning": MEANING,
    }


async def current_measure(redis) -> Optional[Dict[str, Any]]:
    """The measured block, read from Redis at most once a minute."""
    if time.time() - _cache["at"] > CACHE_S and redis:
        raw = await redis.get(ROLLING_KEY)
        _cache.update(at=time.time(), block=measured_block(json.loads(raw)) if raw else None)
    return _cache["block"]


def tilt(top5_imbalance: float) -> str:
    """Plain label for the share of top-five size on the bid (0.5 = even). ENGINEERING bands."""
    if top5_imbalance >= 0.6:
        return "BID_HEAVY"
    if top5_imbalance <= 0.4:
        return "ASK_HEAVY"
    return "BALANCED"
