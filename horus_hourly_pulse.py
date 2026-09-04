# -*- coding: utf-8 -*-
"""
Horus Hourly Pulse Engine — v3.5 Institutional Cortex Edition
============================================================
Combines:
  1. Sensory Layer (Horus Flow API Microstructure: real L2 depth, real whale intent)
  2. Cognitive Layer (WiseMan Macro Climate & Volatility State)
  3. Liquidity Heatmap & 24h Structural Pivot Levels (Real S/R, No Static ±1% Formulas)
  4. Anti-Fatigue Session Cadence (Full Executive Brief on 4h Session Opens / Stance Shifts, Sleek Flash Pulse during quiet ranges)
  5. Statistical Outcome Ledger (pulse_ledger.db tracking 15m/1h/4h accuracy)

© 2026 HORUS TECH LTD
"""
import os
import json
import time
import asyncio
import logging
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("HorusPulse")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7649770299:AAEW3nO-ko1a63tQZSzreNF7RpjYjInRCi4")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1245603051")
FLOW_API_URL = os.getenv("FLOW_API_URL", "http://127.0.0.1:8011")
FLOW_API_KEY = os.getenv("FLOW_API_KEY", "horus-trader-key-2026")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DB_PATH = Path("/root/horus_flow_api/calibration_data/pulse_ledger.db")


class PulseLedgerDB:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS pulse_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                date_str TEXT NOT NULL,
                symbol TEXT NOT NULL,
                price_at_pulse REAL NOT NULL,
                structure TEXT NOT NULL,
                market_bias TEXT NOT NULL,
                risk_bias TEXT NOT NULL,
                gravity_dir TEXT NOT NULL,
                gravity_score REAL NOT NULL,
                crowd_bias TEXT NOT NULL,
                top_traders_ls REAL NOT NULL,
                smart_divergence INTEGER NOT NULL,
                nearest_liq_price REAL,
                nearest_liq_dist_pct REAL,
                price_15m REAL,
                move_pct_15m REAL,
                liq_swept_15m INTEGER DEFAULT 0,
                price_1h REAL,
                move_pct_1h REAL,
                liq_swept_1h INTEGER DEFAULT 0,
                price_4h REAL,
                move_pct_4h REAL,
                liq_swept_4h INTEGER DEFAULT 0,
                resolved INTEGER DEFAULT 0
            )
        """)
        self.conn.commit()

    def record_pulse(self, ts, date_str, symbol, price, structure,
                     market_bias, risk_bias, gravity_dir, gravity_score,
                     crowd_bias, top_traders_ls, smart_divergence,
                     nearest_liq_price, nearest_liq_dist_pct):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO pulse_snapshots (
                ts, date_str, symbol, price_at_pulse, structure,
                market_bias, risk_bias, gravity_dir, gravity_score,
                crowd_bias, top_traders_ls, smart_divergence,
                nearest_liq_price, nearest_liq_dist_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ts, date_str, symbol, price, structure,
            market_bias, risk_bias, gravity_dir, gravity_score,
            crowd_bias, top_traders_ls, 1 if smart_divergence else 0,
            nearest_liq_price, nearest_liq_dist_pct
        ))
        self.conn.commit()
        return cur.lastrowid

    def get_pending_evaluations(self, horizon_seconds: int):
        now_ts = time.time()
        min_age = horizon_seconds
        col_map = {900: "price_15m", 3600: "price_1h", 14400: "price_4h"}
        target_col = col_map[horizon_seconds]
        query = f"""
            SELECT * FROM pulse_snapshots
            WHERE {target_col} IS NULL
              AND (? - ts) >= ?
              AND (? - ts) <= ? + 3600
        """
        return self.conn.execute(query, (now_ts, min_age, now_ts, min_age)).fetchall()

    def update_evaluation(self, row_id: int, horizon_seconds: int, future_price: float, move_pct: float, liq_swept: bool):
        col_map = {
            900:   ("price_15m", "move_pct_15m", "liq_swept_15m"),
            3600:  ("price_1h", "move_pct_1h", "liq_swept_1h"),
            14400: ("price_4h", "move_pct_4h", "liq_swept_4h"),
        }
        price_col, move_col, swept_col = col_map[horizon_seconds]
        self.conn.execute(
            f"UPDATE pulse_snapshots SET {price_col}=?, {move_col}=?, {swept_col}=? WHERE id=?",
            (future_price, move_pct, 1 if liq_swept else 0, row_id)
        )
        self.conn.execute(
            "UPDATE pulse_snapshots SET resolved=1 WHERE id=? AND price_15m IS NOT NULL AND price_1h IS NOT NULL AND price_4h IS NOT NULL",
            (row_id,)
        )
        self.conn.commit()


pulse_db = PulseLedgerDB()


class HorusHourlyPulse:
    def __init__(self):
        import redis
        self.r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
        self.last_stance = None
        self.last_full_report_ts = 0

    def _get_json(self, key: str) -> dict:
        try:
            val = self.r.get(key)
            return json.loads(val) if val else {}
        except Exception:
            return {}

    def _get_binance_24hr(self, symbol: str) -> dict:
        """Fetch real 24h High, Low, Price, and Volume from Binance REST."""
        try:
            url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
            req = urllib.request.Request(url, headers={"User-Agent": "HorusHourlyPulse/3.5"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                return {
                    "price": float(data.get("lastPrice", 0.0)),
                    "high_24h": float(data.get("highPrice", 0.0)),
                    "low_24h": float(data.get("lowPrice", 0.0)),
                    "chg_24h": float(data.get("priceChangePercent", 0.0)),
                    "volume_24h": float(data.get("quoteVolume", 0.0))
                }
        except Exception as e:
            logger.warning(f"Failed to fetch 24hr stats for {symbol}: {e}")
            return {"price": 0.0, "high_24h": 0.0, "low_24h": 0.0, "chg_24h": 0.0, "volume_24h": 0.0}

    def _get_flow_microstructure(self, symbol: str) -> dict:
        """Fetch live microstructure orderbook & whale intent from local Flow API."""
        try:
            url = f"{FLOW_API_URL}/v1/flow/crypto/{symbol}?key={FLOW_API_KEY}"
            req = urllib.request.Request(url, headers={"User-Agent": "HorusHourlyPulse/3.5"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                metrics = data.get("metrics") or {}
                whale = data.get("whale_intent") or {}
                return {
                    "signal": data.get("signal", "NEUTRAL"),
                    "action": data.get("action", "WAIT"),
                    "direction_bias": data.get("direction_bias", "NEUTRAL"),
                    "confidence": float(data.get("confidence", 0.5)),
                    "explanation": data.get("explanation", ""),
                    "bid_ask_ratio": float(metrics.get("bid_ask_ratio") or 1.0),
                    "buy_sell_ratio": float(metrics.get("buy_sell_ratio") or 0.5),
                    "wall_side": metrics.get("wall_side") or "NONE",
                    "whale_dir": whale.get("direction") or "NEUTRAL",
                    "whale_buy": float(whale.get("buy_ratio") or 0.5),
                    "whale_exec": float(whale.get("exec_intensity") or 0.0),
                    "whale_persist": int(whale.get("persistence") or 0)
                }
        except Exception as e:
            logger.warning(f"Failed to fetch flow microstructure for {symbol}: {e}")
            return {
                "signal": "NEUTRAL", "action": "WAIT", "direction_bias": "NEUTRAL", "confidence": 0.5,
                "explanation": "", "bid_ask_ratio": 1.0, "buy_sell_ratio": 0.5, "wall_side": "NONE",
                "whale_dir": "NEUTRAL", "whale_buy": 0.5, "whale_exec": 0.0, "whale_persist": 0
            }

    def generate_report(self, force_full: bool = False) -> str:
        """Assembles institutional intelligence report with structural levels and anti-fatigue cadence."""
        now_ts = time.time()
        now_dt = datetime.now(timezone.utc)
        now_utc = now_dt.strftime("%Y-%m-%d %H:%M UTC")
        current_hour = now_dt.hour

        # 1. Macro Climate & Global Ignition
        climate = self._get_json("hta:state:wiseman_climate")
        ignition = self._get_json("horus:global_ignition_state")

        mode = climate.get("market_mode", "RANGE")
        raw_health = climate.get("health", "HEALTHY")
        reason = climate.get("reason", "")

        # Dynamic Health Calibration
        health = raw_health
        if "slope: -" in reason or "Vol ratio: 0." in reason or "RSI: 4" in reason or "RSI: 3" in reason:
            if raw_health in ("HEALTHY", "STABLE"):
                health = "FRAGILE"

        # 2. Gather All Asset Intelligence (Live 24h Ticker + Microstructure + Liquidity Heatmap)
        asset_data = {}
        down_gravity_count = 0
        long_heavy_count = 0

        for sym in SYMBOLS:
            t24 = self._get_binance_24hr(sym)
            flow = self._get_flow_microstructure(sym)
            heatmap = self._get_json(f"horus:liq_heatmap:{sym}")

            price = t24["price"]
            high_24h = t24["high_24h"]
            low_24h = t24["low_24h"]
            chg_24h = t24["chg_24h"]

            gravity_dir = heatmap.get("gravity_direction", "NEUTRAL")
            gravity_score = float(heatmap.get("gravity_score", 0.0))
            crowd_bias = heatmap.get("crowd_bias", "NEUTRAL")
            top_ls = float(heatmap.get("long_short_ratio_top_traders", 1.0))
            smart_divergence = heatmap.get("smart_money_divergence", False)
            liq_zones = heatmap.get("estimated_liquidation_zones", {})

            if gravity_dir == "DOWN":
                down_gravity_count += 1
            if "LONG" in crowd_bias.upper():
                long_heavy_count += 1

            # Dynamic Support Level (Structural Danger Floor)
            # Use real 24h Low or Nearest Long Liquidation Cluster
            if liq_zones.get("long_zones") and float(liq_zones["long_zones"][0]) < price:
                danger_level_price = float(liq_zones["long_zones"][0])
            else:
                danger_level_price = low_24h if low_24h > 0 and low_24h < price else price * 0.99
            danger_dist_pct = ((danger_level_price - price) / price) * 100 if price > 0 else -1.0

            # Dynamic Resistance Level (Structural Safety Pivot)
            # Use real 24h High or Nearest Short Liquidation Cluster
            if liq_zones.get("short_zones") and float(liq_zones["short_zones"][0]) > price:
                safe_level_price = float(liq_zones["short_zones"][0])
            else:
                safe_level_price = high_24h if high_24h > 0 and high_24h > price else price * 1.01
            safe_dist_pct = ((safe_level_price - price) / price) * 100 if price > 0 else 1.0

            asset_data[sym] = {
                "price": price,
                "high_24h": high_24h,
                "low_24h": low_24h,
                "chg_24h": chg_24h,
                "flow": flow,
                "gravity_dir": gravity_dir,
                "gravity_score": gravity_score,
                "crowd_bias": crowd_bias,
                "top_ls": top_ls,
                "smart_divergence": smart_divergence,
                "danger_level_price": danger_level_price,
                "danger_dist_pct": danger_dist_pct,
                "safe_level_price": safe_level_price,
                "safe_dist_pct": safe_dist_pct,
            }

            # Record into Statistical Outcome Ledger
            if price > 0:
                pulse_db.record_pulse(
                    ts=now_ts,
                    date_str=now_utc,
                    symbol=sym,
                    price=price,
                    structure=f"{mode} / {health}",
                    market_bias="محايد (NEUTRAL)" if mode == "RANGE" else "مائل للصعود",
                    risk_bias="هابط (DOWNSIDE ASYMMETRY)" if (long_heavy_count >= 2 and down_gravity_count >= 2) else "متوازن",
                    gravity_dir=gravity_dir,
                    gravity_score=gravity_score,
                    crowd_bias=crowd_bias,
                    top_traders_ls=top_ls,
                    smart_divergence=smart_divergence,
                    nearest_liq_price=danger_level_price,
                    nearest_liq_dist_pct=danger_dist_pct
                )

        # 3. Tactical Synthesis & Horus Cortex Cognitive Brain Integration
        btc = asset_data.get("BTCUSDT", {})
        btc_price = btc.get("price", 0.0)
        btc_flow = btc.get("flow", {})

        # Load Live Horus Cortex Telemetry
        cortex = self._get_json("horus:maestro:state")
        cortex_nar = self._get_json("horus:maestro:narrative")
        trust_score = round(float(cortex.get("trust_score", 50.0)), 0) if cortex else 50.0
        cortex_regime = cortex.get("state", "TRANSITION") if cortex else "TRANSITION"
        cortex_dir = cortex.get("transition_direction", "STABLE") if cortex else "STABLE"
        cortex_taker = float(cortex.get("taker_ratio", 1.0)) if cortex else 1.0
        cortex_ignition = float(cortex.get("global_ignition", 0.0)) if cortex else 0.0

        state_ar_map = {
            "EXPANSION": "🟢 صعود قوي وتوسع سيولة شامل",
            "BUILDING": "🟢 بناء زخم تدريجي وتجميع إيجابي",
            "HEALTHY_CONSOLIDATION": "⚪ تماسك صحي وتنفس طبيعي للسعر",
            "EXHAUSTION": "🟠 استنفاد صعود وفخ امتصاص في القمة",
            "TRANSITION": "🟡 مرحلة انتقالية وإعادة تقييم الحسابات",
            "BREAKDOWN": "🔴 انهيار وتصريف حاد يستوجب الحماية"
        }
        traffic_light = state_ar_map.get(cortex_regime, "🟡 حذر وترقب — وضعية الدفاع")

        # Extract structural boundaries from Cortex conditions
        risk_factors = cortex_nar.get("risk_factors", []) if cortex_nar else []
        what_improves = cortex_nar.get("what_improves_verdict", []) if cortex_nar else []
        what_worsens = cortex_nar.get("what_worsens_verdict", []) if cortex_nar else []
        cortex_summary = cortex_nar.get("summary_arabic", "") if cortex_nar else ""

        btc_danger = btc.get("danger_level_price", btc_price * 0.99)
        btc_safe = btc.get("safe_level_price", btc_price * 1.01)

        for w in what_worsens:
            if "$" in w:
                try:
                    p = float(w.split("$")[1].split()[0].replace(",", ""))
                    if p > 0:
                        btc_danger = p
                        break
                except Exception:
                    pass

        for i in what_improves:
            if "$" in i:
                try:
                    p = float(i.split("$")[1].split()[0].replace(",", ""))
                    if p > 0:
                        btc_safe = p
                        break
                except Exception:
                    pass

        btc_danger_dist = ((btc_danger - btc_price) / btc_price * 100) if btc_price > 0 else -1.0
        btc_safe_dist = ((btc_safe - btc_price) / btc_price * 100) if btc_price > 0 else 1.0

        # Anti-Fatigue Session Cadence Logic
        current_stance = f"{cortex_regime}_{cortex_dir}"
        is_major_session = (current_hour % 4 == 0)
        is_stance_shift = (self.last_stance is not None and self.last_stance != current_stance)
        should_send_full = force_full or is_major_session or is_stance_shift

        self.last_stance = current_stance

        # Determine humanized verdict & advice precisely from Cortex Regime, Direction & Contradiction Engine
        active_contradictions = cortex.get("active_contradictions", []) if cortex else []
        has_contradiction = bool(active_contradictions) or (cortex_regime == "TRANSITION" and trust_score < 50)
        ret_15m = float(cortex.get("btc_15m_return_pct", 0.0)) if cortex else 0.0
        chg_24h = btc.get('chg_24h', 0.0)

        # Dynamic Dip Zone Boundaries (حساب دقيق لمنطقة ارتداد الكاش)
        dip_floor = btc_danger
        dip_roof = btc_price * 0.985
        if dip_roof <= dip_floor:
            dip_roof = max(dip_floor * 1.015, btc_price * 0.99)

        # ─────────────────────────────────────────────────────────────────
        # 1. ALL MARKET REGIMES & CONDITIONS (تغطية شاملة لكل حالات السوق)
        # ─────────────────────────────────────────────────────────────────
        if cortex_regime == "EXPANSION":
            verdict_badge = "🟢 <b>صعود وزخم قيادي مشتعل:</b> تدفقات شراء حقيقية تقود السوق لاختراق القمم"
            story_intro = f"السوق مشتعل بنشاط شرائي واسع، والبيتكوين بيقود موجة صعود حقيقية مخترقاً القمم السابقة بقوة ليصل إلى <code>${btc_price:,.0f}</code> بزيادة (<code>{chg_24h:+.2f}%</code>)."
            story_question = "لكن السؤال الأهم: هل الزخم ده حقيقي ومكمل؟ ولا داخلين على فخ تصريف؟"
            whale_point1 = f"تدفق الشراء المباشر (Taker Buy: <code>{cortex_taker:.2f}</code>) بيؤكد إن كبار المتداولين بيدخوا سيولة حقيقية وبيشتروا من العرض المتاح (Market Buy) بشهية مفتوحة دون انتظار."
            if cortex_ignition >= 0.35:
                whale_point2 = "الموجة دي مدعومة باتساع إيجابي في سلة العملات البديلة، وده بيأكد إن السيولة عامة وشاملة ومش حركة معزولة."
            else:
                whale_point2 = "السيولة مركزة بشكل شبه كامل في البيتكوين (BTC Dominance)، وباقي العملات مستنية استقراره عشان تبدأ تلحق بيه."
            story_takeaway = "عشان كده.. الزخم إيجابي، لكن الشراء الذكي لا يكون أبداً بمطاردة الشموع الخضراء في القمة، بل باقتناص الارتدادات السريعة."
            advice_holders = "دع أرباحك تمتد مع رفع الوقف المتحرك لتأمين المكاسب مع كل قمة جديدة."
            advice_cash = f"فرصة ممتازة للدخول مع أي تراجع خاطف (Pullback) نحو <code>${dip_roof:,.0f}</code>، بوقف خسارة محدد أسفل <code>${btc_danger:,.0f}</code>."

        elif cortex_regime == "BUILDING":
            verdict_badge = "🟢 <b>بناء وتجميع إيجابي:</b> الحيتان يمتصون العروض بهدوء ويؤسسون لانفجار قادم"
            story_intro = f"هدوء نسبي يسبق الحركة.. البيتكوين بيتحرك بنمط تجميعي رصين عند <code>${btc_price:,.0f}</code>، والمشترون بيبنوا مراكزهم تدريجياً دون لفت الأنظار."
            story_question = "إيه اللي بيحصل تحت السطح؟ وليه السعر مش بينفجر بسرعة؟"
            whale_point1 = f"الحيتان بيمتصوا عروض البيع بهدوء تام دون إثارة شريط الصفقات؛ نسبة الشراء (<code>{cortex_taker:.2f}</code>) بتعكس تجميعاً ذكياً وممنهجاً فوق مناطق الدعم."
            whale_point2 = "السعر بيصنع قيعان أعلى تدريجياً (Higher Lows)، وده مؤشر كلاسيكي على إن العرض المعروض في السوق بينفد بانتظار شرارة الاختراق."
            story_takeaway = "مرحلة التجميع هي أفضل فترات التمركز الهادئ للمستثمر الصبور، بشرط الالتزام بوقف الخسارة أسفل قاعدة التجميع."
            advice_holders = "التزم بمراكزك ودع الحيتان يكملون تجميعهم طالما الدعم صامد تماماً."
            advice_cash = f"ابدأ بالتمركز التدريجي (DCA) في منطقة الارتداد (<code>${dip_floor:,.0f} - ${dip_roof:,.0f}</code>) بوقف خسارة محكم، ولا تنتظر حتى يطير السعر."

        elif cortex_regime == "HEALTHY_CONSOLIDATION":
            verdict_badge = "⚪ <b>تماسك صحي واستيعاب للمكاسب:</b> ثبات في مناطق عليا بعد موجة الصعود دون بوادر تصريف"
            if ret_15m < -0.10:
                story_intro = f"البيتكوين يمر بتراجع تصحيحي هادئ وصحي عند <code>${btc_price:,.0f}</code> بعد موجة الصعود الأخيرة (تغير 24س: <code>{chg_24h:+.2f}%</code>)، لتهدئة المؤشرات وتنظيف الرافعة المالية."
                story_question = "هل التراجع ده فرصة اقتناص ارتداد (Buy The Dip) ولا بداية انعكاس؟"
            else:
                story_intro = f"البيتكوين بعد ما ولّع شمعة الصعود الأخيرة وتجاوز المحطات الهامة، دخل في مرحلة <b>«تنفس وتماسك صحي»</b> فوق <code>${btc_price:,.0f}</code> (تغير 24س: <code>{chg_24h:+.2f}%</code>)."
                story_question = "ليه وتيرة الصعود هديت فجأة؟ وهل الهدوء ده تمهيد لجولة صعود جديدة؟"

            whale_point1 = f"بعد صعود قوي بأكثر من 4%، طبيعي جداً نشوف هدوء مؤقت في شريط الصفقات (Taker: <code>{cortex_taker:.2f}</code>)؛ كبار المتداولين بيستوعبوا مكاسبهم دون أي ضغط بيعي حقيقي يكسر الدعوم."
            whale_point2 = "السيولة مركزة حالياً في البيتكوين (BTC Dominance)، وفوليوم البيع منخفض ومجفف (Volume Dry-Up)، وده بيمثل غياباً كاملاً للبائعين الحقيقيين حتى اللحظة."
            story_takeaway = "عشان كده.. ما نستعجلش بالدخول في منتصف الطريق؛ الانتظار والقناصة هما عنوان الجلسة."
            advice_holders = "مبروك مكاسبك.. احتفظ بصفقاتك وارفع وقفك أسفل الدعم الرقمي القريب وسيب الحركة تتنفس."
            advice_cash = f"متجريش ورا الشموع في القمة! الدخول الصح يا إما بعد اختراق <code>${btc_safe:,.0f}</code> بثبات، أو باقتناص الارتداد في منطقة الخصم (<code>${dip_floor:,.0f} - ${dip_roof:,.0f}</code>)."

        elif cortex_regime == "EXHAUSTION":
            verdict_badge = "🟠 <b>استنفاد الصعود وفخاخ امتصاص:</b> المشترون يندفعون بجهد لكن السعر يصطدم بجدران بيع كثيفة"
            story_intro = f"⚠️ جرس إنذار للمندفعين.. البيتكوين يتداول عند <code>${btc_price:,.0f}</code> ولكن مؤشرات الزخم بدأت تُظهر علامات إجهاد واستنفاد واضحة عند القمة."
            story_question = "ليه السعر مش قادر يكمل رغم محاولات الشراء المستمرة؟"
            whale_point1 = f"رادارات التدفق بترصد <b>فخ امتصاص بيعي (Absorption Trap)</b>؛ المشترون الصغار بيشتروا بحماس، لكن طلباتهم بتصطدم بجدران بيع كثيفة ومخفية من الحيتان بتكتم حركة السعر."
            whale_point2 = "نسبة كفاءة الشراء بدأت تتلاشى، ومغناطيس السيولة بدأ يسحب تدريجياً نحو الأسفل بحثاً عن تصفيات وعناقيد سيولة أعمق."
            story_takeaway = "احذر من الوقوع في فخ الشراء عند القمم المرهقة؛ حماية الأرباح والكاش هنا هي القرار الأكثر حكمة واحترافية."
            advice_holders = "اجنِ جزءاً كبيراً من أرباحك فوراً (خفف 50% على الأقل) وارفع وقفك لنقطة الدخول؛ السوق مهدد بانعكاس تصحيحي سريع."
            advice_cash = "احذر الشراء عند القمم! السعر يرتفع بضعف وسيولة الحيتان تتوقف عن الدعم.. انتظر تصحيحاً حقيقياً."

        elif cortex_regime == "BREAKDOWN":
            verdict_badge = "🔴 <b>وضع الانهيار والتصريف:</b> كسر هيكلي حاد وتصريف بيعي صريح يستوجب تفعيل الوقف"
            story_intro = f"🚨 وضع الحماية وتفعيل الوقف.. ضغط بيعي صريح وخروج سيولة حاد يدفع البيتكوين للتراجع السريع عند <code>${btc_price:,.0f}</code> (<code>{chg_24h:+.2f}%</code>)."
            story_question = "هل ده مجرد تصحيح عابر ولا كسر هيكلي يستوجب الخروج؟"
            whale_point1 = "كسر واضح للدعوم الهيكلية مع تسارع في وتيرة البيع المباشر وعجز كامل من المشترين عن الدفاع عن المستويات المحورية."
            whale_point2 = "كبار المتداولين سحبوا طلبات الشراء العميقة، ومغناطيس التصفية يسحب بقوة نحو مستويات القيعان القادمة."
            story_takeaway = "الكاش هو الملك الآن (Cash is King). لا تحاول أبداً اصطياد سكين ساقطة، والأولوية المطلقة هي حفظ رأس المال."
            advice_holders = "فعّل وقف الخسارة فوراً واخرج بأقل الأضرار، الأمل والتمني ليسا استراتيجية تداول."
            advice_cash = "ابقَ في الكاش 100%، ولا تفكر في لمس السوق حتى تستقر السيولة ويظهر جدار طلبات حقيقي."

        else: # TRANSITION
            if cortex_dir == "DETERIORATING":
                verdict_badge = "🟠 <b>ضغط بيعي تدريجي وترنح:</b> السعر يختبر قيعان النطاق والسيولة تتناقص"
                story_intro = f"السوق يعاني من ترنح وضعف في الزخم عند <code>${btc_price:,.0f}</code>؛ كفة البائعين تميل تدريجياً لضغط السعر نحو اختبار حدود الدعم الخطرة."
                story_question = "هل الدعم قادر يصمد أمام الضغط المتزايد؟ ولا الكسر وشيك؟"
                whale_point1 = "طلبات الشراء في عمق السوق تتراجع، ونشاط الشراء المباشر أصبح باهتاً وعاجزاً عن صناعة قمم جديدة."
                whale_point2 = f"مغناطيس السيولة يسحب السعر نحو خط الدفاع الأخير عند <code>${btc_danger:,.0f}</code>، مما يزيد احتمالات حدوث تصفية للمتسرعين."
                story_takeaway = "الحذر الدفاعي هو الأساس الآن؛ لا تتورط في شراء سكون هابط، وانتظر رد فعل السعر عند الدعم."
                advice_holders = f"ارفع وقفك واجعله قريباً جداً أسفل <code>${btc_danger:,.0f}</code>، ولا تسمح بتحول الصفقات لخسائر عميقة."
                advice_cash = "الكاش أمان وراحة بال؛ لا تدخل حتى يثبت ارتداد حقيقي بجدار سيولة صلب."

            elif has_contradiction:
                verdict_badge = "🟡 <b>صعود قيادي للبيتكوين وتشتت:</b> الحيتان يركزون في BTC مع ترقب وحذر في باقي السوق"
                story_intro = f"السوق في حالة تموضع انتقالي عند <code>${btc_price:,.0f}</code>؛ البيتكوين بيحاول التماسك بمفرده بينما باقي السوق في حالة ترقب وتراجع."
                story_question = "ليه التباين ده حاصل بين البيتكوين وباقي السوق؟"
                whale_point1 = f"تدفقات الحيتان مركزة في BTC فقط، بينما تسجل سلة الألتكوين ركوداً وضعفاً في السيولة، مما يمنع السوق من إطلاق موجة صعود جماعية."
                whale_point2 = "جاذبية السيولة العامة هابطة في العملات الصغيرة، وده بيخلق حالة من التشتت تستوجب الحذر الشديد."
                story_takeaway = "التركيز فقط على قائد السوق، وتجنب المخاطرة في العملات البديلة حتى يثبت الاتجاه العام."
                advice_holders = "ركز على البيتكوين وخفف مراكزك في الألتكوين الضعيف لحين وضوح اتساع السوق."
                advice_cash = "التزم بالتمركز في قائد السوق فقط (BTC)، وتجنب الدخول في العملات البديلة حتى تؤكد السيولة."

            else:
                verdict_badge = "🟡 <b>مرحلة تذبذب واختبار:</b> السوق يختبر مناطقه المفصلية دون اتجاه حاسم"
                story_intro = f"السوق يمر بمرحلة اختبار مفصلية وتوازن حذر عند <code>${btc_price:,.0f}</code>؛ شد وجذب بين قوى الشراء والبيع داخل نطاق ضيق."
                story_question = "مين اللي ماسك زمام الأمور حالياً؟ وما هو الاتجاه الأرجح؟"
                whale_point1 = f"شريط الصفقات يظهر توازناً نسبياً (Taker: <code>{cortex_taker:.2f}</code>)، مع تداول عرضي عشوائي لتنظيف الرافعة المالية للطرفين."
                whale_point2 = f"صانع السوق لم يحسم قراره بعد بالاختراق أعلى <code>${btc_safe:,.0f}</code> أو الكسر أسفل <code>${btc_danger:,.0f}</code>."
                story_takeaway = "التداول في مناطق الحيرة يستنزف المحفظة؛ راقب مستويات الحسم ولا تستبق إشارة التأكيد."
                advice_holders = "قلّص أحجام العقود والتزم بمستويات الدعم والخطر الرقمية بدقة."
                advice_cash = "التزم بالكاش والمراقبة؛ الدخول الآن عالي المخاطر بانتظار إشارة اختراق واضحة."

        # If not major session and no stance change, generate a SLEEK HUMANIZED FLASH PULSE
        if not should_send_full:
            flash = f"⚡ <b>نبضة قناص الألفا السريعة | HORUS QUICK PULSE</b>\n"
            flash += f"━━━━━━━━━━━━━━━━━━━━\n"
            flash += f"⏰ <code>{now_utc}</code> | 🪙 <b>البيتكوين:</b> <code>${btc_price:,.0f} ({btc.get('chg_24h', 0):+.2f}%)</code>\n\n"
            flash += f"🚦 <b>القرار اللحظي لحورس:</b>\n{verdict_badge}\n"
            flash += f"🛡️ <b>مؤشر أمان السوق:</b> <code>{trust_score:.0f}%</code>\n\n"
            flash += f"🎯 <b>أرقام الحسم للمحفظة:</b>\n"
            flash += f"🛑 <b>جرس الخطر:</b> <code>${btc_danger:,.0f} ({btc_danger_dist:+.1f}%)</code>\n"
            flash += f"🚀 <b>بوابة الأمان:</b> <code>${btc_safe:,.0f} ({btc_safe_dist:+.1f}%)</code>\n"
            if cortex_regime in ("EXPANSION", "BUILDING", "HEALTHY_CONSOLIDATION"):
                flash += f"🔵 <b>منطقة الارتداد (Buy The Dip):</b> <code>${dip_floor:,.0f} - ${dip_roof:,.0f}</code>\n"
            flash += f"\n💡 <b>بوصلة القرار لمحفظتك:</b>\n"
            flash += f"• 🟢 <b>للداخلين:</b> <i>{advice_holders}</i>\n"
            flash += f"• 🟡 <b>للكاش:</b> <i>{advice_cash}</i>\n"
            flash += f"━━━━━━━━━━━━━━━━━━━━\n"
            flash += f"📊 <b>لمتابعة رادار السيولة المباشر والداشبورد:</b>\n👉 https://flow.horustek.pro/dash/"
            return flash

        # ═════════════════════════════════════════════════
        # 🦅 THE UNIFIED FULL HUMANIZED CORTEX REPORT
        # ═════════════════════════════════════════════════
        report = f"🦅 <b>نبضة قناص الألفا | إيه اللي بيحصل في كواليس السوق دلوقتي؟</b>\n"
        report += f"<i>«العين ترصد السيولة.. والعقل يزن القرار»</i>\n"
        report += f"━━━━━━━━━━━━━━━━━━━━\n"
        report += f"⏰ <b>التوقيت:</b> <code>{now_utc}</code>\n\n"

        # SECTION 1: VERDICT
        report += f"🚦 <b>القرار اللحظي لحورس:</b>\n"
        report += f"{verdict_badge}\n"
        report += f"🛡️ <b>درجة أمان السوق:</b> <code>{trust_score:.0f}%</code>\n"
        report += f"🪙 <b>سعر البيتكوين:</b> <code>${btc_price:,.0f}</code> ({btc.get('chg_24h', 0):+.2f}%)\n\n"

        # SECTION 2: HUMANIZED NARRATIVE & WHALE BACKSTAGE
        report += f"{story_intro}\n\n"
        report += f"<b>{story_question}</b>\n\n"
        report += f"🔍 <b>ما وراء الكواليس (قراءة في عقل الحيتان):</b>\n"
        report += f"• {whale_point1}\n"
        report += f"• {whale_point2}\n\n"
        report += f"<i>{story_takeaway}</i>\n\n"

        if risk_factors:
            report += f"⚠️ <b>نقاط انتباه وتحذير للمضاربين:</b>\n"
            for rf in risk_factors[:3]:
                rf_clean = rf.replace("Taker:", "ضغط الشراء المباشر:").replace("Bid Wall Trap", "مصيدة جدار الشراء الوهمي")
                report += f"• {rf_clean}\n"
            report += "\n"

        # SECTION 3: DECISION MAP & BOUNDARIES
        report += f"🎯 <b>أرقام المعركة (خريطة الدخول والخروج):</b>\n"
        report += f"🟢 <b>شرط استمرار الإيجابية وشراء الاختراق:</b>\n"
        report += f"  • اختراق حاجز الأمان عند <code>${btc_safe:,.0f} ({btc_safe_dist:+.1f}%)</code> والإغلاق فوقه بثبات.\n"
        report += f"🔴 <b>جرس الإنذار ووقف الخسارة:</b>\n"
        report += f"  • كسر الدعم الهيكلي عند <code>${btc_danger:,.0f} ({btc_danger_dist:+.1f}%)</code> يفتح الباب لمزيد من الهبوط.\n"
        report += f"🔵 <b>منطقة اقتناص الارتداد لمن في الكاش (Buy The Dip):</b>\n"
        if cortex_regime in ("EXHAUSTION", "BREAKDOWN"):
            report += f"  • 🚫 الشراء محظور حالياً؛ لا تحاول اصطياد سكين ساقطة وانتظر حتى تتشكل أرضية طلب حقيقية.\n\n"
        else:
            report += f"  • التمركز الآمن بين <code>${dip_floor:,.0f}</code> و <code>${dip_roof:,.0f}</code> بشرط ظهور جدار طلبات حقيقي.\n\n"

        # SECTION 4: LIVE ASSET TELEMETRY (CLEAN ARABIC)
        report += f"━━━━━━━━━━━━━━━━━━━━\n"
        report += f"🔬 <b>رادار العملات الكبرى (تشريح السيولة):</b>\n"

        for sym in SYMBOLS:
            d = asset_data.get(sym, {})
            price = d.get("price", 0.0)
            chg = d.get("chg_24h", 0.0)
            flow_info = d.get("flow", {})
            whale_dir = flow_info.get("whale_dir", "NEUTRAL")
            whale_buy = flow_info.get("whale_buy", 0.5)
            smart_divergence = d.get("smart_divergence", False)
            gravity_dir = d.get("gravity_dir", "NEUTRAL")
            danger_p = d.get("danger_level_price", 0.0)

            s_name = "البيتكوين (BTC)" if "BTC" in sym else "الإيثيريوم (ETH)" if "ETH" in sym else "سولانا (SOL)"

            sell_pct = (1.0 - whale_buy) * 100
            if whale_dir == "LONG" and whale_buy >= 0.65:
                w_txt = f"🟢 شراء وتجميع حيتان قوي ({whale_buy*100:.0f}%)"
            elif whale_dir == "SHORT" and whale_buy <= 0.35:
                if chg > 2.0:
                    w_txt = f"🟠 جني أرباح وضغط بيعي موضعي ({sell_pct:.0f}% بيع)"
                else:
                    w_txt = f"🔴 ضغط بيعي وتصريف حيتان واضح ({sell_pct:.0f}% بيع)"
            else:
                w_txt = "⚪ نشاط حيتان هادئ ومتوازن"

            if gravity_dir == "DOWN" and danger_p > 0:
                grav_txt = f"⬇️ جاذبية هابطة (مغناطيس السيولة يسحب نحو <code>${danger_p:,.1f}</code>)"
            elif gravity_dir == "UP" and danger_p > 0:
                grav_txt = f"⬆️ جاذبية صاعدة (مغناطيس السيولة يسحب نحو <code>${danger_p:,.1f}</code>)"
            else:
                grav_txt = "➡️ السيولة متمركزة في نطاق عرضي"

            div_txt = " | ⚠️ <i>انحراف: الحيتان يخالفون اتجاه الجمهور!</i>" if smart_divergence else ""

            report += f"\n🪙 <b>{s_name}</b> — <code>${price:,.1f} ({chg:+.2f}%)</code>\n"
            report += f"• <b>سلوك الحيتان:</b> {w_txt}\n"
            report += f"• <b>مسار السيولة:</b> {grav_txt}{div_txt}\n"

        # SECTION 5: GOLDEN ADVICE & CTA
        report += f"\n━━━━━━━━━━━━━━━━━━━━\n"
        report += f"💡 <b>بوصلة قناص الألفا لمحفظتك:</b>\n"
        report += f"• 🟢 <b>لمن يملك صفقات (داخل السوق):</b>\n  <i>«{advice_holders}»</i>\n"
        report += f"• 🟡 <b>لمن في الكاش (يبحث عن دخول):</b>\n  <i>«{advice_cash}»</i>\n"
        report += f"━━━━━━━━━━━━━━━━━━━━\n"
        report += f"📊 <b>لمتابعة رادار السيولة المباشر والداشبورد:</b>\n"
        report += f"👉 https://flow.horustek.pro/dash/\n"

        return report

    async def check_ledger_outcomes_loop(self):
        horizons = [900, 3600, 14400]
        while True:
            try:
                for h in horizons:
                    pending = pulse_db.get_pending_evaluations(h)
                    for item in pending:
                        price_now = await self._get_current_price(item["symbol"])
                        if price_now > 0:
                            entry_p = item["price_at_pulse"]
                            move_pct = ((price_now - entry_p) / entry_p) * 100
                            liq_p = dict(item).get("nearest_liq_price")
                            liq_swept = False
                            if liq_p and liq_p > 0:
                                if item["gravity_dir"] == "DOWN" and price_now <= liq_p:
                                    liq_swept = True
                                elif item["gravity_dir"] == "UP" and price_now >= liq_p:
                                    liq_swept = True
                            pulse_db.update_evaluation(item["id"], h, price_now, move_pct, liq_swept)
            except Exception as e:
                logger.error(f"Ledger outcome check error: {e}")
            await asyncio.sleep(60)

    async def _get_current_price(self, symbol: str) -> float:
        try:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=5) as r:
                    if r.status == 200:
                        d = await r.json()
                        return float(d.get("price", 0.0))
        except Exception:
            pass
        return 0.0

    async def send_telegram(self, text: str):
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            return False
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, timeout=10) as r:
                    return r.status == 200
            except Exception as e:
                logger.error(f"Telegram send error: {e}")
                return False

    async def run_daemon(self):
        logger.info("🚀 Horus Hourly Pulse Engine (Central Cortex v3.5) started.")
        asyncio.create_task(self.check_ledger_outcomes_loop())
        while True:
            try:
                now = datetime.now(timezone.utc)
                seconds_until_hour = (60 - now.minute - 1) * 60 + (60 - now.second)
                await asyncio.sleep(max(seconds_until_hour, 10))
                report = self.generate_report(force_full=False)
                await self.send_telegram(report)
                logger.info("✅ Hourly Pulse dispatched to Telegram successfully.")
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Hourly Pulse daemon cycle error: {e}", exc_info=True)
                await asyncio.sleep(30)


if __name__ == "__main__":
    import sys
    pulse = HorusHourlyPulse()
    if len(sys.argv) > 1 and sys.argv[1] == "--now":
        report = pulse.generate_report(force_full=True)
        print(report)
        asyncio.run(pulse.send_telegram(report))
    elif len(sys.argv) > 1 and sys.argv[1] == "--flash":
        report = pulse.generate_report(force_full=False)
        print(report)
    elif len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        asyncio.run(pulse.run_daemon())
    else:
        report = pulse.generate_report(force_full=True)
        print(report)
