"""
QVE Database Layer (SQLite)
Manages the structured intelligence for the Horus Quant Validation Engine.
Raw JSON forensic data is handled separately.
"""
import sqlite3
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger("QVE_DB")

DB_PATH = Path("/root/horus_flow_api/calibration_data/qve_court.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT NOT NULL,
    signal_type TEXT,
    action TEXT,
    direction TEXT,
    confidence REAL,
    risk TEXT,
    market_state TEXT,
    market_regime TEXT,
    composite_score REAL,
    uuid TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    ts REAL NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    UNIQUE(symbol, timeframe, ts)
);

CREATE TABLE IF NOT EXISTS decision_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER,
    symbol TEXT NOT NULL,
    entry_price REAL,
    entry_ts REAL,
    exit_price REAL,
    exit_ts REAL,
    max_favorable REAL,
    max_adverse REAL,
    pnl_pct REAL,
    fees_pct REAL,
    slippage_pct REAL,
    result_matrix TEXT, -- GOOD_ENTRY, GOOD_AVOIDANCE, MISSED_OPPORTUNITY, etc.
    expectancy REAL,
    expectancy_r REAL,
    time_to_outcome REAL,
    counterfactual_long_r REAL,
    counterfactual_short_r REAL,
    market_regime TEXT,
    regime_transition TEXT,
    opportunity_cost_r REAL DEFAULT 0.0,
    is_realized INTEGER DEFAULT 0,
    regime_duration REAL DEFAULT 0.0,
    FOREIGN KEY(signal_id) REFERENCES signals(id)
);

CREATE TABLE IF NOT EXISTS sequences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    sequence_type TEXT, -- CANONICAL or DYNAMIC
    sequence_name TEXT,
    events_json TEXT, -- JSON array of events
    start_ts REAL,
    end_ts REAL,
    outcome TEXT,
    expectancy REAL
);

CREATE TABLE IF NOT EXISTS engine_rankings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    engine_name TEXT,
    rolling_expectancy REAL,
    rolling_sharpe REAL,
    regime TEXT
);

CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts ON signals(symbol, ts);
CREATE INDEX IF NOT EXISTS idx_candles_symbol_ts ON candles(symbol, ts);
CREATE INDEX IF NOT EXISTS idx_decision_symbol_ts ON decision_evaluations(symbol, entry_ts);
"""

class QVEDatabase:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def init_db(self):
        with self._get_conn() as conn:
            conn.executescript(SCHEMA)

    async def insert_signal(self, data: Dict[str, Any]) -> int:
        def _insert():
            with self._get_conn() as conn:
                cur = conn.execute(
                    '''INSERT INTO signals 
                       (ts, symbol, signal_type, action, direction, confidence, risk, market_state, market_regime, composite_score, uuid) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (
                        data.get('ts'), data.get('symbol'), data.get('signal_type'), data.get('action'),
                        data.get('direction'), data.get('confidence'), data.get('risk'), data.get('market_state'),
                        data.get('market_regime'), data.get('composite_score'), data.get('uuid')
                    )
                )
                return cur.lastrowid
        return await asyncio.to_thread(_insert)

    async def insert_candle(self, symbol: str, timeframe: str, ts: float, o: float, h: float, l: float, c: float, v: float):
        def _insert():
            with self._get_conn() as conn:
                conn.execute(
                    '''INSERT OR IGNORE INTO candles (symbol, timeframe, ts, open, high, low, close, volume)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (symbol, timeframe, ts, o, h, l, c, v)
                )
        await asyncio.to_thread(_insert)

    async def get_klines_since(self, symbol: str, timeframe: str, since_ts: float) -> List[sqlite3.Row]:
        def _get():
            with self._get_conn() as conn:
                return conn.execute(
                    "SELECT * FROM candles WHERE symbol = ? AND timeframe = ? AND ts >= ? ORDER BY ts ASC",
                    (symbol, timeframe, since_ts)
                ).fetchall()
        return await asyncio.to_thread(_get)

    async def get_recent_klines(self, symbol: str, timeframe: str, before_ts: float, limit: int = 14) -> List[sqlite3.Row]:
        """Get the most recent N klines before a given timestamp (for ATR calculation)."""
        def _get():
            with self._get_conn() as conn:
                return conn.execute(
                    "SELECT * FROM candles WHERE symbol = ? AND timeframe = ? AND ts <= ? ORDER BY ts DESC LIMIT ?",
                    (symbol, timeframe, before_ts, limit)
                ).fetchall()[::-1]  # Reverse to chronological order
        return await asyncio.to_thread(_get)

    async def insert_decision_evaluation(self, data: Dict[str, Any]):
        def _insert():
            with self._get_conn() as conn:
                conn.execute(
                    '''INSERT INTO decision_evaluations 
                       (signal_id, symbol, entry_price, entry_ts, exit_price, exit_ts, max_favorable, max_adverse, 
                        pnl_pct, fees_pct, slippage_pct, result_matrix, expectancy, expectancy_r, time_to_outcome,
                        counterfactual_long_r, counterfactual_short_r, market_regime, regime_transition, 
                        opportunity_cost_r, is_realized, regime_duration)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (
                        data.get('signal_id'), data.get('symbol'), data.get('entry_price'), data.get('entry_ts'),
                        data.get('exit_price'), data.get('exit_ts'), data.get('max_favorable'), data.get('max_adverse'),
                        data.get('pnl_pct'), data.get('fees_pct'), data.get('slippage_pct'), data.get('result_matrix'),
                        data.get('expectancy'), data.get('expectancy_r'), data.get('time_to_outcome'),
                        data.get('counterfactual_long_r'), data.get('counterfactual_short_r'), data.get('market_regime'),
                        data.get('regime_transition'), data.get('opportunity_cost_r', 0.0), data.get('is_realized', 0),
                        data.get('regime_duration', 0.0)
                    )
                )
        await asyncio.to_thread(_insert)

    async def insert_sequence(self, data: Dict[str, Any]):
        def _insert():
            with self._get_conn() as conn:
                conn.execute(
                    '''INSERT INTO sequences 
                       (symbol, sequence_type, sequence_name, events_json, start_ts, end_ts, outcome, expectancy)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (
                        data.get('symbol'), data.get('sequence_type'), data.get('sequence_name'), 
                        json.dumps(data.get('events', [])), data.get('start_ts'), data.get('end_ts'), 
                        data.get('outcome'), data.get('expectancy')
                    )
                )
        await asyncio.to_thread(_insert)

    async def get_recent_signals(self, symbol: str, limit: int = 5) -> List[sqlite3.Row]:
        def _get():
            with self._get_conn() as conn:
                return conn.execute(
                    "SELECT * FROM signals WHERE symbol = ? ORDER BY ts DESC LIMIT ?",
                    (symbol, limit)
                ).fetchall()
        return await asyncio.to_thread(_get)

# Global instance
qve_db = QVEDatabase()
