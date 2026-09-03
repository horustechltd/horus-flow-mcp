// ================================================================
// 🦅 HORUS FLOW — Interactive API Documentation Engine v2
// RapidAPI-style inline params + code snippets
// ================================================================

const BASE = window.location.origin;
let userKey = 'YOUR_API_KEY';
let userTier = 'free';
let activeLang = 'curl';
let activeEpId = 'crypto-flow';
let activeTab = 'params';
let paramValues = {}; // {epId: {paramName: value}}

// ============ ENDPOINT CATALOG ============
const SYM_CRYPTO = {name:'symbol',type:'string',required:true,default:'BTCUSDT',desc:'Trading pair (BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, DOGEUSDT, ADAUSDT, AVAXUSDT)'};
const SYM_L3 = {name:'symbol',type:'string',required:false,default:'BTCUSDT',desc:'Symbol to analyze (BTCUSDT, ETHUSDT, SOLUSDT). Default: BTCUSDT'};
const SYM_EQ = {name:'symbol',type:'string',required:true,default:'AAPL',desc:'Equity ticker (AAPL, TSLA, MSFT, NVDA, AMZN, GOOGL, META, AMD, SPY, QQQ)'};

const EP = [
  { group:'Crypto Flow', items:[
    { id:'crypto-flow', method:'GET', path:'/v1/flow/crypto/{symbol}', tpl:'/v1/flow/crypto/$symbol',
      title:'Get Crypto Orderflow',
      desc:'Real-time L2 orderflow intelligence with strict machine-parseable schema. Includes whale detection, bid/ask imbalance, delta momentum, WiseMan climate overlay, and HTA whale intent. <br><br><strong>v2.1 Strict Schema:</strong> Every response includes <code>action</code>, <code>direction_bias</code>, <code>risk</code>, <code>market_regime</code>, <code>confidence</code>, <code>explanation</code>. Bots should switch on the <code>action</code> field for trade decisions.',
      params:[{name:'symbol',type:'string',required:true,default:'BTCUSDT',desc:'Trading pair (BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, DOGEUSDT, ADAUSDT, AVAXUSDT, SUIUSDT)'}],
      resp:{symbol:"BTCUSDT",signal:"STRONG_BUY_PRESSURE",action:"ENTER_LONG",direction_bias:"BULLISH",confidence:0.88,risk:"LOW",market_regime:"TRENDING",engine_version:"2.1.0",freshness_ms:0,timestamp_utc:"2026-05-08T07:36:06Z",explanation:"Heavy bidding combined with aggressive buying detected. Favorable conditions for UP movement.",market_state:"ACCUMULATION",description:"Heavy bidding combined with aggressive buying detected.",metrics:{bid_ask_ratio:2.15,buy_sell_ratio:0.72,delta_5s:18200,delta_30s:54600,whale_activity:true,large_sell_count:0,delta_accel:1.8,wall_side:"BID",top5_imbalance:0.72,spread_pct:0.0001,wiseman_climate:{market_mode:"RANGE",health:"HEALTHY",confidence:0.75},flags:["BID_WALL_SUPPORT","WISEMAN_APPROVED(RIDE)"]},whale_intent:{direction:"LONG",buy_ratio:0.82,delta_30s:286047,persistence:8,exec_intensity:82.7,age_seconds:0.9},timestamp:1778225172.336}
    },
    { id:'crypto-history', method:'GET', path:'/v1/flow/crypto/{symbol}/history', tpl:'/v1/flow/crypto/$symbol/history',
      title:'Get Crypto Flow History',
      desc:'Last N flow snapshots for backtesting and trend analysis.',
      params:[
        {name:'symbol',type:'string',required:true,default:'BTCUSDT',desc:'Trading pair symbol'},
        {name:'limit',type:'integer',required:false,default:'20',desc:'Snapshots to return (max 100)'}
      ],
      resp:{symbol:"BTCUSDT",snapshots:[{signal:"NEUTRAL",action:"WAIT",confidence:0.45,timestamp:1776107600},{signal:"STRONG_SELL_PRESSURE",action:"ENTER_SHORT",confidence:0.85,timestamp:1776107738}],count:2}
    }
  ]},
  { group:'Equity Flow', items:[
    { id:'equity-macro', method:'GET', path:'/v1/flow/equity/macro-blocks', tpl:'/v1/flow/equity/macro-blocks',
      title:'SPY Macro + Block Trades',
      desc:'SPY macro flow analysis and institutional block trades. Dark pool prints, block sizes, macro sentiment.',
      params:[],
      resp:{macro:{spy_sentiment:"BEARISH",vix_level:22.5,put_call_ratio:1.35},blocks:[{symbol:"AAPL",side:"SELL",size:150000,price:189.50}]}
    },
    { id:'equity-symbol', method:'GET', path:'/v1/flow/equity/{symbol}', tpl:'/v1/flow/equity/$symbol',
      title:'Get Equity Orderflow',
      desc:'Real-time orderflow for US equities via SIP feed. Same physics engine as crypto.',
      params:[{name:'symbol',type:'string',required:true,default:'AAPL',desc:'Equity ticker (AAPL, TSLA, MSFT, NVDA, AMZN, GOOGL, META, AMD, SPY, QQQ)'}],
      resp:{symbol:"AAPL",signal:"ACCUMULATION",confidence:0.72,market_state:"QUIET_ACCUMULATION",metrics:{bid_ask_ratio:1.85,buy_sell_ratio:1.4,delta_5s:8200}}
    }
  ]},
  { group:'Intelligence', items:[
    { id:'intel-climate', method:'GET', path:'/v1/intelligence/climate', tpl:'/v1/intelligence/climate',
      title:'Market Climate',
      desc:'WiseMan Climate Gate — macro market health, regime detection, and trading recommendation. <br><br><strong>v2.1:</strong> Data auto-refreshes every 5 minutes via background publisher. Includes <code>freshness_ms</code> showing data age.',
      params:[],
      resp:{action:"WAIT",direction_bias:"NEUTRAL",risk:"LOW",market_regime:"RANGING",engine_version:"2.1.0",freshness_ms:16173,timestamp_utc:"2026-05-08T07:22:16Z",explanation:"Mean-reversion strategies favored",market_mode:"RANGE",health:"HEALTHY",confidence:0.75,recommendation:"🟢 RANGE PLAYS — Mean-reversion strategies favored",reasoning:"EMA50 slope: +1.60% | RSI: 39 | ATR ratio: 0.89 | Vol ratio: 0.99 | Dir changes: 5/8",aggression_level:0.5,engine:"WiseMan Cognitive Gate v64.0"}
    },
    { id:'intel-ignitions', method:'GET', path:'/v1/intelligence/ignitions', tpl:'/v1/intelligence/ignitions',
      title:'Ignition Signals',
      desc:'Volatility Breakout Engine (VBE) scanner — which coins are about to explode. <br><br><strong>v2.1:</strong> Now includes strict schema fields. <code>DORMANT</code> → action: WAIT, <code>IGNITING</code> → action: ENTER_LONG, <code>ERUPTING</code> → action: ENTER_LONG + risk: HIGH.',
      params:[],
      resp:{action:"WAIT",direction_bias:"BULLISH",risk:"LOW",market_regime:"RANGING",engine_version:"2.1.0",timestamp_utc:"2026-05-08T07:36:36Z",regime:"DORMANT",regime_bias:"RISING",global_ignition_score:0.155,delta:-0.0013,stability:1.0,summary:{total_tracked:344,avg_ignition:0.3279,pct_above_0_6:5.8,pct_above_0_8:0.3},top_ignitions:[],engine:"Volatility Breakout Engine (VBE)"}
    },
    { id:'intel-verdict', method:'GET', path:'/v1/intelligence/verdict/{symbol}', tpl:'/v1/intelligence/verdict/$symbol',
      title:'Court Verdict',
      desc:'Behavioral Court judgment on any asset — conviction reason, incubator state, and EdgeBridge readiness. <br><br><strong>v2.1:</strong> Returns strict schema fields even when asset is NOT_TRACKED.',
      params:[{name:'symbol',type:'string',required:true,default:'BTCUSDT',desc:'Trading pair (BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, DOGEUSDT)'}], tier:'pro',
      resp:{action:"WAIT",direction_bias:"NEUTRAL",risk:"MEDIUM",engine_version:"2.1.0",timestamp_utc:"2026-05-08T07:37:23Z",symbol:"BTC/USDT",status:"NOT_TRACKED",message:"This asset has no court record. It may be clean or not yet scanned.",recommendation:"Use /v1/flow/crypto/{symbol} for raw orderflow data.",engine:"Behavioral Court v1.0"}
    },
    { id:'intel-incubator', method:'GET', path:'/v1/intelligence/incubator', tpl:'/v1/intelligence/incubator',
      title:'Incubator Pipeline',
      desc:'All assets being nursed for re-entry after Court rejection. Assets in READY = highest-conviction trades. <br><br><strong>v2.1:</strong> Top-level strict schema fields added.',
      params:[], tier:'pro',
      resp:{action:"WAIT",risk:"MEDIUM",engine_version:"2.1.0",timestamp_utc:"2026-05-08T07:37:23Z",total_incubated:18,summary:{ready_count:0,absorbing_count:0,waiting_count:0,hot_count:18},ready:[],hot:[{symbol:"TON/USDT",state:"HOT",action:"IGNORE",price:2.762,rejection_reason:"StructureCourt: AVOID | conf=0.00",tracking_cycles:54}],note:"Assets in 'ready' state have confirmed bounces and meet EdgeBridge entry criteria.",engine:"Incubator v5.2 + EdgeBridge"}
    }
  ]},
  { group:'Level 3 Intelligence', badge:'PRO', items:[
    { id:'intel-composite', method:'GET', path:'/v1/intelligence/composite', tpl:'/v1/intelligence/composite?symbol=$symbol',
      title:'Composite Verdict',
      desc:'All 4 intelligence layers fused into ONE actionable score (0-100). >80 = FULL_CONVICTION, <40 = STAY_OUT. <br><br><strong>v2.1:</strong> Now includes <code>confidence</code> (0.0–1.0 = composite_score/100) and emoji-free <code>explanation</code>.',
      params:[{name:'symbol',type:'string',required:false,default:'BTCUSDT',desc:'Symbol to analyze (BTCUSDT, ETHUSDT, SOLUSDT)'}], tier:'pro',
      resp:{symbol:"BTCUSDT",composite_score:39.4,verdict:"STAY_OUT",direction:"NEUTRAL",action:"WAIT",direction_bias:"NEUTRAL",confidence:0.39,risk:"EXTREME",market_regime:"RANGING",engine_version:"2.1.0",freshness_ms:7950,timestamp_utc:"2026-05-08T07:26:22Z",explanation:"FLAT — BTCUSDT — Speculation Dominated",breakdown:{climate_score:18.8,ignition_score:3.1,heatmap_score:4.5,xflow_score:13.0},details:{climate:"RANGE/HEALTHY(conf=75%)",ignition:"DORMANT(ign=0.15,stab=1.0)",heatmap:"grav=NEUTRAL(0.30),crowd=BALANCED,smd=False",xflow:"SPECULATION_DOMINATED,STABLE,fund=+0.00002"},data_freshness:"FRESH",engine:"Composite Intelligence v1.0 (Climate + Ignition + Heatmap + XFlow)"}
    },
    { id:'intel-heatmap', method:'GET', path:'/v1/intelligence/liquidation-heatmap', tpl:'/v1/intelligence/liquidation-heatmap?symbol=$symbol',
      title:'Liquidation Heatmap',
      desc:'Where is price FORCED to go? Maps leveraged liquidation cascade zones. <br><br><strong>v2.1:</strong> Action now factors in <code>crowd_bias</code> + <code>smart_money_divergence</code>. OVERLEVERAGED_LONG + gravity DOWN → <code>BLOCK_LONG</code>.',
      params:[{name:'symbol',type:'string',required:false,default:'BTCUSDT',desc:'Symbol to analyze (BTCUSDT, ETHUSDT, SOLUSDT)'}], tier:'pro',
      resp:{symbol:"ETHUSDT",current_price:2266.6,gravity_direction:"DOWN",gravity_score:0.4434,crowd_bias:"OVERLEVERAGED_LONG",long_short_ratio_global:2.6443,long_short_ratio_top_traders:1.0078,smart_money_divergence:true,oi_change_30m_pct:-0.13,oi_current:5221088894.2,taker_buy_sell_ratio:2.075,estimated_liquidation_zones:{long_zones:[2243.93,2221.27,2198.60,2153.27],short_zones:[2289.27,2311.93,2334.60,2379.93]},risk_assessment:"🔴 HIGH — Market overleveraged long. $5.2B in estimated long liquidations below -3%.",action:"BLOCK_LONG",direction_bias:"BEARISH",risk:"EXTREME",market_regime:"RANGING",engine_version:"2.1.0",freshness_ms:20899,timestamp_utc:"2026-05-08T07:26:31Z",explanation:"Market overleveraged long. $5.2B in estimated long liquidations below -3%.",data_freshness:"FRESH",engine:"Liquidation Heatmap v1.0"}
    },
    { id:'intel-xexchange', method:'GET', path:'/v1/intelligence/cross-exchange-flow', tpl:'/v1/intelligence/cross-exchange-flow?symbol=$symbol',
      title:'Cross-Exchange Flow',
      desc:'Is the move REAL or speculative? Compares Spot vs Futures volume, premium/discount, and OI velocity. <br><br><strong>v2.1:</strong> Extreme funding rates (>5bps) now influence the action: high positive funding → <code>BLOCK_LONG</code>.',
      params:[{name:'symbol',type:'string',required:false,default:'BTCUSDT',desc:'Symbol to analyze (BTCUSDT, ETHUSDT, SOLUSDT)'}], tier:'pro',
      resp:{symbol:"BTCUSDT",futures_volume_24h:10100506250.07,spot_volume_24h:1391646514.45,futures_spot_volume_ratio:7.26,market_type:"SPECULATION_DOMINATED",premium_discount_pct:-0.045,premium_bias:"NEUTRAL",funding_rate:0.000018,oi_current:8182599988.95,oi_velocity_10m_pct:-0.23,positioning_signal:"STABLE",action:"WAIT",direction_bias:"NEUTRAL",risk:"MEDIUM",market_regime:"RANGING",engine_version:"2.1.0",freshness_ms:2940,timestamp_utc:"2026-05-08T07:26:41Z",explanation:"Speculation dominated. Vulnerable to flush.",data_freshness:"FRESH",engine:"Cross-Exchange Flow v1.0"}
    },
    { id:'intel-full', method:'GET', path:'/v1/intelligence/market-intelligence', tpl:'/v1/intelligence/market-intelligence',
      title:'Full Market Intelligence',
      desc:'ALL intelligence layers for ALL symbols in ONE call. Includes <code>action_summary</code> — a quick-lookup per-symbol map with action, direction_bias, risk, composite_score, and verdict. The ultimate endpoint for dashboards and AI agents.',
      params:[], tier:'pro',
      resp:{timestamp_utc:"2026-05-08T07:26:44Z",engine_version:"2.1.0",action_summary:{BTCUSDT:{action:"WAIT",direction_bias:"NEUTRAL",risk:"EXTREME",composite_score:39.4,verdict:"STAY_OUT"},ETHUSDT:{action:"WAIT",direction_bias:"BEARISH",risk:"HIGH",composite_score:47.5,verdict:"NEUTRAL"},SOLUSDT:{action:"WAIT",direction_bias:"BEARISH",risk:"HIGH",composite_score:45.6,verdict:"NEUTRAL"}},climate:{market_mode:"RANGE",health:"HEALTHY",confidence:0.75},ignition:{regime:"DORMANT",global_ignition_score:0.155},heatmap_summary:{dominant_gravity:"DOWN",symbols:{BTCUSDT:{gravity:"NEUTRAL",crowd:"BALANCED"},ETHUSDT:{gravity:"DOWN",crowd:"OVERLEVERAGED_LONG"},SOLUSDT:{gravity:"DOWN",crowd:"LONG_HEAVY"}}}}
    }
  ]},
  { group:'Level 4 Cognitive Cortex', badge:'INSTITUTIONAL', items:[
    { id:'intel-cortex', method:'GET', path:'/v1/intelligence/cortex', tpl:'/v1/intelligence/cortex',
      title:'Horus Cortex Brain',
      desc:'Full-Spectrum Cognitive Market Brain (Horus Cortex Symphony v3.0). Fuses 7 independent evidence families (Price Structure, Dynamic S/R Map, Orderflow Taker Imbalance, Lagging Confirmations, Cycle Memory, Altcoin Breadth, Microstructure Anomalies). <br><br><strong>Machine-to-Machine Sovereign Contract:</strong> Returns penalized <code>trust_score</code> (0-100), active <code>contradictions</code>, exact <code>execution_boundaries</code> (invalidation support and breakout resistance in USD), dynamic <code>action_policy</code> with position sizing multipliers for autonomous bots, and deterministic institutional Arabic & English narrative.',
      params:[], tier:'pro',
      resp:{status:"success",timestamp:1788225200,timestamp_utc:"2026-09-03T08:12:00Z",engine:"Horus Cortex Symphony v3.0",regime_state:"TRANSITION",transition_direction:"STABLE",trust_score:46.1,action_policy:{directive:"Deteriorating Transition: Capital Preservation Lock (0.0x)",ignition_multiplier:0.0,trend_multiplier:0.0,reversal_multiplier:0.5,shock_multiplier:0.0,ignition_allowed:false,trend_allowed:false,reversal_allowed:true},execution_boundaries:{btc_price:77955.01,invalidation_support:77176.0,breakout_resistance:78735.0,invalidation_risk_pct:1.0,breakout_target_pct:1.0},market_vitals:{taker_ratio:2.07,global_ignition:0.081,global_dominant_gravity:"DOWN",btc_15m_return_pct:0.12,btc_1h_return_pct:0.353},active_contradictions:[{contradiction_id:"BULLISH_PRICE_vs_HOLLOW_BREADTH",category:"PRICE_VS_BREADTH",severity:"MEDIUM",description:"البيتكوين صاعد لكن اتساع السوق العام منكمش وخامل (صعود معزول)"}],narrative:{headline:"🎼 تقرير المايسترو: مرحلة انتقالية وإعادة تقييم (موثوقية 46%)",summary_arabic:"السوق في حالة [مرحلة انتقالية وإعادة تقييم] بمستوى موثوقية (46/100). البيتكوين عند $77,955 (+0.01%) ونسبة صانع/آخذ السوق 2.07. التفسير: تضارب بين المؤشرات يستوجب تقليص المخاطر.",summary_english:"Market State: TRANSITION | Trust Score: 46/100 | Direction: DETERIORATING",risk_factors:["اتساع سوق منكمش وخامل: صعود يفتقر للدعم العام (0.08)","جاذبية تصفيات عامة هابطة في الألتكوين","⚠️ تناقض نشط: البيتكوين صاعد لكن اتساع السوق العام منكمش وخامل (صعود معزول)"],what_improves_verdict:["اختراق المقاومة الرئيسية المحددة عند $78,735 والثبات التداولي فوقها.","استمرار كفاءة تدفق الشراء الحالي (2.07) في تحقيق قمم سعرية جديدة."],what_worsens_verdict:["كسر الدعم الهيكلي الرئيسي عند $77,176 والإغلاق أسفله.","تراجع نسبة الشراء التنافسي (Taker الحالي: 2.07 ➔ هبوط تحت 0.90 مع ظهور بيع هجومي)."]},data_freshness:"FRESH"}
    }
  ]},
  { group:'System', items:[
    { id:'health', method:'GET', path:'/health', tpl:'/health',
      title:'Health Check', desc:'Server health, uptime, feeds, version. No auth required.',
      params:[], noAuth:true,
      resp:{status:"healthy",uptime:"14d 6h 32m",version:"2.1.0",feeds:{binance:"connected",alpaca:"connected"},tracked_symbols:12}
    }
  ]}
];


// ============ HELPERS ============
function findEp(id) { for(const g of EP) for(const i of g.items) if(i.id===id) return i; return null; }

function getParamVal(ep, name) {
  if(!paramValues[ep.id]) paramValues[ep.id]={};
  const p = ep.params.find(x=>x.name===name);
  return paramValues[ep.id][name] || (p ? p.default : '');
}

function buildUrl(ep) {
  let url = ep.tpl;
  ep.params.forEach(p => { url = url.replace('$'+p.name, getParamVal(ep, p.name)); });
  return url;
}

function copyText(t) {
  navigator.clipboard.writeText(t);
  const toast = document.getElementById('toast');
  toast.style.display='block';
  setTimeout(()=>toast.style.display='none',1200);
}

function syntaxHL(j) {
  return j.replace(/(".*?")\s*:/g,'<span class="cg">$1</span>:')
    .replace(/:\s*(".*?")/g,': <span class="cs">$1</span>')
    .replace(/:\s*(\d+\.?\d*)/g,': <span class="cn">$1</span>')
    .replace(/:\s*(true|false|null)/g,': <span class="ck">$1</span>');
}

// ============ CODE GENERATION ============
function genCode(ep, lang) {
  const url = `${BASE}${buildUrl(ep)}`;
  const k = userKey;
  if(lang==='curl') return `curl -X GET \\\n  "${url}" \\\n  -H "X-API-Key: ${k}"`;
  if(lang==='python') return `import requests\n\nr = requests.get(\n    "${url}",\n    headers={"X-API-Key": "${k}"}\n)\ndata = r.json()\nprint(data)`;
  if(lang==='javascript') return `const res = await fetch(\n  "${url}",\n  { headers: { "X-API-Key": "${k}" }}\n);\nconst data = await res.json();\nconsole.log(data);`;
  if(lang==='go') return `req, _ := http.NewRequest("GET", "${url}", nil)\nreq.Header.Set("X-API-Key", "${k}")\nresp, _ := http.DefaultClient.Do(req)\nbody, _ := io.ReadAll(resp.Body)\nfmt.Println(string(body))`;
  if(lang==='ruby') return `uri = URI("${url}")\nreq = Net::HTTP::Get.new(uri)\nreq["X-API-Key"] = "${k}"\nres = Net::HTTP.start(uri.hostname, uri.port, use_ssl: true) { |h| h.request(req) }\nputs JSON.parse(res.body)`;
  return '';
}

// ============ RENDER SIDEBAR ============
function renderSidebar(filter='') {
  const el = document.getElementById('sidebar-list');
  let html = '';
  EP.forEach(g => {
    const items = g.items.filter(i=> !filter || i.title.toLowerCase().includes(filter) || i.path.toLowerCase().includes(filter));
    if(!items.length) return;
    html += `<div class="sb-group"><div class="sb-group-title" onclick="this.parentElement.classList.toggle('collapsed')">
      ${g.group} ${g.badge?`<span class="sb-badge">${g.badge}</span>`:''}
      <span class="chevron">▾</span></div><div class="sb-items">`;
    items.forEach(i => {
      const locked = false; // i.tier && ((i.tier==='pro'&&!['pro','institutional'].includes(userTier))||(i.tier==='trader'&&userTier==='free'));
      html += `<div class="sb-item ${i.id===activeEpId?'active':''}" onclick="selectEp('${i.id}')">
        <span class="method m-get">${i.method}</span>
        <span class="path">${i.path.replace('/v1/flow/','').replace('/v1/intelligence/','')}</span>
        ${locked?'<span class="lock">🔒</span>':''}
      </div>`;
    });
    html += '</div></div>';
  });
  el.innerHTML = html;
}

// ============ RENDER CENTER ============
function renderCenter(ep) {
  const el = document.getElementById('docs-center');
  const json = JSON.stringify(ep.resp,null,2);
  el.innerHTML = `
    <div class="ep-header">
      <div class="ep-method-badge get">${ep.method} ${ep.tier?`· <span style="color:var(--gold-primary)">${ep.tier.toUpperCase()}+</span>`:''}</div>
      <div class="ep-url"><span>${BASE}${ep.path}</span>
        <button class="copy-url" onclick="copyText('${BASE}${buildUrl(ep)}')" title="Copy">📋</button></div>
      <h1 class="ep-title">${ep.title}</h1>
      <p class="ep-desc">${ep.desc}</p>
    </div>
    ${!ep.noAuth?`<div class="doc-section"><h3><span class="icon">🔑</span> Authentication</h3>
      <div class="auth-box"><div class="auth-header">X-API-Key Header</div>
      <p style="font-size:0.82rem;color:var(--text-secondary);margin-bottom:8px">Pass via <code>X-API-Key</code> header or <code>?key=</code> query param.</p>
      <div class="auth-key-display" onclick="copyText('${userKey}')"><span>${userKey}</span><span style="font-size:0.7rem">📋</span></div>
      ${userKey==='YOUR_API_KEY'?'<p style="font-size:0.72rem;color:var(--accent-red);margin-top:8px">⚠️ <a href="./register.html" style="color:var(--gold-primary)">Create a free account</a> to get your API key</p>':''}
    </div></div>`:''} 
    <div class="doc-section"><h3><span class="icon">📦</span> Response Example</h3>
      <div class="response-example"><div class="resp-header"><span class="resp-status">200 OK</span>
        <button class="resp-copy" onclick="copyText(JSON.stringify(${JSON.stringify(ep.resp)},null,2))">Copy JSON</button></div>
        <pre>${syntaxHL(json)}</pre></div></div>
    <div class="doc-section"><h3><span class="icon">⚠️</span> Error Codes</h3>
      <table class="error-table"><thead><tr><th>Code</th><th>Meaning</th><th>Description</th></tr></thead><tbody>
        <tr><td class="err-code c2">200</td><td>Success</td><td style="color:var(--text-secondary)">OK</td></tr>
        <tr><td class="err-code c4">400</td><td>Bad Request</td><td style="color:var(--text-secondary)">Invalid symbol/param</td></tr>
        <tr><td class="err-code c4">401</td><td>Unauthorized</td><td style="color:var(--text-secondary)">Missing API key</td></tr>
        <tr><td class="err-code c4">403</td><td>Forbidden</td><td style="color:var(--text-secondary)">Higher tier required</td></tr>
        <tr><td class="err-code c4">429</td><td>Rate Limited</td><td style="color:var(--text-secondary)">Daily limit exceeded</td></tr>
      </tbody></table></div>
    <div class="doc-section"><h3><span class="icon">⏱</span> Rate Limits</h3>
      <div class="rate-grid">
        <div class="rate-card ${userTier==='free'?'current':''}"><div class="tier-name">Explorer</div><div class="tier-val">100</div><div class="tier-unit">calls/day</div></div>
        <div class="rate-card ${userTier==='trader'?'current':''}"><div class="tier-name">Trader</div><div class="tier-val">1K</div><div class="tier-unit">calls/day</div></div>
        <div class="rate-card ${userTier==='pro'?'current':''}"><div class="tier-name">Pro</div><div class="tier-val">5K</div><div class="tier-unit">calls/day</div></div>
        <div class="rate-card ${userTier==='institutional'?'current':''}"><div class="tier-name">Inst.</div><div class="tier-val">∞</div><div class="tier-unit">unlimited</div></div>
      </div></div>`;
  el.scrollTop = 0;
}

// ============ RENDER RIGHT PANEL (RapidAPI Style) ============
function renderRight(ep) {
  const el = document.getElementById('right-content');
  const TABS = [
    {id:'params', label:`Params(${ep.params.length})`, icon:''},
    {id:'headers', label:'Headers(3)', icon:''},
    {id:'code', label:'Code Snippets', icon:''},
  ];

  let tabsHtml = TABS.map(t =>
    `<button class="rt-tab ${t.id===activeTab?'active':''}" onclick="activeTab='${t.id}';renderRight(findEp('${ep.id}'))">${t.label}</button>`
  ).join('');

  let bodyHtml = '';

  if (activeTab === 'params') {
    if (ep.params.length === 0) {
      bodyHtml = '<div class="rt-empty">No path or query parameters for this endpoint.</div>';
    } else {
      bodyHtml = '<div class="rt-params">';
      ep.params.forEach(p => {
        const val = getParamVal(ep, p.name);
        bodyHtml += `<div class="rt-param">
          <div class="rt-param-top">
            <span class="rt-param-name">${p.name} ${p.required?'<span class="rt-req">*</span>':''}</span>
            <span class="rt-param-type">${p.type}</span>
          </div>
          <input class="rt-param-input" value="${val}" placeholder="${p.default||p.name}"
            oninput="setParam('${ep.id}','${p.name}',this.value)" />
          <div class="rt-param-desc">${p.desc}</div>
        </div>`;
      });
      bodyHtml += '</div>';
    }
  } else if (activeTab === 'headers') {
    bodyHtml = `<div class="rt-params">
      <div class="rt-param">
        <div class="rt-param-top"><span class="rt-param-name">X-API-Key <span class="rt-req">*</span></span><span class="rt-param-type">string</span></div>
        <input class="rt-param-input" value="${userKey}" readonly style="color:var(--gold-primary);cursor:pointer" onclick="copyText(this.value)" />
        <div class="rt-param-desc">Your authentication key</div>
      </div>
      <div class="rt-param">
        <div class="rt-param-top"><span class="rt-param-name">Content-Type</span><span class="rt-param-type">string</span></div>
        <input class="rt-param-input" value="application/json" readonly />
        <div class="rt-param-desc">Response format</div>
      </div>
      <div class="rt-param">
        <div class="rt-param-top"><span class="rt-param-name">Accept</span><span class="rt-param-type">string</span></div>
        <input class="rt-param-input" value="application/json" readonly />
        <div class="rt-param-desc">Accept header</div>
      </div>
    </div>`;
  } else if (activeTab === 'code') {
    const LANGS = ['curl','python','javascript','go','ruby'];
    bodyHtml = `<div class="rt-lang-tabs">${LANGS.map(l=>
      `<button class="rt-lang ${l===activeLang?'active':''}" onclick="activeLang='${l}';renderRight(findEp('${ep.id}'))">${l}</button>`
    ).join('')}</div>
    <div class="rt-code-wrap">
      <button class="rt-code-copy" onclick="copyText(genCode(findEp('${ep.id}'),'${activeLang}'))">📋 Copy</button>
      <pre class="rt-code">${genCode(ep, activeLang)}</pre>
    </div>`;
  }

  // Build URL display
  const fullUrl = `${BASE}${buildUrl(ep)}`;

  el.innerHTML = `
    <div class="rt-url-bar">
      <span class="rt-method">GET</span>
      <span class="rt-url">${fullUrl}</span>
    </div>
    <div class="rt-actions">
      <button class="rt-test-btn" id="try-btn" onclick="tryIt()">▶ Test Endpoint</button>
    </div>
    <div id="rt-result"></div>
    <div class="rt-tabs">${tabsHtml}</div>
    <div class="rt-body">${bodyHtml}</div>`;
}

function setParam(epId, name, val) {
  if(!paramValues[epId]) paramValues[epId]={};
  paramValues[epId][name] = val.toUpperCase().trim();
  // Live-update URL display only
  const ep = findEp(epId);
  const urlEl = document.querySelector('.rt-url');
  if(urlEl && ep) urlEl.textContent = `${BASE}${buildUrl(ep)}`;
}

// ============ TRY IT ============
let lastResponse = '';
async function tryIt() {
  const ep = findEp(activeEpId);
  if(!ep) return;
  const btn = document.getElementById('try-btn');
  const res_el = document.getElementById('rt-result');
  btn.textContent = '⏳ Sending...'; btn.disabled = true;
  try {
    const rp = buildUrl(ep);
    const sep = rp.includes('?') ? '&' : '?';
    const url = ep.noAuth ? rp : `${rp}${sep}key=${userKey}`;
    const t0 = performance.now();
    const res = await fetch(url);
    const ms = (performance.now()-t0).toFixed(0);
    const txt = await res.text();
    let body; try{body=JSON.stringify(JSON.parse(txt),null,2)}catch{body=txt}
    lastResponse = body;
    const kb = (new Blob([txt]).size/1024).toFixed(1);
    res_el.innerHTML = `<div class="try-meta">
      <span class="try-tag ${res.ok?'ok':'err'}">${res.status}</span>
      <span class="try-tag info">⏱ ${ms}ms</span>
      <span class="try-tag info">📦 ${kb}KB</span>
      <button class="try-copy" onclick="copyText(lastResponse)">📋 Copy</button>
    </div><pre class="try-body">${body}</pre>`;
  } catch(e) {
    res_el.innerHTML = `<div class="try-meta"><span class="try-tag err">ERROR</span></div><pre class="try-body" style="color:var(--accent-red)">${e.message}</pre>`;
  }
  btn.textContent = '▶ Test Endpoint'; btn.disabled = false;
}

// ============ SELECT + INIT ============
function selectEp(id) {
  activeEpId = id;
  const ep = findEp(id);
  if(!ep) return;
  // Init default param values
  if(!paramValues[id]) {
    paramValues[id] = {};
    ep.params.forEach(p => { paramValues[id][p.name] = p.default || ''; });
  }
  activeTab = ep.params.length ? 'params' : 'code';
  renderSidebar();
  renderCenter(ep);
  renderRight(ep);
}

function filterEndpoints() { renderSidebar(document.getElementById('ep-search').value.toLowerCase()); }

async function loadUser() {
  try {
    const r = await fetch('/api/auth/me?_=' + new Date().getTime(),{credentials:'include', cache:'no-store'});
    if(!r.ok) return;
    const d = await r.json();
    userTier = d.user.tier;
    if(d.api_keys.length) userKey = d.api_keys[0].key;
    document.getElementById('topbar-user').textContent = d.user.email;
    document.getElementById('topbar-cta').textContent = 'Console';
    document.getElementById('topbar-cta').href = './account.html';
  } catch{}
}

async function init() {
  await loadUser();
  selectEp(activeEpId);
}
init();
