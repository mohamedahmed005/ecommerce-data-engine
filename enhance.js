/* enhance.js — additive UX layer for landing / dashboard / chat.
   Wraps existing functions; never replaces markup or API logic. Every feature is try/catch-guarded. */
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const guard = fn => (...a) => { try { return fn(...a); } catch (e) { console.warn('[enhance]', e); } };
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
    del(k) { try { localStorage.removeItem(k); } catch {} }
  };
  const BASE = location.protocol.startsWith('http') ? location.origin : 'http://localhost:8000';
  const ready = fn => document.readyState === 'complete' ? fn() : document.addEventListener('DOMContentLoaded', fn);

  /* ---------- shared CSS ---------- */
  const css = document.createElement('style');
  css.textContent = `
  .enh-toasts{position:fixed;right:16px;bottom:16px;z-index:9999;display:flex;flex-direction:column;gap:8px}
  .enh-toast{background:#111827;border:1px solid #334155;color:#e2e8f0;padding:10px 14px;border-radius:12px;font-size:12px;box-shadow:0 10px 30px rgba(0,0,0,.4);animation:enhIn .25s ease}
  .enh-toast.err{border-color:#f43f5e66;color:#fda4af}.enh-toast.ok{border-color:#10b98166;color:#6ee7b7}
  @keyframes enhIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
  @keyframes enhShimmer{0%{background-position:-200% 0}100%{background-position:200% 0}}
  .enh-loading .enh-skel{color:transparent!important;border-radius:8px;background:linear-gradient(90deg,#1e293b 25%,#334155 50%,#1e293b 75%);background-size:200% 100%;animation:enhShimmer 1.2s infinite}
  .enh-reveal{opacity:0;transform:translateY(16px);transition:opacity .6s ease,transform .6s ease}.enh-reveal.in{opacity:1;transform:none}
  .enh-lift{transition:transform .2s ease,box-shadow .2s ease}.enh-lift:hover{transform:translateY(-2px);box-shadow:0 12px 28px rgba(0,0,0,.35)}
  th.enh-sort{cursor:pointer;user-select:none}th.enh-sort:hover{color:#fff}
  th.enh-sort[data-dir="1"]::after{content:" ▲";font-size:9px}th.enh-sort[data-dir="-1"]::after{content:" ▼";font-size:9px}
  ::-webkit-scrollbar{width:8px;height:8px}::-webkit-scrollbar-thumb{background:#334155;border-radius:8px}
  @media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}`;
  document.head.appendChild(css);

  const toast = (msg, type = '') => {
    let w = $('.enh-toasts');
    if (!w) { w = document.createElement('div'); w.className = 'enh-toasts'; document.body.appendChild(w); }
    const t = document.createElement('div'); t.className = 'enh-toast ' + type; t.textContent = msg; w.appendChild(t);
    setTimeout(() => { t.style.transition = 'opacity .3s'; t.style.opacity = '0'; setTimeout(() => t.remove(), 300); }, 3200);
  };

  function countUp(el) {
    if (!el) return;
    const txt = el.textContent, m = txt.match(/\d[\d,]*\.?\d*/);
    if (!m || el.dataset.enhFinal === txt) return;
    el.dataset.enhFinal = txt;
    const raw = m[0], target = parseFloat(raw.replace(/,/g, ''));
    if (!isFinite(target)) return;
    const dec = (raw.split('.')[1] || '').length, comma = raw.includes(',');
    const fmt = v => comma ? v.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec }) : v.toFixed(dec);
    cancelAnimationFrame(el._enhRaf);
    const t0 = performance.now(), dur = 800;
    const step = now => {
      const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      if (p < 1) { el.textContent = txt.replace(raw, fmt(target * e)); el._enhRaf = requestAnimationFrame(step); }
      else el.textContent = txt;
    };
    el._enhRaf = requestAnimationFrame(step);
  }

  /* ---------- sortable + searchable tables ---------- */
  function tableTools(tbodyId, searchLabel) {
    const tb = $('#' + tbodyId); if (!tb) return;
    const table = tb.closest('table'); let q = '', col = -1, dir = 1;
    const apply = () => $$('tr', tb).forEach(tr => { tr.style.display = !q || tr.textContent.toLowerCase().includes(q) ? '' : 'none'; });
    const clean = t => t.replace(/R\$|%|d$/g, '').replace(/,/g, '').trim();
    const isNum = t => /^-?\d+(\.\d+)?$/.test(clean(t));
    $$('thead th', table).forEach((th, i) => {
      th.classList.add('enh-sort'); th.title = 'Click to sort';
      th.addEventListener('click', () => {
        dir = col === i ? -dir : 1; col = i;
        $$('thead th', table).forEach(h => delete h.dataset.dir); th.dataset.dir = dir;
        const rows = $$('tr', tb).filter(r => r.children.length > 1);
        rows.sort((a, b) => {
          const x = (a.children[i]?.textContent || '').trim(), y = (b.children[i]?.textContent || '').trim();
          return (isNum(x) && isNum(y) ? clean(x) - clean(y) : x.localeCompare(y)) * dir;
        });
        rows.forEach(r => tb.appendChild(r));
      });
    });
    if (searchLabel) {
      const inp = document.createElement('input');
      inp.type = 'search'; inp.placeholder = searchLabel; inp.setAttribute('aria-label', searchLabel);
      inp.className = 'mb-3 w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 no-print';
      inp.addEventListener('input', () => { q = inp.value.trim().toLowerCase(); apply(); });
      table.parentElement.before(inp);
    }
    new MutationObserver(apply).observe(tb, { childList: true });
  }

  /* =====================  DASHBOARD  ===================== */
  const dashboard = guard(() => {
    if (typeof window.loadDashboardData !== 'function') return;
    const orig = window.loadDashboardData;
    ['kpi-revenue', 'kpi-orders', 'kpi-delivery', 'kpi-late', 'kpi-rating', 'kpi-reviews', 'kpi-lowstock', 'kpi-outofstock', 'selected-month-rev', 'selected-year-rev']
      .forEach(id => $('#' + id)?.classList.add('enh-skel'));

    // header controls: last-updated + live refresh
    const status = $('#api-status');
    const upd = document.createElement('span'); upd.id = 'enh-updated'; upd.className = 'text-[11px] text-slate-500 hidden sm:inline';
    const live = document.createElement('button');
    live.className = 'px-3 py-2 rounded-lg text-xs font-medium border transition'; live.title = 'Auto-refresh every 60s';
    let liveOn = store.get('enh.live', false), timer = null;
    const paintLive = () => {
      live.innerHTML = `<i class="fa-solid fa-satellite-dish mr-1.5"></i> Live: ${liveOn ? 'ON' : 'OFF'}`;
      live.className = 'px-3 py-2 rounded-lg text-xs font-medium border transition ' + (liveOn ? 'bg-emerald-600/20 border-emerald-500/40 text-emerald-300' : 'bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700');
    };
    const setTimer = () => { clearInterval(timer); if (liveOn) timer = setInterval(() => { if (!document.hidden) window.loadDashboardData(); }, 60000); };
    live.onclick = () => { liveOn = !liveOn; store.set('enh.live', liveOn); paintLive(); setTimer(); toast(liveOn ? 'Live refresh enabled (60s)' : 'Live refresh disabled', 'ok'); };
    paintLive(); setTimer();
    if (status) { status.before(upd); status.before(live); }

    // wrap loader: skeletons, persistence, count-up, error feedback
    let first = true, wasFailing = false;
    window.loadDashboardData = async function (...a) {
      if (first) {
        first = false;
        const s = store.get('enh.dash', {});
        if (s.syn === false && typeof includeSynthetic !== 'undefined') {
          includeSynthetic = false;
          const A = $('#btn-ds-all'), R = $('#btn-ds-real');
          if (A && R) { const t = A.className; A.className = R.className; R.className = t; }
        }
        if (/^\d{4}$/.test(s.year || '') && typeof selectedYear !== 'undefined') selectedYear = s.year;
      }
      document.body.classList.add('enh-loading');
      try { return await orig.apply(this, a); }
      finally {
        document.body.classList.remove('enh-loading');
        guard(() => {
          const failed = $('#kpi-revenue').textContent.trim() === '--';
          if (failed && !wasFailing) toast('Could not load data — is the API running on port 8000?', 'err');
          wasFailing = failed;
          if (!failed) {
            upd.textContent = 'Updated ' + new Date().toLocaleTimeString();
            store.set('enh.dash', { syn: includeSynthetic, year: selectedYear });
            ['kpi-revenue', 'kpi-orders', 'kpi-delivery', 'kpi-late', 'kpi-rating', 'kpi-reviews', 'kpi-lowstock', 'kpi-outofstock'].forEach(id => countUp($('#' + id)));
          }
        })();
      }
    };

    // MoM and YoY deltas
    const mk = (afterId, id) => { const d = document.createElement('p'); d.id = id; d.className = 'text-[11px] mt-0.5'; $('#' + afterId)?.after(d); return d; };
    const mom = mk('selected-month-orders', 'enh-mom'), yoy = mk('selected-year-orders', 'enh-yoy');
    const delta = (cur, prev, label) => {
      if (!(prev > 0)) return '';
      const p = (cur - prev) / prev * 100, up = p >= 0;
      return `<span class="${up ? 'text-emerald-400' : 'text-rose-400'} font-semibold">${up ? '▲' : '▼'} ${Math.abs(p).toFixed(1)}%</span> <span class="text-slate-500">${label}</span>`;
    };
    const ouc = window.updateSelectedCards;
    if (typeof ouc === 'function') window.updateSelectedCards = function (i) {
      const r = ouc.apply(this, arguments);
      guard(() => {
        const item = filteredMonthlyData[i], prev = filteredMonthlyData[i - 1];
        mom.innerHTML = item && prev ? delta(+item.total_sales, +prev.total_sales, 'vs ' + String(prev.month_name).substring(0, 3)) : '';
        const c = item && yearlyMap[String(item.year)], p = item && yearlyMap[String(item.year - 1)];
        yoy.innerHTML = c && p ? (c.months_count === p.months_count ? delta(c.total_sales, p.total_sales, 'vs ' + p.year) : '<span class="text-slate-500">partial year — YoY n/a</span>') : '';
      })();
      return r;
    };

    // chart PNG download
    const badge = $('#chart-badge');
    if (badge) {
      const wrap = document.createElement('div'); wrap.className = 'flex items-center gap-2 no-print';
      const b = document.createElement('button'); b.className = 'text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-2.5 py-1 rounded-md border border-slate-700'; b.innerHTML = '<i class="fa-solid fa-image mr-1"></i>PNG';
      b.onclick = guard(() => { const a = document.createElement('a'); a.href = salesChartInstance.toBase64Image(); a.download = 'revenue_chart.png'; a.click(); });
      badge.replaceWith(wrap); wrap.append(badge, b);
    }

    tableTools('sellers-tbody', 'Filter sellers by ID, city or state…');
    tableTools('categories-tbody', 'Filter categories…');
    tableTools('low-stock-tbody', 'Filter low-stock products…');
    tableTools('states-tbody');
    $$('main > div, main .bg-cardBg').forEach(el => el.classList.add('enh-lift'));
    $('#timeline-slider')?.setAttribute('title', 'Tip: use ← → keys to step through months');

    // keyboard shortcuts
    addEventListener('keydown', e => {
      const t = e.target, s = $('#timeline-slider');
      if (/INPUT|TEXTAREA|SELECT/.test(t.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        const v = +s.value + (e.key === 'ArrowRight' ? 1 : -1);
        if (v < +s.min || v > +s.max) return;
        s.value = v; window.handleSliderChange(v); e.preventDefault();
      } else if (e.key === 'r') window.loadDashboardData();
    });

    // background health watchdog: auto-recover when the API comes back
    setInterval(async () => {
      if (document.hidden || typeof window.checkApiHealth !== 'function') return;
      await window.checkApiHealth();
      if (/Connected/.test(status?.textContent || '') && $('#kpi-revenue').textContent.trim() === '--') {
        toast('API is back online — reloading data', 'ok'); window.loadDashboardData();
      }
    }, 30000);
  });

  /* =====================  LANDING  ===================== */
  const landing = guard(() => {
    const cta = $('main a[href="/dashboard"]'); const wrap = cta?.parentElement;
    if (!wrap || !$('h1') || $('canvas')) return;
    const strip = document.createElement('div');
    strip.className = 'mt-10 grid grid-cols-2 md:grid-cols-4 gap-4 max-w-4xl mx-auto';
    const defs = [['rev', 'Total Revenue', 'text-indigo-300'], ['ord', 'Orders', 'text-cyan-300'], ['rate', 'Avg Rating', 'text-amber-300'], ['late', 'Late Deliveries', 'text-rose-300']];
    strip.innerHTML = defs.map(([k, l, c]) => `<div class="bg-white/5 border border-white/10 rounded-2xl p-4 enh-lift"><p class="text-[11px] uppercase tracking-wider text-slate-400">${l}</p><p data-k="${k}" class="text-2xl font-extrabold mt-1 ${c}">—</p></div>`).join('');
    wrap.after(strip);
    const dot = $('.animate-pulse');
    fetch(BASE + '/api/analytics/kpis?include_synthetic=true').then(r => r.json()).then(d => {
      const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 2 });
      const v = { rev: 'R$ ' + compact.format(d.sales.total_revenue), ord: d.sales.total_orders.toLocaleString('en-US'), rate: d.reviews.avg_review_score + ' / 5', late: d.delivery.late_order_percentage + '%' };
      Object.entries(v).forEach(([k, val]) => { const el = $(`[data-k="${k}"]`, strip); el.textContent = val; countUp(el); });
    }).catch(() => {
      $$('[data-k]', strip).forEach(el => el.textContent = 'n/a');
      if (dot) { dot.className = dot.className.replace('bg-emerald-400', 'bg-rose-400'); dot.parentElement.title = 'API appears offline'; }
    });
    const cards = $$('.backdrop-blur-sm');
    cards.forEach(c => c.classList.add('enh-reveal', 'enh-lift'));
    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }), { threshold: .15 });
      cards.forEach((c, i) => { c.style.transitionDelay = i * 90 + 'ms'; io.observe(c); });
    } else cards.forEach(c => c.classList.add('in'));
  });

  /* =====================  CHAT  ===================== */
  const chat = guard(() => {
    const box = $('#chat-messages'), input = $('#chat-input'), form = $('#chat-form');
    if (!box || !input || !form) return;
    const saved = store.get('enh.chat', ''); let live = false;
    const hist = store.get('enh.hist', []); let hi = hist.length;

    // history + duplicate-send guard
    const oSubmit = window.handleChatSubmit;
    window.handleChatSubmit = function (e) {
      if ($('[id^="loading-"]')) { e?.preventDefault?.(); toast('Please wait for the current answer…'); return; }
      const v = input.value.trim();
      if (v && hist[hist.length - 1] !== v) { hist.push(v); if (hist.length > 50) hist.shift(); store.set('enh.hist', hist); }
      hi = hist.length;
      return oSubmit.apply(this, arguments);
    };
    input.addEventListener('keydown', e => {
      if (e.key === 'ArrowUp' && hist.length) { hi = Math.max(0, hi - 1); input.value = hist[hi]; e.preventDefault(); }
      else if (e.key === 'ArrowDown' && hist.length) { hi = Math.min(hist.length, hi + 1); input.value = hist[hi] || ''; e.preventDefault(); }
    });
    addEventListener('keydown', e => { if (e.key === '/' && document.activeElement !== input && !e.ctrlKey && !e.metaKey) { e.preventDefault(); input.focus(); } });

    // decorate bot answers: auto text direction (Arabic), time, copy
    const decorate = guard(() => {
      $$(':scope > div', box).forEach(n => {
        if (n.id?.startsWith('loading-') || n.dataset.enh) return;
        const ans = $('.leading-relaxed', n);
        if (!ans) return;
        n.dataset.enh = '1'; ans.setAttribute('dir', 'auto');
        const bubble = ans.parentElement;
        if (!$('.enh-meta', bubble)) {
          const m = document.createElement('div');
          m.className = 'enh-meta mt-2 flex items-center gap-3 text-[10px] text-slate-500';
          m.innerHTML = `<span>${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span><button type="button" class="enh-copy hover:text-slate-200"><i class="fa-regular fa-copy mr-1"></i>Copy</button>`;
          bubble.appendChild(m);
        }
      });
    });
    box.addEventListener('click', e => {
      const b = e.target.closest('.enh-copy'); if (!b) return;
      const c = b.closest('.bg-cardBg').cloneNode(true); $('.enh-meta', c)?.remove();
      navigator.clipboard?.writeText(c.textContent.replace(/\s+\n/g, '\n').trim()).then(() => toast('Copied to clipboard', 'ok'), () => toast('Copy failed', 'err'));
    });

    // scroll-to-bottom button
    const main = box.parentElement; main.style.position = 'relative';
    const down = document.createElement('button');
    down.type = 'button'; down.innerHTML = '<i class="fa-solid fa-arrow-down"></i>'; down.title = 'Jump to latest';
    down.className = 'hidden absolute right-6 bottom-24 bg-blue-600 hover:bg-blue-500 text-white w-9 h-9 rounded-full shadow-lg z-10';
    down.onclick = () => box.scrollTo({ top: box.scrollHeight, behavior: 'smooth' });
    main.appendChild(down);
    box.addEventListener('scroll', () => down.classList.toggle('hidden', box.scrollHeight - box.scrollTop - box.clientHeight < 200));

    // mobile quick-prompt chips (sidebar is hidden < md)
    const chips = document.createElement('div');
    chips.className = 'md:hidden flex gap-2 overflow-x-auto px-4 py-2 bg-slate-950 border-t border-slate-800';
    $$('aside button[onclick^="sendQuickPrompt"]').forEach(b => {
      const c = b.cloneNode(true); c.className = 'whitespace-nowrap bg-slate-900 border border-slate-700 rounded-full px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800'; chips.appendChild(c);
    });
    if (chips.children.length) form.parentElement.before(chips);

    // export + clear
    const clr = $('button[onclick="clearChat()"]');
    if (clr) {
      const ex = document.createElement('button');
      ex.type = 'button'; ex.className = 'bg-slate-800 hover:bg-slate-700 text-slate-200 px-3.5 py-2 rounded-lg text-xs font-medium transition border border-slate-700 flex items-center';
      ex.innerHTML = '<i class="fa-solid fa-download mr-1.5 text-emerald-400"></i> Export';
      ex.onclick = () => {
        const c = box.cloneNode(true); $$('.enh-meta', c).forEach(x => x.remove());
        const url = URL.createObjectURL(new Blob([c.innerText || c.textContent], { type: 'text/plain;charset=utf-8' }));
        const a = document.createElement('a'); a.href = url; a.download = 'warehouse_chat.txt'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      };
      clr.before(ex);
    }
    const oClear = window.clearChat;
    window.clearChat = function () { if (live) store.del('enh.chat'); return oClear.apply(this, arguments); };

    // restore previous session AFTER the page's own init (which calls clearChat)
    guard(() => {
      if (saved) { box.innerHTML = saved; box.scrollTop = box.scrollHeight; }
      live = true; decorate();
      new MutationObserver(() => {
        decorate();
        const c = box.cloneNode(true); $$('[id^="loading-"]', c).forEach(x => x.remove());
        if (c.innerHTML.length < 400000) store.set('enh.chat', c.innerHTML);
      }).observe(box, { childList: true });
      if (matchMedia('(pointer:fine)').matches) input.focus();
    })();
  });

  // dashboard must wrap before the page's own DOMContentLoaded load; chat restores after its init
  dashboard(); landing(); ready(chat);
})();
