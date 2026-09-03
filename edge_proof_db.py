"""
Edge Proof Database Layer (SQLite)
Manages predictions and outcome tracking for the Horus Edge Proof Engine.
"""
import sqlite3
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("EdgeProofDB")

DB_PATH = Path("/root/horus_flow_api/calibration_data/edge_proof.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT NOT NULL,
    signal TEXT NOT NULL,
    direction_bias TEXT NOT NULL,
    confidence REAL NOT NULL,
    price_at_signal REAL NOT NULL,
    whale_intent TEXT,

    -- Outcomes at different horizons (filled later)
    price_1m REAL,
    price_5m REAL,
    price_15m REAL,
    price_30m REAL,

    move_pct_1m REAL,
    move_pct_5m REAL,
    move_pct_15m REAL,
    move_pct_30m REAL,

    correct_1m INTEGER,  -- 1=correct, 0=wrong, NULL=pending
    correct_5m INTEGER,
    correct_15m INTEGER,
    correct_30m INTEGER,

    -- Dedup: don't record same signal twice in a row
    resolved INTEGER DEFAULT 0  -- 1 when all horizons checked
);

CREATE INDEX IF NOT EXISTS idx_predictions_ts ON predictions(ts);
CREATE INDEX IF NOT EXISTS idx_predictions_symbol ON predictions(symbol);
CREATE INDEX IF NOT EXISTS idx_predictions_signal ON predictions(signal);
CREATE INDEX IF NOT EXISTS idx_predictions_resolved ON predictions(resolved);

CREATE TABLE IF NOT EXISTS daily_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    signal TEXT NOT NULL,
    count INTEGER DEFAULT 0,
    hit_1m INTEGER DEFAULT 0,
    hit_5m INTEGER DEFAULT 0,
    hit_15m INTEGER DEFAULT 0,
    hit_30m INTEGER DEFAULT 0,
    avg_move_1m REAL DEFAULT 0,
    avg_move_5m REAL DEFAULT 0,
    avg_move_15m REAL DEFAULT 0,
    avg_move_30m REAL DEFAULT 0,
    UNIQUE(date, signal)
);
"""


class EdgeProofDB:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._lock = asyncio.Lock()

    async def insert_prediction(self, ts: float, symbol: str, signal: str,
                                direction_bias: str, confidence: float,
                                price: float, whale_intent: str = None) -> int:
        async with self._lock:
            cur = self.conn.execute(
                """INSERT INTO predictions
                   (ts, symbol, signal, direction_bias, confidence, price_at_signal, whale_intent)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (ts, symbol, signal, direction_bias, confidence, price, whale_intent)
            )
            self.conn.commit()
            return cur.lastrowid

    async def get_pending_predictions(self, horizon_seconds: int) -> List[Dict]:
        """Get predictions that need outcome checking for a specific horizon."""
        import time
        now = time.time()
        col_map = {60: "correct_1m", 300: "correct_5m",
                   900: "correct_15m", 1800: "correct_30m"}
        col = col_map.get(horizon_seconds)
        if not col:
            return []

        async with self._lock:
            rows = self.conn.execute(
                f"""SELECT id, ts, symbol, signal, direction_bias, price_at_signal
                    FROM predictions
                    WHERE {col} IS NULL AND ts <= ? AND resolved = 0""",
                (now - horizon_seconds,)
            ).fetchall()
            return [dict(r) for r in rows]

    async def update_outcome(self, pred_id: int, horizon_seconds: int,
                             future_price: float, move_pct: float, correct: bool):
        """Update a prediction with the outcome at a specific horizon."""
        col_map = {
            60:   ("price_1m", "move_pct_1m", "correct_1m"),
            300:  ("price_5m", "move_pct_5m", "correct_5m"),
            900:  ("price_15m", "move_pct_15m", "correct_15m"),
            1800: ("price_30m", "move_pct_30m", "correct_30m"),
        }
        price_col, move_col, correct_col = col_map[horizon_seconds]

        async with self._lock:
            self.conn.execute(
                f"UPDATE predictions SET {price_col}=?, {move_col}=?, {correct_col}=? WHERE id=?",
                (future_price, move_pct, 1 if correct else 0, pred_id)
            )
            # Mark as fully resolved if all 4 horizons done
            self.conn.execute(
                """UPDATE predictions SET resolved = 1
                   WHERE id = ? AND correct_1m IS NOT NULL AND correct_5m IS NOT NULL
                   AND correct_15m IS NOT NULL AND correct_30m IS NOT NULL""",
                (pred_id,)
            )
            self.conn.commit()

    async def get_daily_accuracy(self, hours: int = 24) -> List[Dict]:
        """Get accuracy stats grouped by signal type for the last N hours."""
        import time
        cutoff = time.time() - (hours * 3600)

        async with self._lock:
            rows = self.conn.execute("""
                SELECT signal,
                       COUNT(*) as total,
                       SUM(CASE WHEN correct_1m = 1 THEN 1 ELSE 0 END) as hit_1m,
                       SUM(CASE WHEN correct_5m = 1 THEN 1 ELSE 0 END) as hit_5m,
                       SUM(CASE WHEN correct_15m = 1 THEN 1 ELSE 0 END) as hit_15m,
                       SUM(CASE WHEN correct_30m = 1 THEN 1 ELSE 0 END) as hit_30m,
                       SUM(CASE WHEN correct_1m IS NOT NULL THEN 1 ELSE 0 END) as resolved_1m,
                       SUM(CASE WHEN correct_5m IS NOT NULL THEN 1 ELSE 0 END) as resolved_5m,
                       SUM(CASE WHEN correct_15m IS NOT NULL THEN 1 ELSE 0 END) as resolved_15m,
                       SUM(CASE WHEN correct_30m IS NOT NULL THEN 1 ELSE 0 END) as resolved_30m,
                       ROUND(AVG(move_pct_5m), 4) as avg_move_5m
                FROM predictions
                WHERE ts >= ? AND resolved = 1
                GROUP BY signal
                ORDER BY total DESC
            """, (cutoff,)).fetchall()
            return [dict(r) for r in rows]

    async def get_overall_accuracy(self, hours: int = 24) -> Dict:
        """Get overall accuracy across all signals for the last N hours."""
        import time
        cutoff = time.time() - (hours * 3600)

        async with self._lock:
            row = self.conn.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN correct_1m = 1 THEN 1 ELSE 0 END) as hit_1m,
                       SUM(CASE WHEN correct_5m = 1 THEN 1 ELSE 0 END) as hit_5m,
                       SUM(CASE WHEN correct_15m = 1 THEN 1 ELSE 0 END) as hit_15m,
                       SUM(CASE WHEN correct_30m = 1 THEN 1 ELSE 0 END) as hit_30m,
                       SUM(CASE WHEN correct_1m IS NOT NULL THEN 1 ELSE 0 END) as resolved_1m,
                       SUM(CASE WHEN correct_5m IS NOT NULL THEN 1 ELSE 0 END) as resolved_5m,
                       SUM(CASE WHEN correct_15m IS NOT NULL THEN 1 ELSE 0 END) as resolved_15m,
                       SUM(CASE WHEN correct_30m IS NOT NULL THEN 1 ELSE 0 END) as resolved_30m
                FROM predictions
                WHERE ts >= ? AND resolved = 1
            """, (cutoff,)).fetchone()
            return dict(row) if row else {}

    async def get_prediction_count_last_n_seconds(self, symbol: str, direction_bias: str, seconds: int) -> int:
        """Check if we already logged this direction recently (dedup)."""
        import time
        cutoff = time.time() - seconds
        async with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) as c FROM predictions WHERE symbol=? AND direction_bias=? AND ts >= ?",
                (symbol, direction_bias, cutoff)
            ).fetchone()
            return row['c'] if row else 0


edge_proof_db = EdgeProofDB()
