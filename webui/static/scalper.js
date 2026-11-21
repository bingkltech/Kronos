/**
 * Kronos Lightning Scalper (Dedicated High-Frequency Alpha & Guardrails Engine)
 * Controls Whole-Binance universal scanning, 3 independent strategies, and ringfenced guardrails.
 */

// Toast notification helper
function showScalperToast(msg, isSuccess = true) {
    const container = document.getElementById('status-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.style.background = isSuccess ? '#238636' : '#da3633';
    toast.style.color = '#fff';
    toast.style.padding = '12px 18px';
    toast.style.borderRadius = '6px';
    toast.style.marginBottom = '10px';
    toast.style.fontSize = '13px';
    toast.style.fontWeight = '700';
    toast.style.boxShadow = '0 8px 24px rgba(0,0,0,0.5)';
    toast.style.border = '1px solid ' + (isSuccess ? '#2ea043' : '#f85149');
    toast.style.display = 'flex';
    toast.style.alignItems = 'center';
    toast.style.gap = '8px';
    toast.innerHTML = (isSuccess ? '✅ ' : '⚠️ ') + msg;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.4s ease';
        setTimeout(() => toast.remove(), 400);
    }, 3500);
}

// 1. Load Scalper Configuration from Backend
async function loadScalperConfig() {
    try {
        const resp = await axios.get('/api/lightning/config');
        if (!resp.data || !resp.data.success || !resp.data.config) return;
        const cfg = resp.data.config;

        // Master switch & Probability Sieve
        const minProb = cfg.min_win_probability_pct !== undefined ? cfg.min_win_probability_pct : 85.0;
        const sliderProb = document.getElementById('input-min-win-prob');
        const valProb = document.getElementById('val-min-win-prob');
        const badgeProb = document.getElementById('scalper-win-gate-badge');
        if (sliderProb) sliderProb.value = minProb;
        if (valProb) valProb.textContent = minProb.toFixed(1) + '%';
        if (badgeProb) badgeProb.textContent = '≥ ' + minProb.toFixed(1) + '% Prob';

        const chkEnabled = document.getElementById('check-scalper-enabled');
        if (chkEnabled) chkEnabled.checked = cfg.enabled !== false;

        const masterBadge = document.getElementById('scalper-master-badge');
        if (masterBadge) {
            if (cfg.enabled !== false) {
                masterBadge.innerHTML = '<span class="pulse-dot" style="background: #00e5ff;"></span> LIGHTNING SCALPER ACTIVE';
                masterBadge.style.color = '#00e5ff';
            } else {
                masterBadge.innerHTML = '⏸️ SCALPER PAUSED';
                masterBadge.style.color = '#8b949e';
            }
        }

        // Section 1: Execution Rules & Targets
        const exec = cfg.execution_targets || {};
        if (document.getElementById('input-tp-pct') && exec.take_profit_net_pct)
            document.getElementById('input-tp-pct').value = exec.take_profit_net_pct;
        if (document.getElementById('input-ratchet-pct') && exec.fast_profit_ratchet_pct)
            document.getElementById('input-ratchet-pct').value = exec.fast_profit_ratchet_pct;
        if (document.getElementById('input-sl-pct') && exec.stop_loss_pct)
            document.getElementById('input-sl-pct').value = exec.stop_loss_pct;
        if (document.getElementById('input-max-duration') && exec.max_duration_seconds)
            document.getElementById('input-max-duration').value = exec.max_duration_seconds;
        if (document.getElementById('input-order-type'))
            document.getElementById('input-order-type').value = exec.maker_first_pricing ? 'maker_first' : 'taker_immediate';

        // Section 2: Strategies
        const strats = cfg.strategies || {};
        // Strat A: Liquidation
        const liq = strats.liquidation_vacuum_rebound || {};
        if (document.getElementById('check-strat-liq'))
            document.getElementById('check-strat-liq').checked = liq.enabled !== false;
        if (document.getElementById('input-strat-liq-min') && liq.min_liquidation_usd)
            document.getElementById('input-strat-liq-min').value = liq.min_liquidation_usd;
        if (document.getElementById('input-strat-liq-wick') && liq.rejection_wick_ratio)
            document.getElementById('input-strat-liq-wick').value = liq.rejection_wick_ratio;

        // Strat B: Lead-Lag
        const leadlag = strats.cross_asset_lead_lag || {};
        if (document.getElementById('check-strat-leadlag'))
            document.getElementById('check-strat-leadlag').checked = leadlag.enabled !== false;
        if (document.getElementById('input-strat-leadlag-spike') && leadlag.btc_velocity_spike_pct)
            document.getElementById('input-strat-leadlag-spike').value = leadlag.btc_velocity_spike_pct;
        if (document.getElementById('input-strat-leadlag-lag') && leadlag.max_lag_delay_ms)
            document.getElementById('input-strat-leadlag-lag').value = leadlag.max_lag_delay_ms;

        // Strat C: Stoikov
        const stoikov = strats.iceberg_shield_stoikov || {};
        if (document.getElementById('check-strat-stoikov'))
            document.getElementById('check-strat-stoikov').checked = stoikov.enabled !== false;
        if (document.getElementById('input-strat-stoikov-obi') && stoikov.min_obi_threshold)
            document.getElementById('input-strat-stoikov-obi').value = stoikov.min_obi_threshold;
        if (document.getElementById('input-strat-stoikov-skew') && stoikov.min_skew_bps)
            document.getElementById('input-strat-stoikov-skew').value = stoikov.min_skew_bps;

        // Section 3: Guardrails
        const guards = cfg.guardrails || {};
        const marginVal = guards.ringfenced_margin_usd || 20.0;
        const levVal = guards.isolated_leverage || 4;
        if (document.getElementById('input-guard-margin'))
            document.getElementById('input-guard-margin').value = marginVal;
        if (document.getElementById('input-guard-leverage'))
            document.getElementById('input-guard-leverage').value = levVal;
        if (document.getElementById('input-guard-daily-loss') && guards.daily_loss_circuit_breaker_usd)
            document.getElementById('input-guard-daily-loss').value = guards.daily_loss_circuit_breaker_usd;
        if (document.getElementById('input-guard-consec-loss') && guards.consecutive_loss_quarantine_count)
            document.getElementById('input-guard-consec-loss').value = guards.consecutive_loss_quarantine_count;
        if (document.getElementById('input-guard-cooldown') && guards.post_exit_cooldown_seconds)
            document.getElementById('input-guard-cooldown').value = guards.post_exit_cooldown_seconds;
        if (document.getElementById('input-guard-min-vol') && guards.min_symbol_24h_volume_usd)
            document.getElementById('input-guard-min-vol').value = guards.min_symbol_24h_volume_usd;

        const marginBadge = document.getElementById('scalper-margin-badge');
        if (marginBadge) {
            marginBadge.textContent = '$' + Number(marginVal).toFixed(2) + ' Isolated · ' + levVal + 'x';
        }

    } catch (e) {
        console.error('Failed to load scalper config:', e);
    }
}

// 2. Save Scalper Configuration to Backend
async function saveScalperConfig() {
    try {
        const payload = {
            enabled: document.getElementById('check-scalper-enabled') ? document.getElementById('check-scalper-enabled').checked : true,
            min_win_probability_pct: parseFloat(document.getElementById('input-min-win-prob').value || 85.0),
            execution_targets: {
                take_profit_net_pct: parseFloat(document.getElementById('input-tp-pct').value || 0.55),
                fast_profit_ratchet_pct: parseFloat(document.getElementById('input-ratchet-pct').value || 0.25),
                stop_loss_pct: parseFloat(document.getElementById('input-sl-pct').value || 0.60),
                max_duration_seconds: parseInt(document.getElementById('input-max-duration').value || 180),
                maker_first_pricing: document.getElementById('input-order-type').value === 'maker_first'
            },
            strategies: {
                liquidation_vacuum_rebound: {
                    enabled: document.getElementById('check-strat-liq').checked,
                    min_liquidation_usd: parseFloat(document.getElementById('input-strat-liq-min').value || 50000.0),
                    rejection_wick_ratio: parseFloat(document.getElementById('input-strat-liq-wick').value || 0.35)
                },
                cross_asset_lead_lag: {
                    enabled: document.getElementById('check-strat-leadlag').checked,
                    btc_velocity_spike_pct: parseFloat(document.getElementById('input-strat-leadlag-spike').value || 0.40),
                    max_lag_delay_ms: parseInt(document.getElementById('input-strat-leadlag-lag').value || 2500)
                },
                iceberg_shield_stoikov: {
                    enabled: document.getElementById('check-strat-stoikov').checked,
                    min_obi_threshold: parseFloat(document.getElementById('input-strat-stoikov-obi').value || 0.40),
                    min_skew_bps: parseFloat(document.getElementById('input-strat-stoikov-skew').value || 0.20)
                }
            },
            guardrails: {
                ringfenced_margin_usd: parseFloat(document.getElementById('input-guard-margin').value || 20.0),
                isolated_leverage: parseInt(document.getElementById('input-guard-leverage').value || 4),
                daily_loss_circuit_breaker_usd: parseFloat(document.getElementById('input-guard-daily-loss').value || 3.0),
                consecutive_loss_quarantine_count: parseInt(document.getElementById('input-guard-consec-loss').value || 2),
                post_exit_cooldown_seconds: parseInt(document.getElementById('input-guard-cooldown').value || 900),
                min_symbol_24h_volume_usd: parseFloat(document.getElementById('input-guard-min-vol').value || 15000000.0)
            }
        };

        const resp = await axios.post('/api/lightning/config', payload);
        if (resp.data && resp.data.success) {
            showScalperToast('Lightning Scalper rules, strategies & guardrails saved!');
            loadScalperConfig();
            loadScalperRadar();
        } else {
            showScalperToast('Failed to save config: ' + (resp.data.error || 'Unknown'), false);
        }
    } catch (e) {
        console.error('Save scalper config error:', e);
        showScalperToast('Error saving scalper config: ' + e.message, false);
    }
}

// 3. Reset Defaults to Institutional Settings
function resetScalperDefaults() {
    if (!confirm('Reset all Lightning Scalper rules, strategies, and guardrails to institutional defaults?')) return;

    if (document.getElementById('input-min-win-prob')) document.getElementById('input-min-win-prob').value = 65.0;
    if (document.getElementById('input-tp-pct')) document.getElementById('input-tp-pct').value = 1.10;
    if (document.getElementById('input-ratchet-pct')) document.getElementById('input-ratchet-pct').value = 0.80;
    if (document.getElementById('input-sl-pct')) document.getElementById('input-sl-pct').value = 0.70;
    if (document.getElementById('input-max-duration')) document.getElementById('input-max-duration').value = 600;
    if (document.getElementById('input-order-type')) document.getElementById('input-order-type').value = 'maker_first';
    if (document.getElementById('check-scalper-enabled')) document.getElementById('check-scalper-enabled').checked = true;

    if (document.getElementById('check-strat-liq')) document.getElementById('check-strat-liq').checked = true;
    if (document.getElementById('input-strat-liq-min')) document.getElementById('input-strat-liq-min').value = 75000;
    if (document.getElementById('input-strat-liq-wick')) document.getElementById('input-strat-liq-wick').value = 0.40;

    if (document.getElementById('check-strat-leadlag')) document.getElementById('check-strat-leadlag').checked = true;
    if (document.getElementById('input-strat-leadlag-spike')) document.getElementById('input-strat-leadlag-spike').value = 0.45;
    if (document.getElementById('input-strat-leadlag-lag')) document.getElementById('input-strat-leadlag-lag').value = 3500;

    if (document.getElementById('check-strat-stoikov')) document.getElementById('check-strat-stoikov').checked = true;
    if (document.getElementById('input-strat-stoikov-obi')) document.getElementById('input-strat-stoikov-obi').value = 0.45;
    if (document.getElementById('input-strat-stoikov-skew')) document.getElementById('input-strat-stoikov-skew').value = 0.25;

    if (document.getElementById('input-guard-margin')) document.getElementById('input-guard-margin').value = 20.0;
    if (document.getElementById('input-guard-leverage')) document.getElementById('input-guard-leverage').value = 4;
    if (document.getElementById('input-guard-daily-loss')) document.getElementById('input-guard-daily-loss').value = 3.0;
    if (document.getElementById('input-guard-consec-loss')) document.getElementById('input-guard-consec-loss').value = 2;
    if (document.getElementById('input-guard-cooldown')) document.getElementById('input-guard-cooldown').value = 900;
    if (document.getElementById('input-guard-min-vol')) document.getElementById('input-guard-min-vol').value = 50000000;

    saveScalperConfig();
}

// 4. Load Whole-Binance Live Scanner Radar
async function loadScalperRadar() {
    const tbody = document.getElementById('scalper-radar-tbody');
    const badge = document.getElementById('scalper-radar-count-badge');
    if (!tbody) return;

    try {
        const resp = await axios.get('/api/lightning/radar');
        if (!resp.data || !resp.data.success || !resp.data.radar) return;
        const items = resp.data.radar;

        if (badge) {
            badge.textContent = `${resp.data.qualified_count} Candidates Qualified (≥${resp.data.min_win_probability_pct}%)`;
            badge.style.color = resp.data.qualified_count > 0 ? '#00E676' : '#d29922';
            badge.style.background = resp.data.qualified_count > 0 ? 'rgba(0, 230, 118, 0.15)' : 'rgba(210, 153, 34, 0.15)';
        }

        if (items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: var(--text-muted); padding: 30px;">No candidates currently match filters.</td></tr>';
            return;
        }

        let html = '';
        items.forEach(item => {
            const isQualified = item.passed_gate;
            const chgColor = item.price_change_pct >= 0 ? '#3fb950' : '#f85149';
            const sideBadge = item.side === 'LONG'
                ? '<span style="color: #3fb950; background: rgba(63,185,80,0.15); padding: 2px 6px; border-radius: 3px; font-weight: 800;">LONG</span>'
                : (item.side === 'SHORT'
                    ? '<span style="color: #f85149; background: rgba(248,81,73,0.15); padding: 2px 6px; border-radius: 3px; font-weight: 800;">SHORT</span>'
                    : '<span style="color: #8b949e;">--</span>');

            const probColor = item.win_probability_pct >= 85 ? '#00E676' : (item.win_probability_pct >= 75 ? '#58a6ff' : '#8b949e');
            const probBarWidth = Math.min(Math.max((item.win_probability_pct - 60) * 2.5, 5), 100);

            let stratColor = '#8b949e';
            let metricText = '--';
            if (item.strategy.includes('Liquidation')) {
                stratColor = '#58a6ff';
                metricText = `$${(item.liquidation_burst_usd / 1000).toFixed(0)}k Liq Wick`;
            } else if (item.strategy.includes('Lead-Lag')) {
                stratColor = '#00E676';
                metricText = `${item.lead_lag_delta_pct > 0 ? '+' : ''}${item.lead_lag_delta_pct}% Delta`;
            } else if (item.strategy.includes('Stoikov')) {
                stratColor = '#d29922';
                metricText = `OBI: ${item.order_book_imbalance > 0 ? '+' : ''}${item.order_book_imbalance}`;
            }

            const verdictHtml = isQualified
                ? '<span style="background: rgba(0, 230, 118, 0.2); color: #00E676; border: 1px solid rgba(0,230,118,0.4); padding: 3px 8px; border-radius: 4px; font-weight: 800; font-size: 11px;">⚡ QUALIFIED</span>'
                : `<span style="background: rgba(110, 118, 129, 0.2); color: #8b949e; padding: 2px 6px; border-radius: 3px; font-size: 10px;">${item.status}</span>`;

            html += `
                <tr style="${isQualified ? 'background: rgba(0, 230, 118, 0.04);' : ''}">
                    <td style="font-family: var(--font-mono); color: var(--text-muted); font-weight: 700;">#${item.rank}</td>
                    <td style="font-weight: 800; color: #fff;">${item.symbol}</td>
                    <td>${sideBadge}</td>
                    <td style="font-family: var(--font-mono);">$${Number(item.last_price).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 4})}</td>
                    <td style="font-family: var(--font-mono); color: ${chgColor}; font-weight: 700;">${item.price_change_pct >= 0 ? '+' : ''}${item.price_change_pct}%</td>
                    <td><span style="color: ${stratColor}; font-weight: 700; font-size: 11px;">${item.strategy}</span></td>
                    <td style="font-family: var(--font-mono); font-size: 11px;">${metricText}</td>
                    <td style="font-family: var(--font-mono); color: var(--text-muted); font-size: 11px;">$${(item.volume_24h_usd / 1000000).toFixed(1)}M</td>
                    <td>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="font-family: var(--font-mono); font-weight: 800; color: ${probColor}; min-width: 44px;">${item.win_probability_pct.toFixed(1)}%</span>
                            <div style="flex: 1; height: 5px; background: rgba(255,255,255,0.08); border-radius: 3px; overflow: hidden; min-width: 50px;">
                                <div style="width: ${probBarWidth}%; height: 100%; background: ${probColor};"></div>
                            </div>
                        </div>
                    </td>
                    <td>${verdictHtml}</td>
                </tr>
            `;
        });

        tbody.innerHTML = html;

    } catch (e) {
        console.error('Failed to load scalper radar:', e);
    }
}

// 5. Load Scalper Telemetry & Status
async function loadScalperStatus() {
    return loadScalperTelemetry();
}

async function loadScalperTelemetry() {
    try {
        const resp = await axios.get('/api/scalper/status');
        if (!resp.data || !resp.data.success) return;
        const s = resp.data;

        // Dedicated Page Active Scalp Elements
        const pActive = document.getElementById('scalper-page-active');
        const pEmpty = document.getElementById('scalper-page-empty');
        const pBadge = document.getElementById('scalper-page-active-badge');
        const slotBadge = document.getElementById('scalper-slot-badge');

        if (s.active_scalp) {
            const p = s.active_scalp;
            if (pActive) pActive.style.display = 'block';
            if (pEmpty) pEmpty.style.display = 'none';

            if (pBadge) {
                pBadge.textContent = 'ACTIVE POSITION';
                pBadge.style.background = 'rgba(63, 185, 80, 0.2)';
                pBadge.style.color = '#3fb950';
            }
            if (slotBadge) {
                slotBadge.textContent = '⚡ ' + p.symbol + ' (' + p.side + ')';
                slotBadge.style.color = '#00e5ff';
            }

            const setTxt = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
            setTxt('scalper-card-symbol', p.symbol);
            setTxt('scalper-card-entry', '$' + p.entry_price);
            setTxt('scalper-card-notional', '$' + (p.notional_usd ? p.notional_usd.toFixed(2) : '--'));
            setTxt('scalper-card-tp', '$' + p.take_profit);
            setTxt('scalper-card-sl', '$' + p.stop_loss);
            setTxt('scalper-card-mfe', p.highest_price ? '$' + p.highest_price : 'Tracking...');
            setTxt('scalper-card-mae', p.lowest_price ? '$' + p.lowest_price : 'Tracking...');

            const durMin = p.duration_minutes || 0;
            const maxMin = p.max_duration_minutes || 3;
            setTxt('scalper-card-time', durMin + 'm / ' + maxMin + 'm');

            const sideEl = document.getElementById('scalper-card-side');
            if (sideEl) {
                sideEl.textContent = p.side;
                sideEl.style.color = p.side === 'BUY' ? '#3fb950' : '#f85149';
                sideEl.style.background = p.side === 'BUY' ? 'rgba(63,185,80,0.2)' : 'rgba(248,81,73,0.2)';
            }
        } else {
            if (pActive) pActive.style.display = 'none';
            if (pEmpty) pEmpty.style.display = 'block';

            if (pBadge) {
                pBadge.textContent = 'STANDBY';
                pBadge.style.background = 'rgba(0, 229, 255, 0.15)';
                pBadge.style.color = '#00e5ff';
            }
            if (slotBadge) {
                slotBadge.textContent = '🟢 1/1 Available';
                slotBadge.style.color = '#3fb950';
            }
        }

        // Closed Scalps Table
        const closedTbody = document.getElementById('scalper-closed-trades-tbody');
        if (closedTbody && s.recent_trades) {
            if (s.recent_trades.length === 0) {
                closedTbody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 25px;">Awaiting closed scalper trades. Realized scalps will record here with fee deduction audit.</td></tr>';
            } else {
                let html = '';
                s.recent_trades.slice().reverse().forEach(t => {
                    const pnlColor = t.net_pnl_usd >= 0 ? '#3fb950' : '#f85149';
                    const sign = t.net_pnl_usd >= 0 ? '+' : '';
                    html += `
                        <tr>
                            <td style="font-family: var(--font-mono); color: var(--text-muted); font-size: 11px;">${t.trade_id || '--'}</td>
                            <td style="font-weight: 800; color: #fff;">${t.symbol}</td>
                            <td><span style="color: ${t.direction === 'LONG' ? '#3fb950' : '#f85149'}; font-weight: 800;">${t.direction}</span></td>
                            <td style="font-family: var(--font-mono); color: ${pnlColor}; font-weight: 800;">${sign}$${Number(t.net_pnl_usd).toFixed(4)}</td>
                            <td style="font-family: var(--font-mono); color: ${pnlColor}; font-weight: 700;">${sign}${Number(t.return_pct).toFixed(2)}%</td>
                            <td style="font-family: var(--font-mono); color: #3fb950;">+${Number(t.mfe_pct).toFixed(2)}%</td>
                            <td style="font-family: var(--font-mono); color: #f85149;">-${Number(t.mae_pct).toFixed(2)}%</td>
                            <td style="font-size: 11px; color: var(--text-secondary);">${t.root_cause || 'Optimal Trajectory'}</td>
                            <td style="font-size: 11px; color: #58a6ff;">${t.remedy || 'Standard Parameter'}</td>
                        </tr>
                    `;
                });
                closedTbody.innerHTML = html;
            }
        }

        // Cooldown Count
        const cdEl = document.getElementById('scalper-cooldowns-count');
        if (cdEl && s.symbol_cooldowns) {
            const cdKeys = Object.keys(s.symbol_cooldowns);
            cdEl.textContent = cdKeys.length > 0 ? cdKeys.join(', ') : '0';
        }

        // Also update existing paper/live dashboard widgets for backward compatibility
        if (typeof updateScalperUI === 'function') {
            updateScalperUI(s);
        }

    } catch (e) {
        console.error('Failed to load scalper telemetry:', e);
    }
}

// 6. Reset Scalper Slot
async function resetScalperSlot() {
    if (!confirm('Emergency Reset Scalper Slot? This clears active scalp locks and resets cooldowns.')) return;
    try {
        const resp = await axios.post('/api/scalper/reset-slot');
        if (resp.data && resp.data.success) {
            showScalperToast('Scalper slot reset successfully.');
            loadScalperTelemetry();
        }
    } catch (e) {
        showScalperToast('Failed to reset slot: ' + e.message, false);
    }
}

// 7. Full Page Loader is handled by the multi-strategy router below.

// 8. Load Distilled Rules & Parameter Status
async function loadDistilledRules() {
    try {
        const resp = await axios.get('/api/scalper/distilled-rules');
        if (!resp.data || !resp.data.success || !resp.data.distilled_rules) return;
        const d = resp.data.distilled_rules;

        const pcMeta = document.getElementById('distill-pc-meta');
        if (pcMeta) {
            pcMeta.textContent = `Audited: ${d.sample_size || 0} trades · Win Rate: ${(d.win_rate_pct || 0).toFixed(1)}% · PF: ${(d.profit_factor || 1.0).toFixed(2)}x`;
        }

        const causeBadge = document.getElementById('distill-cause-badge');
        if (causeBadge && d.dominant_root_cause) {
            causeBadge.textContent = d.dominant_root_cause;
            causeBadge.style.color = d.dominant_root_cause === 'CONVICTION_WIN' ? '#00E676' : '#d29922';
            causeBadge.style.background = d.dominant_root_cause === 'CONVICTION_WIN' ? 'rgba(0, 230, 118, 0.15)' : 'rgba(210, 153, 34, 0.15)';
        }

        const paramsSummary = document.getElementById('distill-params-summary');
        if (paramsSummary && d.calibrated_parameters) {
            const p = d.calibrated_parameters;
            paramsSummary.textContent = `ATR: ${p.atr_stop_multiplier.toFixed(2)}x · TP: +${p.fee_hurdle_pct.toFixed(2)}% · Sieve: ≥${p.min_win_prob_pct.toFixed(1)}%`;
        }

        const remedyText = document.getElementById('distill-remedy-text');
        if (remedyText && d.recommended_remedy) {
            remedyText.textContent = d.recommended_remedy;
            remedyText.title = d.recommended_remedy;
        }

        const quarList = document.getElementById('distill-quarantined-list');
        if (quarList) {
            const q = d.quarantined_symbols || [];
            quarList.textContent = q.length > 0 ? q.join(', ') : 'None (All Clear)';
            quarList.style.color = q.length > 0 ? '#f85149' : '#00E676';
        }

        const awsBadge = document.getElementById('distill-aws-badge');
        const awsMeta = document.getElementById('distill-aws-meta');
        if (awsBadge && awsMeta) {
            if (d.synced_to_aws) {
                awsBadge.textContent = 'SYNCED';
                awsBadge.style.background = 'rgba(0, 229, 255, 0.15)';
                awsBadge.style.color = '#00e5ff';
                awsMeta.textContent = `Hot-Reload: Active · ${d.timestamp_utc ? new Date(d.timestamp_utc).toLocaleTimeString() : 'Recent'}`;
            } else {
                awsBadge.textContent = 'LOCAL ONLY';
                awsBadge.style.background = 'rgba(210, 153, 34, 0.15)';
                awsBadge.style.color = '#d29922';
                awsMeta.textContent = 'Pending sync to AWS';
            }
        }
    } catch (e) {
        console.error('Failed to load distilled rules:', e);
    }
}

// 9. Load 46-Item TCA Microstructural Forensics Table
async function loadScalperForensics() {
    const closedTbody = document.getElementById('scalper-closed-trades-tbody');
    if (!closedTbody) return;
    try {
        const resp = await axios.get('/api/scalper/forensics?limit=50');
        if (!resp.data || !resp.data.success || !resp.data.forensics) return;
        const rows = resp.data.forensics;

        if (rows.length === 0) {
            closedTbody.innerHTML = '<tr><td colspan="12" style="text-align: center; color: var(--text-muted); padding: 25px;">Awaiting closed scalper trades. Realized scalps will record here with fee deduction audit.</td></tr>';
            return;
        }

        let html = '';
        rows.forEach(t => {
            const netPnl = parseFloat(t.net_pnl_usd || 0);
            const pnlColor = netPnl >= 0 ? '#3fb950' : '#f85149';
            const sign = netPnl >= 0 ? '+' : '';
            const retPct = parseFloat(t.return_pct || 0);
            const mfe = parseFloat(t.mfe_pct || 0);
            const mae = parseFloat(t.mae_pct || 0);
            const tax = parseFloat(t.realization_tax_bps || 0);
            const dur = t.holding_duration_seconds ? `${t.holding_duration_seconds}s` : '--';

            let rootBadgeColor = '#58a6ff';
            if (t.root_cause_diagnosis === 'CONVICTION_WIN') rootBadgeColor = '#00E676';
            else if (t.root_cause_diagnosis === 'TOXIC_LUCKY_WIN') rootBadgeColor = '#d29922';
            else if (t.root_cause_diagnosis === 'FRICTION_BLEED') rootBadgeColor = '#ff7b72';
            else if (t.root_cause_diagnosis === 'STOP_INSIDE_NOISE') rootBadgeColor = '#f0883e';

            html += `
                <tr>
                    <td style="font-family: var(--font-mono); color: var(--text-muted); font-size: 11px;">${t.trade_id || '--'}</td>
                    <td style="font-weight: 800; color: #fff;">${t.symbol}</td>
                    <td><span style="color: ${t.direction === 'LONG' ? '#3fb950' : '#f85149'}; font-weight: 800;">${t.direction}</span></td>
                    <td style="font-family: var(--font-mono); font-size: 11px;">$${Number(t.entry_price).toFixed(2)} → $${Number(t.exit_price).toFixed(2)}</td>
                    <td style="font-family: var(--font-mono); color: var(--text-muted); font-size: 11px;">${dur}</td>
                    <td style="font-family: var(--font-mono); color: ${pnlColor}; font-weight: 800;">${sign}$${netPnl.toFixed(4)}</td>
                    <td style="font-family: var(--font-mono); color: ${pnlColor}; font-weight: 700;">${sign}${retPct.toFixed(2)}%</td>
                    <td style="font-family: var(--font-mono); color: #3fb950; font-weight: 700;">+${mfe.toFixed(2)}%</td>
                    <td style="font-family: var(--font-mono); color: #f85149; font-weight: 700;">${mae.toFixed(2)}%</td>
                    <td style="font-family: var(--font-mono); color: #d29922; font-size: 11px;">${tax.toFixed(1)} bps</td>
                    <td><span style="background: rgba(255,255,255,0.06); color: ${rootBadgeColor}; padding: 2px 6px; border-radius: 3px; font-weight: 800; font-size: 11px;">${t.root_cause_diagnosis}</span></td>
                    <td style="font-size: 11px; color: var(--text-secondary); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${t.actionable_remedy}">${t.actionable_remedy}</td>
                </tr>
            `;
        });
        closedTbody.innerHTML = html;
    } catch (e) {
        console.error('Failed to load forensics:', e);
    }
}

// 10. Trigger Quantitative Learning & Distillation to AWS
async function triggerScalperDistillation(syncAws = true) {
    try {
        showScalperToast(syncAws ? 'Running PC learning audit & syncing to AWS...' : 'Running local learning audit...');
        const resp = await axios.post('/api/scalper/distill', { sync_aws: syncAws, lookback: 100 });
        if (resp.data && resp.data.success) {
            const s = resp.data.summary;
            const msg = `Audit Complete: ${s.sample_size} trades, Win Rate: ${s.win_rate_pct}%. ${syncAws && s.synced_to_aws ? 'Synced to AWS!' : ''}`;
            showScalperToast(msg, true);
            loadDistilledRules();
            loadScalperForensics();
            loadScalperConfig();
        } else {
            showScalperToast('Distillation failed: ' + (resp.data.error || 'Unknown'), false);
        }
    } catch (e) {
        console.error('Distillation error:', e);
        showScalperToast('Distillation error: ' + e.message, false);
    }
}

/* =======================================================================
 * SECTION B: STALKING TIGER SCALPER (STRATEGY #3) JAVASCRIPT CONTROLLER
 * ======================================================================= */

let currentScalperSubTab = 'tiger';

function switchScalperSubTab(subTab) {
    currentScalperSubTab = subTab;
    const paneTiger = document.getElementById('scalper-pane-tiger');
    const paneLightning = document.getElementById('scalper-pane-lightning');
    const btnTiger = document.getElementById('btn-subtab-tiger');
    const btnLightning = document.getElementById('btn-subtab-lightning');

    if (subTab === 'tiger') {
        if (paneTiger) paneTiger.style.display = 'block';
        if (paneLightning) paneLightning.style.display = 'none';

        if (btnTiger) {
            btnTiger.className = 'scalper-subtab active-tiger';
            btnTiger.removeAttribute('style');
        }
        if (btnLightning) {
            btnLightning.className = 'scalper-subtab';
            btnLightning.removeAttribute('style');
        }
        loadTigerPage();
    } else {
        if (paneTiger) paneTiger.style.display = 'none';
        if (paneLightning) paneLightning.style.display = 'block';

        if (btnLightning) {
            btnLightning.className = 'scalper-subtab active-lightning';
            btnLightning.removeAttribute('style');
        }
        if (btnTiger) {
            btnTiger.className = 'scalper-subtab';
            btnTiger.removeAttribute('style');
        }
        loadLightningScalperPage();
    }
}

function loadScalperPage() {
    if (currentScalperSubTab === 'tiger') {
        loadTigerPage();
    } else {
        loadLightningScalperPage();
    }
}

function loadLightningScalperPage() {
    loadScalperConfig();
    loadScalperTelemetry();
    loadScalperRadar();
    loadDistilledRules();
    loadScalperForensics();
}

async function loadTigerPage() {
    await loadTigerStatus();
}

async function loadTigerForensics() {
    await loadTigerStatus();
}

async function loadTigerStatus() {
    try {
        const resp = await axios.get('/api/tiger/status');
        if (!resp.data || !resp.data.success) return;
        const d = resp.data;

        // 1. Master Telemetry Bar
        const wsTicksBadge = document.getElementById('tiger-ws-ticks-badge');
        if (wsTicksBadge && d.radar && d.radar.ws_ticks !== undefined) {
            wsTicksBadge.textContent = `⚡ WS: ${Number(d.radar.ws_ticks).toLocaleString()} ticks`;
        }

        const btcBadge = document.getElementById('tiger-btc-tide-badge');
        if (btcBadge && d.radar) {
            const btcRet = parseFloat(d.radar.btc_1m_return_pct || 0);
            const btcCvd = parseFloat(d.radar.btc_cvd_zscore || 0);
            const isVeto = btcRet <= -0.35 || btcCvd <= -2.5;
            btcBadge.textContent = `${isVeto ? '🔴 DUMP VETO' : '🟢 CLEAR'}: BTC ${btcRet >= 0 ? '+' : ''}${btcRet.toFixed(2)}% · CVD ${btcCvd.toFixed(1)}σ`;
            btcBadge.style.color = isVeto ? '#f85149' : '#00E676';
        }

        const sizingBadge = document.getElementById('tiger-sizing-badge');
        if (sizingBadge && d.config_summary) {
            sizingBadge.textContent = `$${d.config_summary.risk_budget_per_trade_usd} Locked Risk · Vol Parity`;
        }

        const weightBadge = document.getElementById('tiger-weight-badge');
        if (weightBadge && d.radar) {
            weightBadge.textContent = `Weight: ${d.radar.used_weight || 0} / 2400`;
        }

        // 2. Top 5 Hot Prey Table
        const preyTbody = document.getElementById('tiger-prey-tbody');
        const preyCountBadge = document.getElementById('tiger-prey-count-badge');
        if (preyTbody && d.radar && d.radar.active_prey) {
            const preyList = d.radar.active_prey;
            if (preyCountBadge) preyCountBadge.textContent = `${preyList.length} Hot Prey Isolated`;

            let pHtml = '';
            preyList.forEach(p => {
                const chg = parseFloat(p.price_change_pct || 0);
                const chgColor = chg >= 0 ? '#3fb950' : '#f85149';
                const sign = chg >= 0 ? '+' : '';
                const turnover = parseFloat(p.turnover_24h_usd || 0);
                const turnoverStr = turnover >= 1e6 ? `$${(turnover / 1e6).toFixed(1)}M` : `$${turnover.toLocaleString()}`;
                const volScore = parseFloat(p.volatility_score || 0).toFixed(4);
                const isQuar = p.is_quarantined;
                const doi = parseFloat(p.delta_oi_pct || 0);
                const doiColor = doi > 0 ? '#3fb950' : (doi < 0 ? '#f85149' : '#8b949e');
                const doiSign = doi > 0 ? '+' : '';
                const doiBadge = `<span style="font-family: var(--font-mono); font-weight: 800; color: ${doiColor}; background: ${doi > 0 ? 'rgba(63,185,80,0.1)' : 'rgba(248,81,73,0.1)'}; padding: 2px 6px; border-radius: 3px;">${doiSign}${doi.toFixed(2)}% ΔOI</span>`;

                pHtml += `
                    <tr>
                        <td style="font-family: var(--font-mono); font-weight: 800; color: #ff9800;">#${p.rank}</td>
                        <td style="font-weight: 900; font-size: 14px; color: #fff;">${p.symbol}</td>
                        <td style="font-family: var(--font-mono); font-weight: 700;">$${p.last_price}</td>
                        <td style="font-family: var(--font-mono); color: ${chgColor}; font-weight: 800;">${sign}${chg.toFixed(2)}%</td>
                        <td style="font-family: var(--font-mono); color: #58a6ff;">${turnoverStr}</td>
                        <td style="font-family: var(--font-mono); color: #d29922; font-weight: 700;">${volScore}</td>
                        <td style="font-family: var(--font-mono); font-size: 11px;">${doiBadge}</td>
                        <td><span style="font-family: var(--font-mono); font-size: 11px; color: #00E676; background: rgba(0,230,118,0.1); padding: 2px 6px; border-radius: 3px;">@aggTrade + @depth5</span></td>
                        <td><span style="color: #ff9800; font-weight: 700; font-size: 11px;">Stalking Trap...</span></td>
                        <td>
                            ${isQuar
                                ? '<span style="background: rgba(248,81,73,0.15); color: #f85149; padding: 2px 8px; border-radius: 3px; font-weight: 800; font-size: 10px;">🔴 QUARANTINED</span>'
                                : '<span style="background: rgba(0,230,118,0.15); color: #00E676; padding: 2px 8px; border-radius: 3px; font-weight: 800; font-size: 10px;">🟢 HUNTING</span>'}
                        </td>
                    </tr>
                `;
            });
            preyTbody.innerHTML = pHtml;
        }

        // 3. Active Position Card
        const posEmpty = document.getElementById('tiger-pos-empty');
        const posActive = document.getElementById('tiger-pos-active');
        const posBadge = document.getElementById('tiger-pos-badge');
        const activePositions = d.state ? d.state.active_positions || {} : {};
        const posKeys = Object.keys(activePositions);

        if (posKeys.length > 0) {
            const pos = activePositions[posKeys[0]];
            if (posEmpty) posEmpty.style.display = 'none';
            if (posActive) posActive.style.display = 'block';
            if (posBadge) {
                posBadge.textContent = 'POUNCING';
                posBadge.style.color = '#3fb950';
                posBadge.style.background = 'rgba(63,185,80,0.2)';
            }
            const symEl = document.getElementById('tiger-card-symbol');
            if (symEl) symEl.textContent = pos.symbol;
            const sideEl = document.getElementById('tiger-card-side');
            if (sideEl) {
                sideEl.textContent = pos.side;
                sideEl.style.color = pos.side === 'BUY' ? '#3fb950' : '#f85149';
            }
            const entryEl = document.getElementById('tiger-card-entry');
            if (entryEl) entryEl.textContent = `$${pos.entry_price}`;
            const notionalEl = document.getElementById('tiger-card-notional');
            if (notionalEl) notionalEl.textContent = `$${Number(pos.notional_usd || 100).toFixed(2)}`;
            const tpEl = document.getElementById('tiger-card-tp');
            if (tpEl) tpEl.textContent = `$${pos.take_profit}`;
            const slEl = document.getElementById('tiger-card-sl');
            if (slEl) slEl.textContent = `$${pos.stop_loss}`;
        } else {
            if (posEmpty) posEmpty.style.display = 'block';
            if (posActive) posActive.style.display = 'none';
            if (posBadge) {
                posBadge.textContent = 'STANDBY';
                posBadge.style.color = '#00E676';
                posBadge.style.background = 'rgba(0, 230, 118, 0.15)';
            }
        }

        // 4. Pending Signals Table
        const pendingTbody = document.getElementById('tiger-pending-tbody');
        const pendingCountBadge = document.getElementById('tiger-pending-count-badge');
        const pendingSignals = d.state ? d.state.pending_signals || {} : {};
        const pendKeys = Object.keys(pendingSignals);
        if (pendingCountBadge) pendingCountBadge.textContent = `${pendKeys.length} Pending`;

        if (pendingTbody) {
            if (pendKeys.length === 0) {
                pendingTbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 30px;">No pending limit triggers. Waiting for orderflow trap signal.</td></tr>`;
            } else {
                let pendHtml = '';
                pendKeys.forEach(k => {
                    const s = pendingSignals[k];
                    pendHtml += `
                        <tr>
                            <td style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">${s.signal_id}</td>
                            <td style="font-weight: 800; color: #fff;">${s.symbol}</td>
                            <td><span style="color: ${s.action === 'BUY' ? '#3fb950' : '#f85149'}; font-weight: 800;">${s.action}</span></td>
                            <td style="font-family: var(--font-mono); font-weight: 700;">$${s.entry_trigger_price}</td>
                            <td style="font-family: var(--font-mono); color: #f85149;">$${s.stop_loss_price}</td>
                            <td style="font-family: var(--font-mono); color: #3fb950;">$${s.take_profit_price}</td>
                            <td style="font-family: var(--font-mono); color: #d29922; font-weight: 700;">90s TTL</td>
                            <td><span style="font-size: 11px; color: #58a6ff;">${s.is_slow_regime ? 'SLOW VOL' : 'FAST VOL'}</span></td>
                            <td><span style="background: rgba(88,166,255,0.15); color: #58a6ff; padding: 2px 6px; border-radius: 3px; font-weight: 800; font-size: 10px;">WAITING TRIGGER</span></td>
                        </tr>
                    `;
                });
                pendingTbody.innerHTML = pendHtml;
            }
        }

        // 5. Autonomous Learning Distillation Deck
        if (d.distilled_rules) {
            const rules = d.distilled_rules;
            const winEl = document.getElementById('tiger-distill-winrate');
            if (winEl) winEl.textContent = `${rules.win_rate_pct || 0}%`;
            const sampleEl = document.getElementById('tiger-distill-sample');
            if (sampleEl) sampleEl.textContent = `Audited: ${rules.sample_size || 0} trades · PF: ${rules.profit_factor || 1.0}`;
            const mfeMaeEl = document.getElementById('tiger-distill-mfe-mae');
            if (mfeMaeEl) {
                const mfe = (parseFloat(rules.avg_mfe_pct || 0) * 100).toFixed(2);
                const mae = (parseFloat(rules.avg_mae_pct || 0) * 100).toFixed(2);
                mfeMaeEl.textContent = `Avg MFE: +${mfe}% · MAE: -${mae}%`;
            }
            const threshEl = document.getElementById('tiger-distill-thresholds');
            if (threshEl) threshEl.textContent = `Min Wick: ${rules.calibrated_min_wick_ratio || 0.40} · Min CVD: ${rules.calibrated_min_cvd_zscore || 2.2}σ`;
            const slowEl = document.getElementById('tiger-distill-slow-calib');
            if (slowEl) {
                const sTp = (parseFloat(rules.calibrated_slow_tp_pct || 0.0080) * 100).toFixed(2);
                const sSl = (parseFloat(rules.calibrated_slow_sl_pct || 0.0055) * 100).toFixed(2);
                slowEl.textContent = `Slow TP: +${sTp}% · Slow SL: -${sSl}%`;
            }
            const quarEl = document.getElementById('tiger-distill-quarantined');
            if (quarEl) {
                const q = rules.quarantined_symbols || [];
                quarEl.textContent = q.length > 0 ? q.join(', ') : 'None (All Clear)';
                quarEl.style.color = q.length > 0 ? '#f85149' : '#00E676';
            }
        }

        // 6. Trade Forensics Table (from SQLite)
        const tradesTbody = document.getElementById('tiger-trades-tbody');
        const countEl = document.getElementById('tiger-forensics-count');
        if (countEl && d.recent_trades) countEl.textContent = d.recent_trades.length;

        if (tradesTbody && d.recent_trades) {
            if (d.recent_trades.length === 0) {
                tradesTbody.innerHTML = `<tr><td colspan="11" style="text-align: center; color: var(--text-muted); padding: 25px;">No closed trades yet in database.</td></tr>`;
            } else {
                let tHtml = '';
                d.recent_trades.forEach(t => {
                    const isWin = t.is_win;
                    const pnl = parseFloat(t.net_pnl_usd || 0);
                    const pnlColor = pnl >= 0 ? '#3fb950' : '#f85149';
                    const sign = pnl >= 0 ? '+' : '';
                    const dur = t.duration_seconds < 60 ? `${t.duration_seconds}s` : `${Math.floor(t.duration_seconds/60)}m ${t.duration_seconds%60}s`;

                    tHtml += `
                        <tr>
                            <td style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">${t.trade_id}</td>
                            <td style="font-weight: 800; color: #fff;">${t.symbol}</td>
                            <td><span style="color: ${t.side === 'BUY' ? '#3fb950' : '#f85149'}; font-weight: 800;">${t.side}</span></td>
                            <td style="font-family: var(--font-mono); font-size: 11px;">$${t.entry_price}</td>
                            <td style="font-family: var(--font-mono); font-size: 11px;">$${t.exit_price}</td>
                            <td style="font-family: var(--font-mono); color: #f0b90b; font-weight: 700;">$${Number(t.notional_usd).toFixed(2)}</td>
                            <td style="font-family: var(--font-mono); color: ${pnlColor}; font-weight: 800;">${sign}$${pnl.toFixed(2)}</td>
                            <td style="font-family: var(--font-mono); color: ${pnlColor}; font-weight: 700;">${sign}${(t.net_pnl_pct * 100).toFixed(2)}%</td>
                            <td style="font-family: var(--font-mono); color: var(--text-muted); font-size: 11px;">${dur}</td>
                            <td style="font-size: 11px; color: var(--text-secondary);">${t.exit_reason}</td>
                            <td>
                                ${isWin
                                    ? '<span style="background: rgba(0,230,118,0.2); color: #00E676; padding: 2px 6px; border-radius: 3px; font-weight: 800; font-size: 10px;">WIN</span>'
                                    : '<span style="background: rgba(248,81,73,0.2); color: #f85149; padding: 2px 6px; border-radius: 3px; font-weight: 800; font-size: 10px;">LOSS</span>'}
                            </td>
                        </tr>
                    `;
                });
                tradesTbody.innerHTML = tHtml;
            }
        }

        // 7. Populate Configuration Inputs if available
        if (d.config) {
            populateTigerConfigInputs(d.config);
        }

    } catch (e) {
        console.error('Failed to load Tiger status:', e);
    }
}

function populateTigerConfigInputs(cfg) {
    if (!cfg) return;
    const of = cfg.orderflow || {};
    const brk = cfg.brackets || {};

    const elWick = document.getElementById('input-tiger-wick');
    if (elWick && of.absorption_wick_min_ratio) {
        elWick.value = parseFloat(of.absorption_wick_min_ratio);
        const valEl = document.getElementById('val-tiger-wick');
        if (valEl) valEl.textContent = `${Number(elWick.value).toFixed(2)} (${(Number(elWick.value)*100).toFixed(0)}%)`;
    }

    const elClose = document.getElementById('input-tiger-close-loc');
    if (elClose && of.max_candle_close_loc_pct) {
        elClose.value = parseFloat(of.max_candle_close_loc_pct);
        const valEl = document.getElementById('val-tiger-close-loc');
        if (valEl) valEl.textContent = `${Number(elClose.value).toFixed(2)} (${(Number(elClose.value)*100).toFixed(0)}%)`;
    }

    const elVol = document.getElementById('input-tiger-vol-mult');
    if (elVol && of.volume_surge_multiple) elVol.value = parseFloat(of.volume_surge_multiple);

    const elTtl = document.getElementById('input-tiger-ttl');
    if (elTtl && of.signal_ttl_seconds) elTtl.value = parseInt(of.signal_ttl_seconds);

    const chkBtc = document.getElementById('check-tiger-btc-gate');
    if (chkBtc && of.btc_tide_gate_enabled !== undefined) chkBtc.checked = of.btc_tide_gate_enabled;

    const elBtcDump = document.getElementById('input-tiger-btc-dump');
    if (elBtcDump && of.btc_1m_dump_threshold_pct) elBtcDump.value = (parseFloat(of.btc_1m_dump_threshold_pct) * 100).toFixed(2);

    const elBtcCvd = document.getElementById('input-tiger-btc-cvd');
    if (elBtcCvd && of.btc_cvd_dump_sigma) elBtcCvd.value = parseFloat(of.btc_cvd_dump_sigma);

    const chkMacro = document.getElementById('check-tiger-macro-trend');
    if (chkMacro && of.macro_trend_filter_enabled !== undefined) chkMacro.checked = of.macro_trend_filter_enabled;

    const elOutlier = document.getElementById('input-tiger-outlier');
    if (elOutlier && of.max_24h_outlier_move_pct) elOutlier.value = (parseFloat(of.max_24h_outlier_move_pct) * 100).toFixed(0);

    const chkVolParity = document.getElementById('check-tiger-vol-parity');
    if (chkVolParity && brk.volatility_parity_enabled !== undefined) chkVolParity.checked = brk.volatility_parity_enabled;

    const elRisk = document.getElementById('input-tiger-risk-usd');
    if (elRisk && brk.risk_budget_per_trade_usd) elRisk.value = parseFloat(brk.risk_budget_per_trade_usd);

    const elMinNotional = document.getElementById('input-tiger-min-notional');
    if (elMinNotional && brk.min_notional_usd) elMinNotional.value = parseFloat(brk.min_notional_usd);

    const elMaxNotional = document.getElementById('input-tiger-max-notional');
    if (elMaxNotional && brk.max_notional_usd) elMaxNotional.value = parseFloat(brk.max_notional_usd);

    const elFastTp = document.getElementById('input-tiger-fast-tp');
    if (elFastTp && brk.calibrated_tp_price_pct) elFastTp.value = (parseFloat(brk.calibrated_tp_price_pct) * 100).toFixed(2);

    const elFastSl = document.getElementById('input-tiger-fast-sl');
    if (elFastSl && brk.fast_vol_sl_price_pct) elFastSl.value = (parseFloat(brk.fast_vol_sl_price_pct) * 100).toFixed(2);

    const elSlowTp = document.getElementById('input-tiger-slow-tp');
    if (elSlowTp && brk.slow_vol_tp_price_pct) elSlowTp.value = (parseFloat(brk.slow_vol_tp_price_pct) * 100).toFixed(2);

    const elSlowSl = document.getElementById('input-tiger-slow-sl');
    if (elSlowSl && brk.slow_vol_sl_price_pct) elSlowSl.value = (parseFloat(brk.slow_vol_sl_price_pct) * 100).toFixed(2);

    const elCooldown = document.getElementById('input-tiger-cooldown');
    if (elCooldown && brk.asset_cooldown_seconds) elCooldown.value = parseInt(brk.asset_cooldown_seconds);
}

async function saveTigerConfig() {
    try {
        const payload = {
            absorption_wick_min_ratio: parseFloat(document.getElementById('input-tiger-wick').value),
            max_candle_close_loc_pct: parseFloat(document.getElementById('input-tiger-close-loc').value),
            volume_surge_multiple: parseFloat(document.getElementById('input-tiger-vol-mult').value),
            signal_ttl_seconds: parseInt(document.getElementById('input-tiger-ttl').value),
            btc_tide_gate_enabled: document.getElementById('check-tiger-btc-gate').checked,
            btc_1m_dump_threshold_pct: parseFloat(document.getElementById('input-tiger-btc-dump').value) / 100.0,
            btc_cvd_dump_sigma: parseFloat(document.getElementById('input-tiger-btc-cvd').value),
            macro_trend_filter_enabled: document.getElementById('check-tiger-macro-trend').checked,
            max_24h_outlier_move_pct: parseFloat(document.getElementById('input-tiger-outlier').value) / 100.0,
            volatility_parity_enabled: document.getElementById('check-tiger-vol-parity').checked,
            risk_budget_per_trade_usd: parseFloat(document.getElementById('input-tiger-risk-usd').value),
            min_notional_usd: parseFloat(document.getElementById('input-tiger-min-notional').value),
            max_notional_usd: parseFloat(document.getElementById('input-tiger-max-notional').value),
            calibrated_tp_price_pct: parseFloat(document.getElementById('input-tiger-fast-tp').value) / 100.0,
            fast_vol_sl_price_pct: parseFloat(document.getElementById('input-tiger-fast-sl').value) / 100.0,
            slow_vol_tp_price_pct: parseFloat(document.getElementById('input-tiger-slow-tp').value) / 100.0,
            slow_vol_sl_price_pct: parseFloat(document.getElementById('input-tiger-slow-sl').value) / 100.0,
            asset_cooldown_seconds: parseInt(document.getElementById('input-tiger-cooldown').value)
        };

        const resp = await axios.post('/api/tiger/config', payload);
        if (resp.data && resp.data.success) {
            showScalperToast("🐅 Stalking Tiger configuration saved successfully!", true);
            loadTigerPage();
        } else {
            showScalperToast("Failed to save config: " + (resp.data.error || "Unknown"), false);
        }
    } catch (e) {
        console.error("Save Tiger Config Error:", e);
        showScalperToast("Save error: " + e.message, false);
    }
}

async function forceTigerScan() {
    try {
        showScalperToast("Scanning Binance universe for Top 5 Hot Prey...", true);
        const resp = await axios.post('/api/tiger/scan');
        if (resp.data && resp.data.success) {
            showScalperToast(`Scan Complete: Isolated ${resp.data.count} Hot Prey!`, true);
            loadTigerPage();
        } else {
            showScalperToast("Scan failed: " + (resp.data.error || "Unknown"), false);
        }
    } catch (e) {
        showScalperToast("Scan error: " + e.message, false);
    }
}

async function triggerTigerDistillation() {
    try {
        showScalperToast("Running Tiger autonomous learning distillation...", true);
        const resp = await axios.post('/api/tiger/distill');
        if (resp.data && resp.data.success) {
            showScalperToast(resp.data.message || "Distillation complete!", true);
            loadTigerPage();
        } else {
            showScalperToast(resp.data.message || "Distillation: Insufficient trades.", false);
        }
    } catch (e) {
        showScalperToast("Distillation error: " + e.message, false);
    }
}

async function resetTigerQuarantine() {
    try {
        const resp = await axios.post('/api/tiger/reset-quarantine');
        if (resp.data && resp.data.success) {
            showScalperToast("Quarantined symbols & cooldowns reset to clear!", true);
            loadTigerPage();
        } else {
            showScalperToast("Reset failed: " + (resp.data.error || "Unknown"), false);
        }
    } catch (e) {
        showScalperToast("Reset error: " + e.message, false);
    }
}

// Auto-run on DOM ready
document.addEventListener('DOMContentLoaded', function() {
    loadScalperPage();

    // Auto-refresh scalper telemetry every 3 seconds if active view is scalper
    setInterval(() => {
        if (typeof currentActiveView !== 'undefined' && currentActiveView === 'scalper') {
            if (currentScalperSubTab === 'tiger') {
                loadTigerStatus();
            } else {
                loadScalperTelemetry();
            }
        }
    }, 3000);
});
