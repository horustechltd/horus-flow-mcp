/* ================================================================
   🦅 HORUS FLOW INTELLIGENCE — Landing Page JS
   Live data fetching + Animations + Stripe Checkout
   ================================================================ */

const API_BASE = window.location.origin;

// ============ INTERSECTION OBSERVER (Scroll Animations) ============
const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('visible');
        }
    });
}, { threshold: 0.1, rootMargin: '0px 0px -50px 0px' });

document.querySelectorAll('.animate-in').forEach(el => observer.observe(el));

// ============ SMOOTH SCROLL FOR NAV LINKS ============
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            e.preventDefault();
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    });
});

// ============ NAV SCROLL EFFECT ============
const nav = document.getElementById('main-nav');
let lastScroll = 0;
window.addEventListener('scroll', () => {
    const scroll = window.scrollY;
    if (scroll > 100) {
        nav.style.background = 'rgba(10, 10, 15, 0.95)';
        nav.style.boxShadow = '0 2px 20px rgba(0,0,0,0.3)';
    } else {
        nav.style.background = 'rgba(10, 10, 15, 0.85)';
        nav.style.boxShadow = 'none';
    }
    lastScroll = scroll;
});

// ============ LIVE DATA FETCHING ============
// Public preview endpoint: no API key in the browser, cached 30s server-side.
async function fetchLiveData() {
    try {
        const res = await fetch(`${API_BASE}/v1/public/preview`);
        if (!res.ok) throw new Error(`preview ${res.status}`);
        const p = await res.json();

        if (p.flow) {
            const tickerSignal = document.getElementById('ticker-signal');
            const tickerConf = document.getElementById('ticker-conf');
            if (tickerSignal && p.flow.signal) {
                tickerSignal.textContent = p.flow.signal;
                tickerSignal.style.color = p.flow.signal.includes('BUY') || p.flow.signal.includes('ABSORPTION')
                    ? 'var(--accent-green)'
                    : p.flow.signal.includes('DUMP') || p.flow.signal.includes('EXIT')
                    ? 'var(--accent-red)'
                    : 'var(--gold-primary)';
            }
            if (tickerConf && p.flow.confidence !== undefined) {
                tickerConf.textContent = (p.flow.confidence * 100).toFixed(0) + '%';
            }
        }

        const liveJson = document.getElementById('live-json');
        if (liveJson && (p.flow || p.cortex)) {
            liveJson.innerHTML = formatJSON({
                sample: "public preview, refreshed every 30s",
                flow: p.flow,
                cortex: p.cortex,
                composite_btc: p.composite
            });
        }

        const statSignals = document.getElementById('stat-signals');
        if (statSignals && p.composite && p.composite.composite_score !== undefined) {
            statSignals.textContent = Math.round(p.composite.composite_score);
            statSignals.title = 'Composite Intelligence Score (BTCUSDT)';
        }
    } catch (err) {
        console.log('Live data fetch info:', err.message);
        const liveJson = document.getElementById('live-json');
        if (liveJson) {
            liveJson.innerHTML = `<span class="code-comment">// Live preview unavailable right now. See /status.html</span>`;
        }
    }
}

function formatJSON(obj) {
    const lines = JSON.stringify(obj, null, 2).split('\n');
    return lines.map(line => {
        return line
            .replace(/"([^"]+)":/g, '<span class="code-gold">"$1"</span>:')
            .replace(/: "([^"]+)"/g, ': <span class="code-string">"$1"</span>')
            .replace(/: (-?\d+\.?\d*)/g, ': <span class="code-func">$1</span>');
    }).join('\n');
}

// Checkout lives in index.html (handleCheckout -> /api/billing/create-checkout-session, Stripe).
// A second handleCheckout here overrode it (deferred script) and answered "Checkout coming soon".

// ============ COUNTER ANIMATION ============
function animateCounter(el, target, suffix = '') {
    if (!el) return;
    let current = 0;
    const increment = target / 40;
    const timer = setInterval(() => {
        current += increment;
        if (current >= target) {
            current = target;
            clearInterval(timer);
        }
        el.textContent = Math.round(current) + suffix;
    }, 30);
}

// ============ INIT ============
document.addEventListener('DOMContentLoaded', () => {
    // Fetch live data immediately
    fetchLiveData();
    
    // Refresh every 30 seconds
    setInterval(fetchLiveData, 30000);
    
    // Animate stats on visible
    const statsObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                animateCounter(document.getElementById('stat-accuracy'), 63, '%');
                statsObserver.disconnect();
            }
        });
    });
    
    const statsEl = document.querySelector('.hero-stats');
    if (statsEl) statsObserver.observe(statsEl);
});
