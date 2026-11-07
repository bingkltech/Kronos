// Auto-poll scalper status alongside main dashboard
function updateScalperUI(s) {
    if (!s || !s.success) return;

    // 1. Update Paper Dashboard Scalper Card
    const badge = document.getElementById('scalper-status-badge');
    const batchBadge = document.getElementById('scalper-batch-badge');
    const emptyState = document.getElementById('scalper-empty-state');
    const activeState = document.getElementById('scalper-active-state');

    // 2. Update Live Dashboard Scalper Card
    const liveBadge = document.getElementById('live-scalper-status-badge');
    const liveEmptyState = document.getElementById('live-scalper-empty-state');
    const liveActiveState = document.getElementById('live-scalper-active-state');

    if (batchBadge) {
        const closed = s.total_closed_scalps || 0;
        const batchProgress = closed % 10;
        batchBadge.textContent = 'Batch Learning: ' + batchProgress + '/10 (' + (s.learning_audits_count || 0) + ' Batches Completed)';
    }

    if (s.active_scalp) {
        const p = s.active_scalp;

        // Paper Card Elements
        if (badge) {
            badge.innerHTML = '<span class="pulse-dot"></span> SCALPING ACTIVE: ' + p.symbol;
            badge.style.color = '#3fb950';
            badge.style.borderColor = 'rgba(63, 185, 80, 0.5)';
        }
        if (emptyState) emptyState.style.display = 'none';
        if (activeState) activeState.style.display = 'block';

        const setTxt = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
        setTxt('scalper-symbol', p.symbol);
        setTxt('scalper-pos-id', p.position_id);
        setTxt('scalper-duration', p.duration_minutes + 'm');
        setTxt('scalper-entry', '$' + p.entry_price);
        setTxt('scalper-tp', '$' + p.take_profit);
        setTxt('scalper-sl', '$' + p.stop_loss);
        setTxt('scalper-notional', '$' + p.notional_usd.toFixed(2));
        setTxt('scalper-mfe', p.highest_price ? '$' + p.highest_price : 'Tracking...');
        setTxt('scalper-mae', p.lowest_price ? '$' + p.lowest_price : 'Tracking...');

        const sideEl = document.getElementById('scalper-side');
        if (sideEl) {
            sideEl.textContent = p.side;
            sideEl.style.color = p.side === 'BUY' ? '#3fb950' : '#f85149';
            sideEl.style.borderColor = p.side === 'BUY' ? 'rgba(63, 185, 80, 0.4)' : 'rgba(248, 81, 73, 0.4)';
        }

        // Live Real Trading Card Elements
        if (liveBadge) {
            liveBadge.innerHTML = '<span class="pulse-dot" style="background: #00E676;"></span> LIVE SCALP ACTIVE: ' + p.symbol;
            liveBadge.style.color = '#00E676';
            liveBadge.style.borderColor = 'rgba(0, 230, 118, 0.5)';
        }
        if (liveEmptyState) liveEmptyState.style.display = 'none';
        if (liveActiveState) liveActiveState.style.display = 'block';

        setTxt('live-scalper-symbol', p.symbol);
        setTxt('live-scalper-pos-id', p.position_id);
        setTxt('live-scalper-duration', p.duration_minutes + 'm');
        setTxt('live-scalper-entry', '$' + p.entry_price);
        setTxt('live-scalper-tp', '$' + p.take_profit);
        setTxt('live-scalper-sl', '$' + p.stop_loss);
        setTxt('live-scalper-notional', '$' + p.notional_usd.toFixed(2));
        setTxt('live-scalper-mfe', p.highest_price ? '$' + p.highest_price : 'Tracking...');
        setTxt('live-scalper-mae', p.lowest_price ? '$' + p.lowest_price : 'Tracking...');

        const liveSideEl = document.getElementById('live-scalper-side');
        if (liveSideEl) {
            liveSideEl.textContent = p.side;
            liveSideEl.style.color = p.side === 'BUY' ? '#3fb950' : '#f85149';
            liveSideEl.style.borderColor = p.side === 'BUY' ? 'rgba(63, 185, 80, 0.4)' : 'rgba(248, 81, 73, 0.4)';
        }
    } else {
        if (badge) {
            badge.textContent = 'SEARCHING FOR APEX SETUP';
            badge.style.color = '#f0883e';
            badge.style.borderColor = 'rgba(240, 136, 62, 0.4)';
        }
        if (emptyState) emptyState.style.display = 'block';
        if (activeState) activeState.style.display = 'none';

        if (liveBadge) {
            liveBadge.textContent = 'LIVE SCALPER: STANDBY / SEARCHING';
            liveBadge.style.color = '#ff7b72';
            liveBadge.style.borderColor = 'rgba(255, 82, 82, 0.4)';
        }
        if (liveEmptyState) liveEmptyState.style.display = 'block';
        if (liveActiveState) liveActiveState.style.display = 'none';
    }
}

async function loadScalperStatus() {
    try {
        const resp = await axios.get('/api/scalper/status');
        updateScalperUI(resp.data);
    } catch (e) {
        console.error('Failed to load scalper status:', e);
    }
}

// Auto-poll scalper status alongside main dashboard
setInterval(loadScalperStatus, 5000);
document.addEventListener('DOMContentLoaded', loadScalperStatus);
