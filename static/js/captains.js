/**
 * Horus Intel - Commander's Hub (Captains Dashboard)
 */

let pollingInterval = null;
const HEARTBEAT_INTERVAL = 15000; // 15 seconds balance

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('btn-cmd-track').addEventListener('click', () => {
        const symbol = document.getElementById('cmd-track-input').value.trim().toUpperCase();
        const type = document.getElementById('cmd-track-type').value;
        if (symbol) {
            startRadar(symbol, type);
        }
    });

    document.getElementById('cmd-track-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') document.getElementById('btn-cmd-track').click();
    });
});

function startRadar(symbol, type) {
    if (pollingInterval) clearInterval(pollingInterval);
    
    document.getElementById('radar-container').style.display = 'block';
    document.getElementById('display-symbol').innerText = symbol;
    const sigEl = document.getElementById('display-signal');
    sigEl.innerText = "ANALYZING TAPE...";
    sigEl.style.color = "var(--gold)";
    sigEl.style.textShadow = "0 0 5px rgba(255,179,0,0.3)";
    const scanLabel = document.getElementById('scan-label');
    if(scanLabel) scanLabel.innerText = "Scanning L2 Orderbook Physics...";
    
    // Initialize TradingView
    initCaptainTV(symbol, type);
    
    const execute = async () => {
        const apiKey = document.getElementById('rapid-key').value || 'horus-demo-key-2026';
        const endpoint = `/v1/flow/${type}/${symbol}?key=${apiKey}`;

        try {
            const res = await fetch(endpoint);
            const data = await res.json();
            
            // Also fetch Jury theses data
            const accuracyRes = await fetch(`/v1/flow/theses`);
            let accuracyData = null;
            if (accuracyRes.ok) {
                accuracyData = await accuracyRes.json();
            }
            
            if (res.ok) {
                updateRadar(data);
                if (accuracyData) {
                    updateScoreboard(accuracyData);
                }
            } else {
                showOffline(data.detail || 'Feed unavailable');
            }
        } catch (e) {
            console.error(`Radar Error:`, e);
        }
    };

    // Run immediately
    execute();
    
    // Then every 15 seconds
    pollingInterval = setInterval(execute, HEARTBEAT_INTERVAL);
}

function showOffline(msg) {
    document.getElementById('display-signal').innerText = "OFFLINE";
    document.getElementById('display-signal').style.color = "var(--neon-red)";
    
    document.getElementById('intent-score').innerText = "--";
    document.getElementById('intent-progress').style.width = "0%";
    
    document.getElementById('toxicity-score').innerText = "0%";
    document.getElementById('toxicity-gauge').setAttribute('stroke-dasharray', '0 125.6');
    document.getElementById('toxicity-label').innerText = "OFFLINE";
    
    document.getElementById('abs-bid').style.width = "50%";
    document.getElementById('abs-ask').style.width = "50%";
    document.getElementById('lbl-bid').innerText = "0%";
    document.getElementById('lbl-ask').innerText = "0%";
    document.getElementById('abs-verdict').innerText = "NO LIQUIDITY";
}

function updateRadar(data) {
    const signal = data.signal || 'NEUTRAL';
    const sigEl = document.getElementById('display-signal');
    const fBox = document.getElementById('foresight-verdict');
    const fDesc = document.getElementById('foresight-desc');
    const pDot = document.getElementById('pulse-dot');
    
    // Set AI Voice Description
    if (data.description) {
        fBox.style.display = 'block';
        fDesc.innerText = data.description;
    } else {
        fBox.style.display = 'none';
    }

    // Default pulse and animation
    sigEl.style.animation = "none";
    pDot.style.background = "#ffb300";

    if (signal === 'IMMINENT_DUMP_5M') {
        sigEl.innerText = "[ 5M DUMP IMMINENT ]";
        sigEl.style.color = "var(--neon-red)";
        sigEl.style.textShadow = "0 0 10px rgba(239, 68, 68, 0.4)";
        pDot.style.background = "var(--neon-red)";
        fBox.className = "foresight-box danger";
    } else if (signal === 'IMMINENT_PUMP_5M') {
        sigEl.innerText = "[ 5M PUMP IMMINENT ]";
        sigEl.style.color = "var(--neon-green)";
        sigEl.style.textShadow = "0 0 10px rgba(34, 197, 94, 0.4)";
        pDot.style.background = "var(--neon-green)";
        fBox.className = "foresight-box pump";
    } else {
        sigEl.innerText = signal;
        if (signal.includes('EXIT') || signal.includes('SELL') || signal.includes('DUMP')) {
            sigEl.style.color = "var(--neon-red)";
            sigEl.style.textShadow = "0 0 5px rgba(239, 68, 68, 0.4)";
        } else if (signal.includes('BUY') || signal.includes('PUMP')) {
            sigEl.style.color = "var(--neon-green)";
            sigEl.style.textShadow = "0 0 5px rgba(34, 197, 94, 0.4)";
        } else {
            sigEl.style.color = "var(--text-pure)";
            sigEl.style.textShadow = "none";
        }
        fBox.className = "foresight-box";
    }

    const m = data.metrics || {};

    // 1. Whale Intent (Confidence)
    const score = Math.round((data.confidence || 0) * 100);
    const scoreEl = document.getElementById('intent-score');
    const progEl = document.getElementById('intent-progress');
    const labelEl = document.getElementById('intent-label');
    const flowEl = document.getElementById('intent-flow');
    
    scoreEl.innerText = score + '%';
    progEl.style.width = score + '%';
    
    if (signal.includes('BUY') || signal.includes('PUMP')) {
        labelEl.innerText = "BULLISH";
        labelEl.style.color = 'var(--neon-green)';
        labelEl.style.textShadow = '0 0 15px rgba(0, 255, 157, 0.3)';
        progEl.style.background = 'var(--neon-green)';
        progEl.style.boxShadow = '0 0 10px var(--neon-green)';
        flowEl.innerText = "Bid Dominated";
    } else if (signal.includes('SELL') || signal.includes('DUMP') || signal.includes('EXIT')) {
        labelEl.innerText = "BEARISH";
        labelEl.style.color = 'var(--neon-red)';
        labelEl.style.textShadow = '0 0 15px rgba(255, 51, 102, 0.3)';
        progEl.style.background = 'var(--neon-red)';
        progEl.style.boxShadow = '0 0 10px var(--neon-red)';
        flowEl.innerText = "Ask Dominated";
    } else {
        labelEl.innerText = "NEUTRAL";
        labelEl.style.color = 'var(--gold)';
        labelEl.style.textShadow = '0 0 15px rgba(255, 179, 0, 0.3)';
        progEl.style.background = 'var(--gold)';
        progEl.style.boxShadow = '0 0 10px var(--gold)';
        flowEl.innerText = "Accumulation";
    }

    // 2. Trap Detector -> Toxicity Index
    let isTrap = false;
    let trapMessage = "";
    let trapDetail = "";

    // Trap Condition A: Bear Trap
    if (signal.includes('SELL') && m.wall_side === 'BID' && m.bid_ask_ratio > 1.5) {
        isTrap = true;
        trapMessage = "BEAR TRAP";
        trapDetail = "Retail selling, Whales absorbing.";
    }
    // Trap Condition B: Bull Trap
    else if (signal.includes('BUY') && m.delta_accel < -1.0) {
        isTrap = true;
        trapMessage = "BULL TRAP";
        trapDetail = "Price rising, Whales dumping.";
    }
    // Trap Condition C: Whale Dump
    else if (m.flags && m.flags.includes('WHALE_DUMP_DETECTED')) {
        isTrap = true;
        trapMessage = "WHALE DUMP";
        trapDetail = "Massive institutional unloading.";
    }

    // Calculate Toxicity (0 to 100)
    let toxicityScore = 0;
    if (isTrap) {
        toxicityScore = Math.floor(Math.random() * 20) + 80; // 80-100%
    } else {
        toxicityScore = Math.min(Math.floor(Math.abs(m.delta_accel || 0) * 10), 40); // 0-40%
    }

    const toxGauge = document.getElementById('toxicity-gauge');
    const toxScoreEl = document.getElementById('toxicity-score');
    const toxLabel = document.getElementById('toxicity-label');
    const toxTrend = document.getElementById('toxicity-trend');
    const trapDesc = document.getElementById('trap-desc');

    toxScoreEl.innerText = toxicityScore + '%';
    
    // SVG Arc max length is 125.6
    const dashLength = (toxicityScore / 100) * 125.6;
    toxGauge.setAttribute('stroke-dasharray', `${dashLength} 125.6`);

    if (toxicityScore > 75) {
        toxLabel.innerText = "HIGH ALERT";
        toxLabel.style.color = "var(--neon-red)";
        toxGauge.style.stroke = "var(--neon-red)";
        toxTrend.innerText = "↑ " + trapMessage;
        toxTrend.style.color = "var(--neon-red)";
        trapDesc.innerText = trapDetail;
    } else if (toxicityScore > 40) {
        toxLabel.innerText = "ELEVATED";
        toxLabel.style.color = "var(--gold)";
        toxGauge.style.stroke = "var(--gold)";
        toxTrend.innerText = "→ Warning";
        toxTrend.style.color = "var(--gold)";
        trapDesc.innerText = "Unusual flows detected.";
    } else {
        toxLabel.innerText = "SAFE";
        toxLabel.style.color = "var(--neon-green)";
        toxGauge.style.stroke = "var(--neon-green)";
        toxTrend.innerText = "↓ Normal";
        toxTrend.style.color = "var(--neon-green)";
        trapDesc.innerText = "LOB Stable";
    }

    // 3. Live Absorption Scale
    const ratio = m.bid_ask_ratio || 1.0;
    // Calculate percentage (e.g. ratio 2.0 -> 2/3 bid = 66.6%)
    const bidPct = Math.round((ratio / (ratio + 1)) * 100);
    const askPct = 100 - bidPct;

    document.getElementById('abs-bid').style.width = bidPct + "%";
    document.getElementById('abs-ask').style.width = askPct + "%";
    document.getElementById('lbl-bid').innerText = bidPct + "%";
    document.getElementById('lbl-ask').innerText = askPct + "%";

    const verdict = document.getElementById('abs-verdict');
    if (m.wall_side === 'BID') {
        verdict.innerText = "[ MASSIVE BID WALL / STRONG SUPPORT ]";
        verdict.style.color = "#10b981";
    } else if (m.wall_side === 'ASK') {
        verdict.innerText = "[ MASSIVE ASK WALL / STRONG RESISTANCE ]";
        verdict.style.color = "#f43f5e";
    } else {
        if (bidPct > 60) {
            verdict.innerText = "BIDS CONTROLLING THE BOOK";
            verdict.style.color = "#34c759";
        } else if (askPct > 60) {
            verdict.innerText = "SELLERS CONTROLLING THE BOOK";
            verdict.style.color = "#ff3b30";
        } else {
            verdict.innerText = "EQUAL PRESSURE / RANGING";
            verdict.style.color = "#a0a0b0";
        }
    }
}

function initCaptainTV(symbol, type) {
    let tvSymbol = "BINANCE:" + symbol;
    if (type === 'equity') {
        tvSymbol = "NASDAQ:" + symbol;
    }

    new TradingView.widget({
        "autosize": true,
        "symbol": tvSymbol,
        "interval": "1", // 1 minute interval as requested
        "timezone": "Etc/UTC",
        "theme": "dark",
        "style": "1",
        "locale": "en",
        "toolbar_bg": "#111113",
        "enable_publishing": false,
        "hide_top_toolbar": false, // Show toolbar so they can see timeframe
        "hide_legend": false,
        "save_image": false,
        "container_id": "tv_chart_container",
        "backgroundColor": "#111113",
        "gridColor": "#1a1a1a"
    });
}

function updateScoreboard(accData) {
    const activeContainer = document.getElementById('active-locks-container');
    const resolvedContainer = document.getElementById('resolved-locks-container');
    // Trust the backend stats directly — no frontend override
    if (accData && accData.stats) {
        const total = accData.stats.wins + accData.stats.losses + accData.stats.draws;
        const total_win_loss = accData.stats.wins + accData.stats.losses;
        const wr = total_win_loss > 0 ? Math.round((accData.stats.wins / total_win_loss) * 100) : 0;
        
        let color = 'var(--text-dim)';
        if (wr > 50 && total_win_loss > 0) color = 'var(--neon-green)';
        else if (wr < 50 && total_win_loss > 0) color = 'var(--neon-red)';
        else if (total_win_loss > 0) color = 'var(--gold)';
        
        const wrText = document.getElementById('winrate-text');
        if (wrText) {
            wrText.style.color = color;
            wrText.style.textShadow = `0 0 10px ${color}`;
            wrText.innerText = `${wr}%`;
        }

        // Animate the stacked bar
        const barW = document.getElementById('bar-wins');
        const barD = document.getElementById('bar-draws');
        const barL = document.getElementById('bar-losses');
        
        if (barW && barD && barL && total > 0) {
            const pctW = (accData.stats.wins / total) * 100;
            const pctD = (accData.stats.draws / total) * 100;
            const pctL = (accData.stats.losses / total) * 100;
            
            barW.style.width = `${pctW}%`;
            barD.style.width = `${pctD}%`;
            barL.style.width = `${pctL}%`;
        }

        // Update the count texts
        const statW = document.getElementById('stat-w');
        const statD = document.getElementById('stat-d');
        const statL = document.getElementById('stat-l');
        
        if (statW) statW.innerText = accData.stats.wins;
        if (statD) statD.innerText = accData.stats.draws;
        if (statL) statL.innerText = accData.stats.losses;
    }
    
    // Render Active Locks
    if (accData.active_theses && accData.active_theses.length > 0) {
        let activeHtml = '';
        
        const sortedActive = accData.active_theses.sort((a, b) => b.opened_at - a.opened_at);
        
        sortedActive.forEach(p => {
            const ageMins = Math.floor(p.age_seconds / 60);
            const ageSecsRem = p.age_seconds % 60;
            const ageStr = `${ageMins}:${ageSecsRem.toString().padStart(2, '0')}`;
            
            let color = p.direction === "UP" ? 'var(--neon-green)' : 'var(--neon-red)';
            let bgTint = p.direction === "UP" ? 'rgba(34, 197, 94, 0.05)' : 'rgba(239, 68, 68, 0.05)';
            let dirArrow = p.direction === "UP" ? "UP 🚀" : "DOWN 🩸";
            
            activeHtml += `
<div style="margin-bottom: 8px; border-left: 3px solid ${color}; padding: 8px 12px; background: ${bgTint}; border-radius: 4px;">
<span style="color: ${color}; font-weight: 800; text-shadow: 0 0 5px ${color};">[ALIVE]</span> <span style="color: var(--text-pure); font-weight: 700;">${p.symbol}</span> | <span style="color: ${color};">${dirArrow}</span> | <span style="color: var(--text-dim);">state=</span><span style="color: var(--text-pure);">${p.market_state}</span> | <span style="color: var(--text-dim);">ESI=</span><span style="color: var(--text-pure);">${p.esi}</span> | <span style="color: var(--text-dim);">age=</span><span style="color: var(--text-pure);">${ageStr}</span> | <span style="color: var(--gold);">Best: $${p.best_price.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</span>
</div>`;
        });
        activeContainer.innerHTML = activeHtml;
    } else {
        activeContainer.innerHTML = '<div style="color: #4a5568; font-style: italic;">No active predictions currently locked...</div>';
    }
    
    // Render Resolved History
    if (accData.resolved_theses && accData.resolved_theses.length > 0) {
        let resolvedHtml = '';
        
        accData.resolved_theses.forEach(p => {
            // Use the backend result directly
            let resultColor = 'var(--neon-red)';
            let resultBg = 'rgba(239, 68, 68, 0.05)';
            let resultText = p.result;
            let icon = '❌';
            
            if (p.result === "WIN") {
                resultColor = 'var(--neon-green)';
                resultBg = 'rgba(34, 197, 94, 0.05)';
                icon = '✅';
            } else if (p.result === "DRAW") {
                resultColor = 'var(--gold)';
                resultBg = 'rgba(255, 179, 0, 0.05)';
                icon = '⚖️';
            }
            
            let dirArrow = p.direction === "UP" ? "صعود 🚀" : "هبوط 🩸";
            const movePct = p.pnl_pct > 0 ? `+${p.pnl_pct.toFixed(3)}%` : `${p.pnl_pct.toFixed(3)}%`;
            
            let mfePct = 0;
            if (p.direction === "UP") {
                mfePct = ((p.best_price - p.open_price) / p.open_price) * 100;
            } else {
                mfePct = ((p.open_price - p.best_price) / p.open_price) * 100;
            }
            mfePct = Math.max(0, mfePct);
            
            resolvedHtml += `
<div style="margin-bottom: 12px; border-left: 3px solid ${resultColor}; background: ${resultBg}; padding: 10px 12px; border-radius: 4px;">
<div style="color: var(--text-pure); font-weight: bold; margin-bottom: 4px;">🔔 إغلاق العملية: ${p.symbol} (${dirArrow})</div>
<div style="color: var(--text-dim);">🎯 الدخول: <span style="color: var(--text-pure);">$${p.open_price.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:5})}</span> | 🛑 الخروج: <span style="color: var(--text-pure);">$${(p.exit_price||0).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:5})}</span></div>
<div style="color: var(--text-dim);">💥 أقصى قمة (MFE): <span style="color: var(--text-pure);">$${p.best_price.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:5})}</span> <span style="color: var(--neon-green);">(+${mfePct.toFixed(3)}%)</span></div>
<div style="color: var(--text-dim);">⏱ عاشت: <span style="color: var(--text-pure);">${p.age_seconds} ثانية</span> | ❌ السبب: <span style="color: var(--text-pure);">${p.reason}</span></div>
<div style="color: ${resultColor}; text-shadow: 0 0 5px ${resultColor}; margin-top: 8px; font-weight: 900; font-size: 1.1rem; border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 8px;">
${icon} النتيجة: ${movePct} [ ${resultText} ]
</div>
</div>`;
        });
        resolvedContainer.innerHTML = resolvedHtml;
    } else {
        resolvedContainer.innerHTML = '<div style="color: #4a5568; font-style: italic;">Awaiting resolved predictions...</div>';
    }
}
