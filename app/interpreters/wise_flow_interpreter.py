# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              المفسر الحكيم — WISE FLOW INTERPRETER v1.0                    ║
║              The Cognitive Layer Between Flow & Decision                    ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                            ║
║  PHILOSOPHY:                                                               ║
║    "العين ترى السيولة، لكن العقل وحده يفهم النية."                         ║
║    The eye sees liquidity, but only the mind understands intent.            ║
║                                                                            ║
║  PROBLEM SOLVED:                                                           ║
║    Raw HTA was killing 80/84 trades because it reacted to every            ║
║    micro-flow fluctuation. BTC PRESSURE was always on → DEFEND             ║
║    fired every tick → trades died in seconds.                              ║
║                                                                            ║
║  SOLUTION:                                                                 ║
║    This interpreter sits BETWEEN raw HTA data and Guardian decisions.      ║
║    It thinks like a human trader:                                          ║
║      1. Requires SUSTAINED signals (not single-tick panic)                 ║
║      2. Weighs CONTEXT (profit state, trade age, BTC trend)               ║
║      3. Differentiates NOISE from INTENT                                   ║
║      4. Issues calm, deliberate verdicts                                   ║
║                                                                            ║
║  ZERO I/O: Pure in-memory math. Fed by HTA's existing WS data.            ║
║  NO API CALLS: Reads only from HTA's internal calculators.                 ║
║                                                                            ║
║  VERDICTS:                                                                 ║
║    SAFE        — No threat detected, let trade breathe                     ║
║    CAUTIOUS    — Signals weakening, tighten stop (not exit)                ║
║    EVACUATE    — Confirmed collapse, recommend exit                        ║
║    RIDE        — Confirmed momentum, recommend TP extension                ║
║    TRAP        — Spoofing/fake support detected (pre-entry use)            ║
║                                                                            ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from collections import deque

logger = logging.getLogger("WiseInterpreter")


# ═══════════════════════════════════════════════════════════════
# 📊 DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════

class WiseVerdict(Enum):
    """الأحكام الخمسة للمفسر الحكيم"""
    SAFE = "SAFE"            # لا تهديد — اترك الصفقة تتنفس
    CAUTIOUS = "CAUTIOUS"    # إشارات ضعف — شد الوقف لا تخرج
    EVACUATE = "EVACUATE"    # انهيار مؤكد — اخرج الآن
    RIDE = "RIDE"            # زخم مؤكد — مدد الهدف
    TRAP = "TRAP"            # فخ سيولة — لا تدخل (للحضانة)


@dataclass
class WiseReading:
    """قراءة واحدة من المفسر الحكيم"""
    verdict: WiseVerdict
    confidence: float          # 0.0 - 1.0
    reason: str                # شرح بشري
    tighten_pct: float = 0.0   # نسبة شد الوقف (فقط مع CAUTIOUS)
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class FlowSnapshot:
    """لقطة مبسطة من حالة السيولة في لحظة معينة"""
    timestamp: float
    bid_ask_ratio: float       # نسبة الطلب/العرض
    buy_ratio: float           # نسبة الشراء العنيف (30 ثانية)
    delta_5s: float            # صافي الضغط (5 ثواني)
    delta_30s: float           # صافي الضغط (30 ثانية)
    bid_depth_change: float    # تغير عمق الطلبات (%)
    spread_pct: float          # فارق السعر (%)
    has_wall: bool             # هل يوجد جدار كبير
    wall_side: str             # أي جانب (BID/ASK/None)
    sell_spike: bool           # هل هناك موجة بيع عنيفة
    large_sell_count: int      # عدد الصفقات الكبيرة
    market_state: str          # NORMAL/PRESSURE/LIQUIDITY_EVENT
    imb_stability: float = 0.0 # استقرار عدم التوازن (كشف التلاعب)
    refill_ratio: float = 1.0  # نسبة إعادة ملء السيولة


# ═══════════════════════════════════════════════════════════════
# 🧠 THE WISE FLOW INTERPRETER
# ═══════════════════════════════════════════════════════════════

class WiseFlowInterpreter:
    """
    المفسر الحكيم — يحول بيانات السيولة اللحظية إلى قرارات حكيمة.
    
    القاعدة الذهبية:
      "لا تصرخ من أول شرارة. انتظر حتى ترى دخاناً مستمراً."
    
    المبادئ:
      1. التأكيد الزمني: أي إشارة تحتاج استمرارية (X ثوانٍ متتالية)
      2. الوعي بالسياق: مستوى الحساسية يتغير حسب حالة الربح
      3. فصل الغث عن السمين: ومضات لحظية = ضوضاء، اتجاه مستمر = نية
      4. الهدوء قبل العاصفة: لا يصدر حكم إخلاء إلا بثقة عالية
    """
    
    # ─── Confirmation Windows (ثوانٍ) ───
    # هذه هي "كوابح الهدوء" — كم يجب أن تستمر الإشارة لنصدقها
    EVACUATE_CONFIRM_SECONDS = 15   # 15 ثانية لتأكيد هروب السيولة (ضد الجدران الوهمية)
    CAUTIOUS_CONFIRM_SECONDS = 8    # 8 ثوانٍ ضعف مستمر = تحذير
    RIDE_CONFIRM_SECONDS = 6        # 6 ثوانٍ زخم مستمر = حقيقي
    TRAP_CONFIRM_SECONDS = 3        # 3 ثوانٍ تلاعب = كافي (للحضانة فقط)
    
    # ─── Thresholds ───
    # عتبات التفعيل — تم ضبطها لتصفية الضوضاء
    RATIO_HEALTHY = 0.8             # فوق هذا = الطلبات صحية
    RATIO_WEAK = 0.5                # تحت هذا = الطلبات ضعيفة
    RATIO_COLLAPSE = 0.3            # تحت هذا = انهيار حقيقي
    
    BUY_RATIO_STRONG = 0.65         # فوق هذا = شراء قوي
    BUY_RATIO_WEAK = 0.35           # تحت هذا = بيع مسيطر
    
    DEPTH_DROP_WARNING = -25.0      # هبوط بـ 25% = تحذير
    DEPTH_DROP_CRITICAL = -45.0     # هبوط بـ 45% = حرج
    
    STABILITY_SPOOF_THRESHOLD = 0.40  # تذبذب عالٍ = تلاعب محتمل
    REFILL_TRAP_THRESHOLD = 2.5       # إعادة ملء مفاجئة = مصيدة صانع سوق
    
    # ─── History ───
    HISTORY_SIZE = 60  # نحتفظ بآخر 60 لقطة (~60 ثانية)
    
    def __init__(self):
        # تاريخ اللقطات لكل عملة
        self._history: Dict[str, deque] = {}
        
        # حالة التأكيد: متى بدأ كل نمط
        self._pattern_start: Dict[str, Dict[str, float]] = {}
        # pattern_start[symbol] = {
        #   "evacuate": timestamp_when_collapse_started,
        #   "cautious": timestamp_when_weakness_started,
        #   "ride": timestamp_when_momentum_started,
        #   "trap": timestamp_when_spoofing_started,
        # }
        
        # آخر حكم صدر لكل عملة (لمنع التكرار)
        self._last_verdict: Dict[str, WiseVerdict] = {}
        self._last_verdict_time: Dict[str, float] = {}
        
        # Cooldown: لا تُصدر نفس الحكم مرتين خلال X ثوانٍ
        self._verdict_cooldown = 15  # 15 ثانية بين الأحكام المتماثلة
        
        logger.info("🧠 المفسر الحكيم (WiseFlowInterpreter v1.0) جاهز")
    
    # ═══════════════════════════════════════════════════════════
    # 📥 FEED: تلقي بيانات السيولة من الـ HTA
    # ═══════════════════════════════════════════════════════════
    
    def feed(self, symbol: str, imbalance: Optional[Dict], flow: Optional[Dict], 
             market_state: str = "NORMAL"):
        """
        يتلقى بيانات السيولة من الـ HTA ويخزنها كلقطة.
        
        يُستدعى من handle_tick_unified() في كل tick.
        لا يصدر أحكام هنا — فقط يسجل.
        
        Args:
            symbol: مثال "BTC/USDT"
            imbalance: ناتج ImbalanceCalculator.get_imbalance()
            flow: ناتج FlowDetector.get_delta()
            market_state: "NORMAL" / "PRESSURE" / "LIQUIDITY_EVENT"
        """
        if not imbalance or not flow:
            return
        
        snapshot = FlowSnapshot(
            timestamp=time.time(),
            bid_ask_ratio=imbalance.get("avg_ratio", 1.0),
            buy_ratio=flow.get("buy_ratio", 0.5),
            delta_5s=flow.get("delta_5s", 0.0),
            delta_30s=flow.get("delta_30s", 0.0),
            bid_depth_change=imbalance.get("bid_depth_change_pct", 0.0),
            spread_pct=imbalance.get("spread_pct", 0.0),
            has_wall=imbalance.get("wall_side") is not None,
            wall_side=imbalance.get("wall_side", ""),
            sell_spike=flow.get("sell_spike", False),
            large_sell_count=flow.get("large_sell_count", 0),
            market_state=market_state,
            imb_stability=imbalance.get("imb_stability", 0.0),
            refill_ratio=imbalance.get("refill_ratio", 1.0),
        )
        
        if symbol not in self._history:
            self._history[symbol] = deque(maxlen=self.HISTORY_SIZE)
        self._history[symbol].append(snapshot)
    
    # ═══════════════════════════════════════════════════════════
    # ⚖️ INTERPRET: إصدار حكم حكيم (للصفقات النشطة)
    # ═══════════════════════════════════════════════════════════
    
    def interpret_active_trade(self, symbol: str, profit_pct: float = 0.0,
                                trade_age_minutes: float = 0.0) -> WiseReading:
        """
        يفسر حالة السيولة لصفقة مفتوحة.
        
        القرار مختلف حسب:
          - هل الصفقة في خسارة أم ربح؟
          - هل مر وقت كافٍ للحكم؟
          - هل الإشارة مستمرة أم مجرد ومضة؟
        
        Args:
            symbol: مثال "SOL/USDT"
            profit_pct: نسبة الربح الحالية (مثال: 2.5 أو -1.0)
            trade_age_minutes: عمر الصفقة بالدقائق
            
        Returns:
            WiseReading مع الحكم والثقة والسبب
        """
        now = time.time()
        
        # ── لا توجد بيانات كافية ──
        if symbol not in self._history or len(self._history[symbol]) < 5:
            return WiseReading(
                verdict=WiseVerdict.SAFE,
                confidence=0.0,
                reason="بيانات غير كافية — ندع الصفقة تتنفس"
            )
        
        snapshots = list(self._history[symbol])
        recent = snapshots[-5:]  # آخر 5 لقطات
        
        # ══════════════════════════════════════
        # 🔴 فحص الإخلاء (EVACUATE)
        # ══════════════════════════════════════
        evacuate_score = self._calc_evacuate_score(recent, profit_pct)
        
        if evacuate_score >= 0.6:
            # بدأ نمط الانهيار — هل مستمر بما يكفي؟
            if self._confirm_pattern(symbol, "evacuate", self.EVACUATE_CONFIRM_SECONDS, now):
                if not self._in_cooldown(symbol, WiseVerdict.EVACUATE, now):
                    self._record_verdict(symbol, WiseVerdict.EVACUATE, now)
                    return WiseReading(
                        verdict=WiseVerdict.EVACUATE,
                        confidence=min(evacuate_score, 1.0),
                        reason=self._describe_evacuate(recent, profit_pct)
                    )
        else:
            self._clear_pattern(symbol, "evacuate")
        
        # ══════════════════════════════════════
        # 🟡 فحص الحذر (CAUTIOUS)
        # ══════════════════════════════════════
        cautious_score = self._calc_cautious_score(recent, profit_pct)
        
        if cautious_score >= 0.5:
            if self._confirm_pattern(symbol, "cautious", self.CAUTIOUS_CONFIRM_SECONDS, now):
                if not self._in_cooldown(symbol, WiseVerdict.CAUTIOUS, now):
                    tighten = self._calc_tighten_pct(cautious_score, profit_pct)
                    self._record_verdict(symbol, WiseVerdict.CAUTIOUS, now)
                    return WiseReading(
                        verdict=WiseVerdict.CAUTIOUS,
                        confidence=min(cautious_score, 1.0),
                        reason=self._describe_cautious(recent),
                        tighten_pct=tighten
                    )
        else:
            self._clear_pattern(symbol, "cautious")
        
        # ══════════════════════════════════════
        # 🟢 فحص الركوب (RIDE)
        # ══════════════════════════════════════
        if profit_pct > 0.5:  # فقط لو الصفقة رابحة
            ride_score = self._calc_ride_score(recent)
            
            if ride_score >= 0.6:
                if self._confirm_pattern(symbol, "ride", self.RIDE_CONFIRM_SECONDS, now):
                    if not self._in_cooldown(symbol, WiseVerdict.RIDE, now):
                        self._record_verdict(symbol, WiseVerdict.RIDE, now)
                        return WiseReading(
                            verdict=WiseVerdict.RIDE,
                            confidence=min(ride_score, 1.0),
                            reason=self._describe_ride(recent)
                        )
            else:
                self._clear_pattern(symbol, "ride")
        
        # ══════════════════════════════════════
        # 🟢 الوضع آمن
        # ══════════════════════════════════════
        return WiseReading(
            verdict=WiseVerdict.SAFE,
            confidence=0.5,
            reason="لا تهديد — الصفقة تتنفس بشكل طبيعي"
        )
    
    # ═══════════════════════════════════════════════════════════
    # 🏗️ INTERPRET: إصدار حكم للحضانة (قبل الدخول)
    # ═══════════════════════════════════════════════════════════
    
    def interpret_pre_entry(self, symbol: str) -> WiseReading:
        """
        يفسر حالة السيولة قبل دخول صفقة جديدة.
        
        هنا الحساسية أعلى — أي شك = رفض.
        "الشك يُفسر لصالح الرفض"
        
        Args:
            symbol: العملة المراد فحصها
            
        Returns:
            WiseReading — TRAP (ارفض) أو SAFE (ادخل) أو RIDE (ادخل بثقة)
        """
        now = time.time()
        
        if symbol not in self._history or len(self._history[symbol]) < 3:
            return WiseReading(
                verdict=WiseVerdict.SAFE,
                confidence=0.3,
                reason="بيانات غير كافية — ادخل بحذر"
            )
        
        snapshots = list(self._history[symbol])
        recent = snapshots[-5:] if len(snapshots) >= 5 else snapshots
        
        # ── فحص الفخاخ ──
        trap_score = self._calc_trap_score(recent)
        
        if trap_score >= 0.5:
            if self._confirm_pattern(symbol, "trap", self.TRAP_CONFIRM_SECONDS, now):
                return WiseReading(
                    verdict=WiseVerdict.TRAP,
                    confidence=min(trap_score, 1.0),
                    reason=self._describe_trap(recent)
                )
        else:
            self._clear_pattern(symbol, "trap")
        
        # ── فحص الضغط البيعي المباشر ──
        avg_buy_ratio = sum(s.buy_ratio for s in recent) / len(recent)
        avg_ratio = sum(s.bid_ask_ratio for s in recent) / len(recent)
        
        if avg_buy_ratio < self.BUY_RATIO_WEAK and avg_ratio < self.RATIO_WEAK:
            return WiseReading(
                verdict=WiseVerdict.TRAP,
                confidence=0.7,
                reason=f"ضغط بيع مستمر: buy_ratio={avg_buy_ratio:.2f}, bid/ask={avg_ratio:.2f}"
            )
        
        # ── فحص الزخم الإيجابي ──
        if avg_buy_ratio > self.BUY_RATIO_STRONG and avg_ratio > 1.5:
            return WiseReading(
                verdict=WiseVerdict.RIDE,
                confidence=0.7,
                reason=f"زخم شرائي قوي: buy_ratio={avg_buy_ratio:.2f}, bid/ask={avg_ratio:.2f}"
            )
        
        return WiseReading(
            verdict=WiseVerdict.SAFE,
            confidence=0.5,
            reason="السيولة محايدة — ادخل بحجم عادي"
        )
    
    # ═══════════════════════════════════════════════════════════
    # 🔬 SCORING ENGINES
    # ═══════════════════════════════════════════════════════════
    
    def _calc_evacuate_score(self, recent: List[FlowSnapshot], profit_pct: float) -> float:
        """
        حساب درجة الإخلاء — يحتاج توافق عدة مؤشرات.
        
        مبدأ "الفيتو المزدوج":
          لا نهرب بناءً على مؤشر واحد.
          الانهيار الحقيقي = تراجع الطلبات + بيع عنيف + انتشار السبريد
        """
        score = 0.0
        n = len(recent)
        
        # حماية من التلاعب (Spoofing Filter)
        # إذا كان دفتر الأوامر يتذبذب بعنف (تلاعب لحظي)، نقلل وزن الدفتر
        avg_stability = sum(s.imb_stability for s in recent) / n
        is_spoofing = avg_stability > self.STABILITY_SPOOF_THRESHOLD
        
        # 1. نسبة الطلب/العرض (sustained collapse)
        avg_ratio = sum(s.bid_ask_ratio for s in recent) / n
        if not is_spoofing:
            if avg_ratio < self.RATIO_COLLAPSE:
                score += 0.35
            elif avg_ratio < self.RATIO_WEAK:
                score += 0.15
        else:
            # تجاهل الدفتر أو أعطه وزناً طفيفاً جداً وقت التلاعب
            if avg_ratio < self.RATIO_COLLAPSE:
                score += 0.10
                
        # 2. نسبة الشراء العنيف (sellers dominating) - The core truth
        avg_buy = sum(s.buy_ratio for s in recent) / n
        if avg_buy < 0.30:
            score += 0.35  # زاد وزنه لأنه المؤشر الحقيقي
        elif avg_buy < 0.40:  # Sell Flow المتسارع
            score += 0.25
        elif avg_buy < 0.45:
            score += 0.15
            
        # الفيتو المزدوج: إذا كان هناك جدار وهمي (انهيار في النسبة) ولكن لا يوجد بيع حقيقي، لا تخرج!
        if avg_ratio < self.RATIO_WEAK and avg_buy >= 0.45:
            score -= 0.20  # عقاب لمنع الخروج بسبب جدار وهمي
            
        # 3. عمق الطلبات (depth collapse)
        avg_depth = sum(s.bid_depth_change for s in recent) / n
        if avg_depth < self.DEPTH_DROP_CRITICAL:
            score += 0.20
        elif avg_depth < self.DEPTH_DROP_WARNING:
            score += 0.10
        
        # 4. موجة بيع عنيفة (sell spike)
        sell_spikes = sum(1 for s in recent if s.sell_spike)
        if sell_spikes >= 3:
            score += 0.15
            
        # 5. نزيف السيولة (Sustained Bleeding Logic)
        # إذا كانت الصفقة خاسرة وتتعرض لتصريف مستمر
        if profit_pct < 0 and avg_buy < 0.45 and avg_ratio < 0.8:
            score += 0.30  # منقذ رأس المال
        
        # 6. حالة السوق العالمية (BTC Layer 2)
        if recent[-1].market_state == "LIQUIDITY_EVENT":
            score += 0.20
        elif recent[-1].market_state == "PRESSURE":
            score += 0.05
        
        # ── تعديل حسب الربح ──
        if profit_pct > 2.0:
            score *= 1.20  # أكثر حساسية لحماية الأرباح من التصريف
        elif profit_pct < -1.0:
            score *= 1.10  # أكثر حساسية لإنقاذ ما يمكن إنقاذه
        
        return min(max(score, 0.0), 1.0)
    
    def _calc_cautious_score(self, recent: List[FlowSnapshot], profit_pct: float) -> float:
        """حساب درجة الحذر — إشارات ضعف لكن ليست انهيار"""
        score = 0.0
        n = len(recent)
        
        avg_ratio = sum(s.bid_ask_ratio for s in recent) / n
        avg_buy = sum(s.buy_ratio for s in recent) / n
        
        # ضعف مع ان الطلبات ليست منهارة
        if self.RATIO_WEAK <= avg_ratio < self.RATIO_HEALTHY:
            score += 0.25
        
        if self.BUY_RATIO_WEAK <= avg_buy < 0.45:
            score += 0.20
        
        # السبريد يتسع قليلاً
        avg_spread = sum(s.spread_pct for s in recent) / n
        if avg_spread > 0.08:
            score += 0.15
        
        # BTC تحت ضغط (خفيف)
        if recent[-1].market_state == "PRESSURE":
            score += 0.15
        
        # الدلتا تتراجع (مشترون يتراجعون)
        if len(recent) >= 3:
            deltas = [s.delta_30s for s in recent[-3:]]
            if all(d < 0 for d in deltas):
                score += 0.20
        
        # تعديل حسب الربح
        if profit_pct > 3.0:
            score *= 1.2  # حماية الأرباح أهم
        
        return min(score, 1.0)
    
    def _calc_ride_score(self, recent: List[FlowSnapshot]) -> float:
        """حساب درجة الركوب — زخم شرائي حقيقي ومستمر"""
        score = 0.0
        n = len(recent)
        
        avg_ratio = sum(s.bid_ask_ratio for s in recent) / n
        avg_buy = sum(s.buy_ratio for s in recent) / n
        
        # طلبات قوية
        if avg_ratio > 1.8:
            score += 0.30
        elif avg_ratio > 1.3:
            score += 0.15
        
        # شراء عنيف مستمر
        if avg_buy > self.BUY_RATIO_STRONG:
            score += 0.25
        
        # الدلتا إيجابية ومتسارعة
        if len(recent) >= 3:
            deltas = [s.delta_30s for s in recent[-3:]]
            if all(d > 0 for d in deltas):
                score += 0.20
                # متسارعة
                if deltas[-1] > deltas[0] * 1.5:
                    score += 0.15
        
        # لا يوجد تلاعب
        avg_stability = sum(s.imb_stability for s in recent) / n
        if avg_stability < 0.20:
            score += 0.10  # سيولة مستقرة = حقيقية
        
        return min(score, 1.0)
    
    def _calc_trap_score(self, recent: List[FlowSnapshot]) -> float:
        """حساب درجة الفخ — تلاعب وجدران وهمية"""
        score = 0.0
        n = len(recent)
        
        # 1. عدم استقرار عالي = تلاعب (spoof cycling)
        avg_stability = sum(s.imb_stability for s in recent) / n
        if avg_stability > self.STABILITY_SPOOF_THRESHOLD:
            score += 0.35
        
        # 2. إعادة ملء مفاجئة = مصيدة صانع سوق
        avg_refill = sum(s.refill_ratio for s in recent) / n
        if avg_refill > self.REFILL_TRAP_THRESHOLD:
            score += 0.30
        
        # 3. جدار شرائي ضخم + بيع عنيف خلفه = Spoofing
        has_bid_wall = any(s.wall_side == "BID" for s in recent)
        avg_buy = sum(s.buy_ratio for s in recent) / n
        if has_bid_wall and avg_buy < 0.45:
            score += 0.30  # جدار وهمي — يبدو دعم لكن البيع مسيطر
        
        # 4. جدار بيع = مقاومة حقيقية
        has_ask_wall = any(s.wall_side == "ASK" for s in recent)
        if has_ask_wall and avg_buy < 0.50:
            score += 0.20
        
        return min(score, 1.0)
    
    # ═══════════════════════════════════════════════════════════
    # ⏱️ CONFIRMATION SYSTEM (كوابح الهدوء)
    # ═══════════════════════════════════════════════════════════
    
    def _confirm_pattern(self, symbol: str, pattern: str, 
                         required_seconds: float, now: float) -> bool:
        """
        هل النمط مستمر لفترة كافية؟
        
        الفلسفة: "الومضة ليست حريقاً."
        أول ظهور للنمط = نسجله.
        إذا استمر >= required_seconds = نصدقه.
        """
        if symbol not in self._pattern_start:
            self._pattern_start[symbol] = {}
        
        patterns = self._pattern_start[symbol]
        
        if pattern not in patterns:
            # أول ظهور — سجل وانتظر
            patterns[pattern] = now
            return False
        
        elapsed = now - patterns[pattern]
        return elapsed >= required_seconds
    
    def _clear_pattern(self, symbol: str, pattern: str):
        """النمط اختفى — أعد العداد"""
        if symbol in self._pattern_start:
            self._pattern_start[symbol].pop(pattern, None)
    
    def _in_cooldown(self, symbol: str, verdict: WiseVerdict, now: float) -> bool:
        """هل أصدرنا نفس الحكم مؤخراً؟"""
        key = f"{symbol}_{verdict.value}"
        last_time = self._last_verdict_time.get(key, 0)
        return (now - last_time) < self._verdict_cooldown
    
    def _record_verdict(self, symbol: str, verdict: WiseVerdict, now: float):
        """سجل الحكم الأخير"""
        key = f"{symbol}_{verdict.value}"
        self._last_verdict[symbol] = verdict
        self._last_verdict_time[key] = now
    
    # ═══════════════════════════════════════════════════════════
    # 🗣️ DESCRIPTIONS (شروح بشرية)
    # ═══════════════════════════════════════════════════════════
    
    def _describe_evacuate(self, recent: List[FlowSnapshot], profit_pct: float) -> str:
        n = len(recent)
        avg_ratio = sum(s.bid_ask_ratio for s in recent) / n
        avg_buy = sum(s.buy_ratio for s in recent) / n
        
        parts = []
        if avg_buy < 0.45 and profit_pct < 0:
            parts.append(f"نزيف سيولة مستمر ({self.EVACUATE_CONFIRM_SECONDS}ث+)")
        else:
            parts.append(f"انهيار سيولة مؤكد ({self.EVACUATE_CONFIRM_SECONDS}ث+)")
            
        parts.append(f"bid/ask={avg_ratio:.2f}")
        parts.append(f"buy_ratio={avg_buy:.2f}")
        if recent[-1].market_state != "NORMAL":
            parts.append(f"BTC={recent[-1].market_state}")
        if profit_pct > 0:
            parts.append(f"⚠️ حماية ربح +{profit_pct:.1f}%")
        elif profit_pct < 0:
            parts.append(f"🛡️ وقف نزيف {profit_pct:.1f}%")
        return " | ".join(parts)
    
    def _describe_cautious(self, recent: List[FlowSnapshot]) -> str:
        n = len(recent)
        avg_ratio = sum(s.bid_ask_ratio for s in recent) / n
        avg_buy = sum(s.buy_ratio for s in recent) / n
        return (f"ضعف مستمر ({self.CAUTIOUS_CONFIRM_SECONDS}ث+): "
                f"bid/ask={avg_ratio:.2f}, buy_ratio={avg_buy:.2f}")
    
    def _describe_ride(self, recent: List[FlowSnapshot]) -> str:
        n = len(recent)
        avg_ratio = sum(s.bid_ask_ratio for s in recent) / n
        avg_buy = sum(s.buy_ratio for s in recent) / n
        return (f"زخم شرائي مؤكد ({self.RIDE_CONFIRM_SECONDS}ث+): "
                f"bid/ask={avg_ratio:.2f}, buy_ratio={avg_buy:.2f}")
    
    def _describe_trap(self, recent: List[FlowSnapshot]) -> str:
        n = len(recent)
        avg_stab = sum(s.imb_stability for s in recent) / n
        parts = ["فخ سيولة مرصود"]
        if avg_stab > self.STABILITY_SPOOF_THRESHOLD:
            parts.append(f"تلاعب(stability={avg_stab:.2f})")
        bid_walls = sum(1 for s in recent if s.wall_side == "BID")
        if bid_walls > 0:
            avg_buy = sum(s.buy_ratio for s in recent) / n
            parts.append(f"جدار وهمي({bid_walls}x, buy={avg_buy:.2f})")
        return " | ".join(parts)

    def _calc_tighten_pct(self, cautious_score: float, profit_pct: float) -> float:
        """
        حساب نسبة شد الوقف المناسبة.
        
        المنطق:
          - كلما زاد الخطر (cautious_score) → شد أكثر
          - كلما زاد الربح → حماية أكثر
          - الحد الأقصى لن يتجاوز 30% من المسافة الحالية
        """
        base = cautious_score * 0.15  # أقصى 15% من المسافة
        
        if profit_pct > 5.0:
            base *= 1.5  # حماية ربح كبير
        elif profit_pct > 2.0:
            base *= 1.2
        
        return min(base, 0.30)  # لا تتجاوز 30%
    
    # ═══════════════════════════════════════════════════════════
    # 📊 STATUS (للتشخيص)
    # ═══════════════════════════════════════════════════════════
    
    def get_status(self, symbol: str) -> Dict:
        """حالة المفسر لعملة معينة"""
        if symbol not in self._history:
            return {"symbol": symbol, "data": False}
        
        snapshots = list(self._history[symbol])
        if not snapshots:
            return {"symbol": symbol, "data": False}
        
        recent = snapshots[-5:] if len(snapshots) >= 5 else snapshots
        n = len(recent)
        
        return {
            "symbol": symbol,
            "snapshots": len(snapshots),
            "avg_bid_ask_ratio": round(sum(s.bid_ask_ratio for s in recent) / n, 3),
            "avg_buy_ratio": round(sum(s.buy_ratio for s in recent) / n, 3),
            "avg_depth_change": round(sum(s.bid_depth_change for s in recent) / n, 1),
            "market_state": recent[-1].market_state,
            "pending_patterns": self._pattern_start.get(symbol, {}),
            "last_verdict": self._last_verdict.get(symbol, "NONE"),
        }


# ═══════════════════════════════════════════════════════════
# 🏭 SINGLETON
# ═══════════════════════════════════════════════════════════

_interpreter_instance: Optional[WiseFlowInterpreter] = None

def get_wise_interpreter() -> WiseFlowInterpreter:
    """الحصول على نسخة المفسر الحكيم (Singleton)"""
    global _interpreter_instance
    if _interpreter_instance is None:
        _interpreter_instance = WiseFlowInterpreter()
    return _interpreter_instance
