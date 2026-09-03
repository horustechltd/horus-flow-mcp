/**
 * Horus Intel - Multi-Asset Intelligence Engine (PRO REBUILD)
 */

let trackedAssets = [];
let globalAccuracy = null;
const HEARTBEAT_INTERVAL = 2000;
const GLOBAL_INTEL_INTERVAL = 5000;

document.addEventListener('DOMContentLoaded', () => {
    initGlobalIntelligence();
    setupEventListeners();
    
    // Default trackers
    addTracker('BTCUSDT', 'crypto');
    addTracker('ETHUSDT', 'crypto');
    addTracker('SOLUSDT', 'crypto');
    addTracker('AAPL', 'equity');
    addTracker('NVDA', 'equity');
    addTracker('TSLA', 'equity');
});

function setupEventListeners() {
    const btnTrack = document.getElementById('btn-track');
    const trackInput = document.getElementById('track-input');
    const trackType = document.getElementById('track-type');

    btnTrack.addEventListener('click', () => {
        const symbol = trackInput.value.trim().toUpperCase();
        const type = trackType.value;
        if (symbol) {
            addTracker(symbol, type);
            trackInput.value = '';
        }
    });

    trackInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') btnTrack.click();
    });
}

/**
 * GLOBAL INTELLIGENCE POLLING
 */
async function initGlobalIntelligence() {
    const poll = async () => {
        const apiKey = document.getElementById('rapid-key').value || 'horus-demo-key-2026';
        
        try {
            // 0. Level 4 Cortex Symphony
            const ctxRes = await fetch(`/v1/intelligence/cortex?key=${apiKey}`);
            if (ctxRes.ok) {
                const ctxData = await ctxRes.json();
                updateCortexLiveBrain(ctxData);
            }

            // 1. Climate
            const cRes = await fetch(`/v1/intelligence/climate?key=${apiKey}`);
            if (cRes.ok) {
                const cData = await cRes.json();
                updateGlobalClimate(cData);
            }

            // 2. Ignitions
            const iRes = await fetch(`/v1/intelligence/ignitions?key=${apiKey}`);
            if (iRes.ok) {
                const iData = await iRes.json();
                updateGlobalIgnitions(iData);
            }

            // 3. Incubator (Court)
            const bRes = await fetch(`/v1/intelligence/incubator?key=${apiKey}`);
            if (bRes.ok) {
                const bData = await bRes.json();
                updateGlobalCourt(bData);
            }
            
        } catch (e) {
            console.error("Global Intel Sync Error:", e);
        }
    };

    poll();
    setInterval(poll, GLOBAL_INTEL_INTERVAL);
}

function updateCortexLiveBrain(data) {
    if (!data) return;
    const regime = data.regime_state || 'TRANSITION';
    const direction = data.transition_direction || 'STABLE';
    const trust = Math.round(data.trust_score || 0);
    const policy = data.action_policy || {};
    const boundaries = data.execution_boundaries || {};
    const vitals = data.market_vitals || {};
    const narrative = data.narrative || {};
    const contradictions = data.active_contradictions || [];

    // Pills & Badges
    const regimePill = document.getElementById('cortex-regime-pill');
    if (regimePill) {
        regimePill.innerText = regime;
        regimePill.className = 'cortex-pill ' + (regime.includes('BULL') ? 'badge-green' : regime.includes('BEAR') ? 'badge-red' : 'badge-gold');
    }
    const trustPill = document.getElementById('cortex-trust-pill');
    if (trustPill) {
        trustPill.innerText = `TRUST: ${trust}%`;
        trustPill.className = 'cortex-pill ' + (trust >= 60 ? 'badge-green' : trust >= 40 ? 'badge-gold' : 'badge-red');
    }

    // Col 1: Consensus
    const regimeVal = document.getElementById('cortex-regime-val');
    if (regimeVal) regimeVal.innerText = regime;
    const trajVal = document.getElementById('cortex-trajectory-val');
    if (trajVal) trajVal.innerText = `Trajectory: ${direction}`;

    // Col 2: Trust
    const trustVal = document.getElementById('cortex-trust-val');
    if (trustVal) trustVal.innerHTML = `${trust} <span style="font-size:0.9rem; color:var(--text-dim);">/ 100</span>`;
    const takerVal = document.getElementById('cortex-taker-val');
    if (takerVal) {
        const tr = vitals.taker_ratio || 1.0;
        takerVal.innerText = `Taker: ${tr.toFixed(2)}x (${tr >= 1.0 ? 'Whale Buy' : 'Whale Sell'})`;
    }

    // Col 3: Boundaries
    const resVal = document.getElementById('cortex-res-val');
    if (resVal && boundaries.breakout_resistance) resVal.innerText = `RES: $${Math.round(boundaries.breakout_resistance).toLocaleString()}`;
    const supVal = document.getElementById('cortex-sup-val');
    if (supVal && boundaries.invalidation_support) supVal.innerText = `SUP: $${Math.round(boundaries.invalidation_support).toLocaleString()}`;
    const btcPrice = document.getElementById('cortex-btc-price');
    if (btcPrice && boundaries.btc_price) btcPrice.innerText = `Ref BTC: $${boundaries.btc_price.toLocaleString()}`;

    // Col 4: Action Policy
    const dirVal = document.getElementById('cortex-directive-val');
    if (dirVal) {
        let shortDirective = 'CAPITAL PRESERVATION';
        if (policy.directive) {
            shortDirective = policy.directive.split(':')[0].trim();
        }
        dirVal.innerText = shortDirective.toUpperCase();
    }
    const multVal = document.getElementById('cortex-mult-val');
    if (multVal) {
        multVal.innerText = `Ignition: ${policy.ignition_multiplier || 0}x · Reversal: ${policy.reversal_multiplier || 0}x`;
    }

    // Radar Banner
    const radarMsg = document.getElementById('cortex-contradiction-msg');
    const actionTag = document.getElementById('cortex-action-tag');
    if (radarMsg) {
        if (contradictions.length > 0) {
            radarMsg.innerText = contradictions.join(' | ');
            if (actionTag) {
                actionTag.innerText = 'CONTRADICTION DETECTED';
                actionTag.style.background = 'rgba(239, 68, 68, 0.2)';
                actionTag.style.color = '#fca5a5';
            }
        } else if (narrative.human_verdict) {
            radarMsg.innerText = `${narrative.human_verdict} · ${narrative.summary_english || ''}`;
            if (actionTag) {
                actionTag.innerText = policy.ignition_allowed ? 'GO ACTIVE' : 'PRESERVE CAPITAL';
                actionTag.style.background = policy.ignition_allowed ? 'rgba(34, 197, 94, 0.2)' : 'rgba(255, 179, 0, 0.2)';
                actionTag.style.color = policy.ignition_allowed ? '#86efac' : '#fde047';
            }
        }
    }
}

function updateGlobalClimate(data) {
    document.getElementById('gw-mode').innerText = data.market_mode || '---';
    document.getElementById('gw-rec').innerText = data.recommendation || '---';
    document.getElementById('gw-conf').innerText = Math.round((data.confidence || 0) * 100) + '%';
    document.getElementById('gw-agg').innerText = (data.aggression_level || 0).toFixed(1) + 'x';
    document.getElementById('gw-health').innerText = data.health || '---';
    
    const badge = document.getElementById('gw-health-badge');
    badge.innerText = data.health || '---';
    badge.className = 'w-badge ' + (data.health === 'HEALTHY' ? 'badge-green' : 'badge-gray');
}

function updateGlobalIgnitions(data) {
    const r = data.regime || '---';
    document.getElementById('gi-regime').innerText = r;
    document.getElementById('gi-regime-badge').innerText = r;
    const badge = document.getElementById('gi-regime-badge');
    badge.className = 'w-badge ' + (r === 'IGNITED' ? 'badge-red' : 'badge-gray');

    document.getElementById('gi-sub').innerText = `Scanning ${data.summary?.total_tracked || 0} assets | Bias: ${data.regime_bias || '---'}`;
    
    document.getElementById('gi-score').innerText = (data.global_ignition_score || 0).toFixed(3);
    document.getElementById('gi-hot').innerText = (data.summary?.pct_above_0_6 || 0) + '%';
    document.getElementById('gi-tracked').innerText = data.summary?.total_tracked || 0;
}

function updateGlobalCourt(data) {
    document.getElementById('gc-total').innerText = data.total_incubated || 0;
    const readyCount = data.summary?.ready_count || 0;
    document.getElementById('gc-ready-badge').innerText = `${readyCount} READY`;
    
    const sub = document.getElementById('gc-sub');
    sub.innerHTML = `<span class="text-white">🚀 ${readyCount} READY</span> for EdgeBridge entry | ${data.summary?.absorbing_count || 0} absorbing | ${data.summary?.waiting_count || 0} waiting`;

    const list = document.getElementById('inc-list');
    const allItems = [...data.ready, ...data.absorbing, ...data.waiting, ...data.hot].slice(0, 10);
    
    list.innerHTML = allItems.map(item => `
        <div class="inc-item font-mono ${item.state === 'READY' ? 'inc-ready' : ''}">
            <span style="font-weight:700; font-size: 0.95rem;">${item.symbol}</span>
            <span class="text-dim" style="font-size:0.75rem;">${item.tracking_cycles} cycles</span>
            <span style="color:${item.state === 'READY' ? 'var(--green)' : 'var(--pink)'}; font-size:0.8rem; font-weight:800;">● ${item.state}</span>
        </div>
    `).join('');
}

/**
 * ASSET TRACKING ENGINE
 */
function addTracker(symbol, type) {
    // Prevent duplicate
    if (trackedAssets.find(a => a.symbol === symbol)) return;
    
    const id = "tracker-" + Math.random().toString(36).substr(2, 9);
    const container = document.getElementById('track-grid');
    const template = document.getElementById('card-template');
    const clone = template.content.cloneNode(true);
    
    const card = clone.querySelector('.flow-card');
    card.id = id;
    
    card.querySelector('[data-id="card-symbol"]').innerText = symbol;
    card.querySelector('[data-id="tag-type"]').innerText = type.toUpperCase();
    
    // Add symbol overlay inside chart
    const tvLabel = card.querySelector('[data-id="tv-label"]');
    if (tvLabel) {
        tvLabel.innerText = symbol;
    }

    const tvId = "tv-" + id;
    card.querySelector('[data-id="tv_chart"]').id = tvId;

    // Remove logic
    card.querySelector('[data-id="btn-close"]').addEventListener('click', () => {
        trackedAssets = trackedAssets.filter(a => a.id !== id);
        card.remove();
    });

    container.appendChild(clone);
    
    // Initialize TV Widget
    setTimeout(() => initTV(tvId, symbol, type), 100);

    const assetObj = {
        id: id,
        symbol: symbol,
        type: type,
        card: document.getElementById(id)
    };
    
    trackedAssets.push(assetObj);
    
    // Start polling for this specific asset
    pollAsset(assetObj);
}

function initTV(id, symbol, type) {
    let tvSymbol = "BINANCE:" + symbol;
    if (type === 'equity') {
        tvSymbol = "NASDAQ:" + symbol; // Fallback
    }

    new TradingView.widget({
        "autosize": true,
        "symbol": tvSymbol,
        "interval": "1",
        "timezone": "Etc/UTC",
        "theme": "dark",
        "style": "1",
        "locale": "en",
        "toolbar_bg": "#f1f3f6",
        "enable_publishing": false,
        "hide_top_toolbar": true,
        "hide_legend": true,
        "save_image": false,
        "container_id": id,
        "backgroundColor": "#000000",
        "gridColor": "#1a1a1a"
    });
}

async function pollAsset(asset) {
    const execute = async () => {
        // If asset removed, stop polling
        if (!trackedAssets.find(a => a.id === asset.id)) return;

        const apiKey = document.getElementById('rapid-key').value || 'horus-demo-key-2026';
        const endpoint = `/v1/flow/${asset.type}/${asset.symbol}?key=${apiKey}`;

        try {
            const res = await fetch(endpoint);
            const data = await res.json();
            
            if (res.ok) {
                updateAssetCard(asset.id, data, false);
            } else {
                // API returned an error (e.g. market closed, no data)
                updateAssetCard(asset.id, data, true);
            }
        } catch (e) {
            console.error(`Poll error for ${asset.symbol}:`, e);
        }
        
        setTimeout(execute, HEARTBEAT_INTERVAL);
    };

    execute();
}

function updateAssetCard(id, data, isOffline) {
    const card = document.getElementById(id);
    if (!card) return;

    const statusOverlay = card.querySelector('[data-id="card-status"]');

    if (isOffline) {
        // Show market closed / error status
        statusOverlay.classList.remove('hidden');
        const errMsg = data.detail || 'Feed unavailable';
        statusOverlay.innerHTML = `<span>⚠️ ${errMsg}</span>`;
        
        // Mark all values as offline
        card.querySelector('[data-id="card-signal"]').innerText = 'OFFLINE';
        card.querySelector('[data-id="card-signal"]').className = 'f-val text-dim';
        card.querySelector('[data-id="card-conf"]').innerText = '---';
        card.querySelector('[data-id="card-risk"]').innerText = '---';
        card.querySelector('[data-id="card-risk"]').className = 'f-val text-dim';
        card.querySelector('[data-id="card-state"]').innerText = '---';
        card.querySelector('[data-id="card-state"]').className = 'f-val text-dim';
        card.querySelector('[data-id="card-whales"]').innerText = '---';
        card.querySelector('[data-id="card-mom"]').innerText = '---';
        card.querySelector('[data-id="card-wall"]').innerText = '---';
        card.querySelector('[data-id="card-logs"]').innerText = errMsg;
        return;
    }

    // Live data — hide any offline overlay
    statusOverlay.classList.add('hidden');

    const signal = data.signal || 'NEUTRAL';
    const sEl = card.querySelector('[data-id="card-signal"]');
    sEl.innerText = signal;
    sEl.className = 'f-val ' + (signal.includes('EXIT') || signal.includes('SELL') || signal.includes('DUMP') ? 'text-red' : signal.includes('BUY') || signal.includes('PUMP') ? 'text-green' : 'text-white');

    card.querySelector('[data-id="card-conf"]').innerText = Math.round((data.confidence || 0) * 100) + '%';
    
    // Edge Proof — read from global accuracy cache
    const ep = card.querySelector('[data-id="card-edge"]');
    const symbol = data.symbol || '';
    if (globalAccuracy && globalAccuracy.symbols && globalAccuracy.symbols[symbol]) {
        const symAcc = globalAccuracy.symbols[symbol];
        ep.innerText = `${symAcc.accuracy.toFixed(1)}% (${symAcc.wins}/${symAcc.resolved})`;
        ep.className = 'f-val text-gold';
    } else if (globalAccuracy && globalAccuracy.stats) {
        const w = globalAccuracy.stats.wins || 0;
        const l = globalAccuracy.stats.losses || 0;
        const d = globalAccuracy.stats.draws || 0;
        const t = w + l + d;
        const pct = t > 0 ? Math.round((w/t)*100) : 0;
        ep.innerText = `${pct}% (${w}W)`;
        
        if (pct > 50 && t > 0) ep.className = 'f-val text-green';
        else if (pct < 50 && t > 0) ep.className = 'f-val text-red';
        else ep.className = 'f-val text-gold';
    } else {
        ep.innerText = '---';
        ep.className = 'f-val text-dim';
    }

    const rEl = card.querySelector('[data-id="card-risk"]');
    rEl.innerText = data.risk || '---';
    rEl.className = 'f-val ' + (data.risk === 'HIGH' ? 'text-red' : data.risk === 'MEDIUM' ? 'text-gold' : 'text-green');

    const stEl = card.querySelector('[data-id="card-state"]');
    stEl.innerText = data.market_state || '---';
    stEl.className = 'f-val ' + (data.market_state === 'DISTRIBUTION' || data.market_state === 'COLLAPSE' ? 'text-red' : 'text-white');

    const m = data.metrics || {};
    
    // Whales — with specific counts
    const whaleEl = card.querySelector('[data-id="card-whales"]');
    if (m.whale_activity) {
        const dumpCount = m.large_sell_count || 0;
        whaleEl.innerHTML = `<span class="dot-red"></span> ${dumpCount} DUMPS`;
        whaleEl.className = 'f-sval text-red';
    } else if (m.sell_spike) {
        whaleEl.innerHTML = `<span class="dot-red"></span> SPIKE`;
        whaleEl.className = 'f-sval text-orange';
    } else {
        whaleEl.innerHTML = `CLEAR`;
        whaleEl.className = 'f-sval text-dim';
    }

    // Momentum
    const mom = m.delta_accel || 0;
    const momEl = card.querySelector('[data-id="card-mom"]');
    if (mom > 1.5) {
        momEl.innerText = `BUILDING ${mom.toFixed(1)}x`;
        momEl.className = 'f-sval text-green';
    } else {
        momEl.innerText = `${mom.toFixed(1)}x`;
        momEl.className = 'f-sval text-white';
    }
    
    card.querySelector('[data-id="card-wall"]').innerText = m.wall_side || 'NONE';

    // Climate local
    const climateStr = `${m.wiseman_climate?.market_mode || '---'} | ${m.wiseman_climate?.health || '---'} | ${Math.round((m.wiseman_climate?.confidence || 0)*100)}%`;
    card.querySelector('[data-id="card-climate"]').innerText = climateStr;

    // Flags + Description combined into logs
    const logEl = card.querySelector('[data-id="card-logs"]');
    let logText = data.description || '';
    if (m.flags && m.flags.length > 0) {
        logText += ' ⚠️ ' + m.flags.join(' | ');
    }
    logEl.innerText = logText || 'No recent behavioral events detected.';
}
