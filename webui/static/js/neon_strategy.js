(function () {
    'use strict';

    let neonCachedData = null;
    let neonDynamicState = null;
    let neonDynamicMode = 'live'; // 'live' | 'win' | 'bleed'
    let neonLatestAiPatch = null;

    function escapeHtml(str) {
        return String(str ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function fmtUsd(val, showSign) {
        const num = Number(val || 0);
        const sign = showSign ? (num > 0 ? '+' : num < 0 ? '-' : '') : (num < 0 ? '-' : '');
        return `${sign}$${Math.abs(num).toFixed(2)}`;
    }

    function fmtPrice(val) {
        const n = Number(val || 0);
        if (n >= 1000) return `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        if (n >= 1) return `$${n.toFixed(4)}`;
        return `$${n.toFixed(6)}`;
    }

    function setElText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function renderConfigControls(cfg) {
        if (!cfg) return;
        const badge = document.getElementById('neon-state-badge');
        if (badge) {
            badge.textContent = cfg.enabled ? 'ACTIVE · MAKER-FIRST' : 'STANDBY';
            badge.className = cfg.enabled ? 'badge-regime regime-bull' : 'badge-regime regime-chop';
        }
        const toggleBtn = document.getElementById('neon-toggle-btn');
        if (toggleBtn) {
            toggleBtn.textContent = cfg.enabled ? 'Pause Neon Engine' : 'Activate Neon Engine';
            toggleBtn.className = cfg.enabled ? 'btn-danger btn-sm' : 'btn-primary btn-sm';
        }

        const setVal = (id, v) => {
            const el = document.getElementById(id);
            if (el) el.value = String(v);
        };
        const setChk = (id, v) => {
            const el = document.getElementById(id);
            if (el) el.checked = Boolean(v);
        };

        setVal('neon-cfg-risk', cfg.risk_per_trade_pct);
        setVal('neon-cfg-adx', cfg.min_adx_14);
        setVal('neon-cfg-tp-r', cfg.tp_r_multiple);
        setVal('neon-cfg-cooldown', cfg.sl_cooldown_minutes);
        setVal('neon-cfg-max-pos', cfg.max_concurrent_positions);
        setChk('neon-cfg-session-gate', cfg.session_gate_enabled);
        setChk('neon-cfg-quarantine-allow', cfg.allow_quarantined_symbols);
    }

    function renderForensicKpis(audit, scanner) {
        if (!audit) return;
        const base = audit.baseline || {};
        const neon = audit.neon_counterfactual || {};
        const antiNoise = audit.neon_anti_noise || {};

        setElText('neon-kpi-wr', `${neon.win_rate_pct ?? 0}%`);
        setElText('neon-kpi-wr-sub', `vs ${base.win_rate_pct ?? 0}% baseline (${antiNoise.win_rate_pct ?? 0}% >60m hold)`);

        setElText('neon-kpi-pf', `${neon.profit_factor ?? 0}x`);
        setElText('neon-kpi-pf-sub', `vs ${base.profit_factor ?? 0}x baseline (${antiNoise.profit_factor ?? 0}x >60m hold)`);

        setElText('neon-kpi-net', fmtUsd(neon.net_pnl_usd, true));
        setElText('neon-kpi-net-sub', `vs ${fmtUsd(base.net_pnl_usd, true)} across ${base.trades ?? 0} live trades`);

        setElText('neon-kpi-fee', `${neon.fee_drag_pct ?? 0}%`);
        setElText('neon-kpi-fee-sub', `Down from ${base.fee_drag_pct ?? 0}% (${fmtUsd(base.fees_usd)} → ${fmtUsd(neon.fees_usd)})`);

        setElText('neon-kpi-dd', `-${fmtUsd(neon.max_drawdown_usd, false)}`);
        setElText('neon-kpi-dd-sub', `vs -${fmtUsd(base.max_drawdown_usd, false)} baseline (-88% DD cut)`);

        if (scanner) {
            setElText('neon-live-session', scanner.session_window || '--');
            setElText('neon-live-regime', `${scanner.macro_regime} (${scanner.macro_breadth_pct}%)`);
            setElText('neon-live-approved', `${scanner.approved_count} / ${(scanner.evaluations || []).length}`);
        }

        // Render key findings list
        const findingsEl = document.getElementById('neon-key-findings');
        if (findingsEl && Array.isArray(audit.key_findings)) {
            findingsEl.innerHTML = audit.key_findings
                .map((item) => `<li class="neon-finding-item">${item}</li>`)
                .join('');
        }
    }

    function renderScannerTable(scanner) {
        const tbody = document.getElementById('neon-scanner-tbody');
        if (!tbody) return;
        const rows = (scanner && scanner.evaluations) || [];
        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="10" class="empty-cell">No universe evaluations available.</td></tr>';
            return;
        }

        tbody.innerHTML = rows
            .map((ev) => {
                const gatesHtml = (ev.gates || [])
                    .map(
                        (g) =>
                            `<span class="neon-gate-chip ${g.passed ? 'gate-pass' : 'gate-fail'}" title="${g.gate}: ${g.detail}">${g.gate.slice(0, 2)}</span>`
                    )
                    .join('');

                const sideClass =
                    ev.side === 'LONG' ? 'regime-bull' : ev.side === 'SHORT' ? 'regime-bear' : 'regime-chop';
                const statusBadge = ev.approved
                    ? '<span class="badge-regime regime-bull">APPROVED</span>'
                    : '<span class="badge-regime regime-chop">GATED</span>';

                const t = ev.ticket;
                const levelsHtml = t
                    ? `<div class="mono-stack">
                         <span>SL: <strong class="text-neg">${fmtPrice(t.stop_loss)}</strong> (-${t.sl_distance_pct}%)</span>
                         <span>TP: <strong class="text-pos">${fmtPrice(t.take_profit)}</strong> (+${t.tp_distance_pct}%)</span>
                         <span class="text-muted">BE Lock: ${fmtPrice(t.be_lock_price)} · Fee/TP: ${t.fee_to_tp_ratio_pct}%</span>
                       </div>`
                    : '<span class="text-muted">Awaiting Regime Alignment</span>';

                const actionBtn = t
                    ? `<button type="button" class="${ev.approved ? 'btn-primary' : 'btn-secondary'} btn-sm" onclick="dispatchNeonTicket('${ev.symbol}')">${ev.approved ? 'Execute Neon' : 'Stage Paper'}</button>`
                    : '<span class="text-muted">--</span>';

                return `<tr>
                    <td>
                        <strong>${ev.symbol}</strong>
                        <div class="text-muted" style="font-size:10px;">${ev.tier === 'CORE_TIER_1' ? 'Tier-1 Core' : 'Quarantined'}</div>
                    </td>
                    <td class="mono">${fmtPrice(ev.price)}</td>
                    <td><span class="badge-regime ${sideClass}">${ev.side}</span></td>
                    <td class="mono">${ev.adx_14} / ${ev.extension_atr}σ</td>
                    <td class="mono">${ev.atr_14_pct}%</td>
                    <td><div class="neon-gates-row">${gatesHtml}</div></td>
                    <td class="mono"><strong>${ev.conviction_pct}%</strong></td>
                    <td>${statusBadge}<div class="text-muted" style="font-size:10.5px;margin-top:3px;max-width:200px;white-space:normal;">${ev.veto_reason || 'All 6 Institutional Gates Passed'}</div></td>
                    <td>${levelsHtml}</td>
                    <td>${actionBtn}</td>
                </tr>`;
            })
            .join('');
    }

    function renderMetricRows(tbodyId, rows, includeTier) {
        const tbody = document.getElementById(tbodyId);
        if (!tbody || !Array.isArray(rows)) return;
        tbody.innerHTML = rows
            .map((r) => {
                const pnlClass = r.net_pnl_usd >= 0 ? 'text-pos' : 'text-neg';
                const wrClass = r.win_rate_pct >= 58 ? 'text-pos' : r.win_rate_pct < 45 ? 'text-neg' : 'text-amber';
                const tierCell = includeTier
                    ? `<td><span class="badge-regime ${r.tier === 'CORE_TIER_1' ? 'regime-bull' : 'regime-bear'}">${r.tier === 'CORE_TIER_1' ? 'CORE TIER-1' : 'QUARANTINE'}</span></td>`
                    : '';
                return `<tr>
                    <td><strong>${r.label}</strong></td>
                    ${tierCell}
                    <td class="mono">${r.trades}</td>
                    <td class="mono ${wrClass}"><strong>${r.win_rate_pct}%</strong></td>
                    <td class="mono">${r.profit_factor}x</td>
                    <td class="mono ${pnlClass}"><strong>${fmtUsd(r.net_pnl_usd, true)}</strong></td>
                    <td class="mono">${fmtUsd(r.fees_usd, false)} (${r.fee_drag_pct}%)</td>
                    <td class="mono text-neg">-${fmtUsd(r.max_drawdown_usd, false)}</td>
                </tr>`;
            })
            .join('');
    }

    function renderBacktestResult(bt) {
        if (!bt) return;
        setElText('neon-bt-source', `${bt.symbol} · ${bt.regime_mode === 'MIRRORED_BULL_STRESS' ? 'Mirrored Bull Stress Test' : 'Real Market 1h OHLCV'} · ${bt.source}`);
        setElText('neon-bt-wr', `${bt.win_rate_pct}% (${bt.wins}W / ${bt.losses}L)`);
        setElText('neon-bt-pf', `${bt.profit_factor}x`);
        setElText('neon-bt-net', `${fmtUsd(bt.net_pnl_usd, true)} (${bt.net_return_pct >= 0 ? '+' : ''}${bt.net_return_pct}%)`);
        setElText('neon-bt-dd', `-${fmtUsd(bt.max_drawdown_usd, false)} (${bt.max_drawdown_pct}%)`);
        setElText('neon-bt-fees', `${fmtUsd(bt.total_fees_usd, false)} (${bt.fee_drag_pct}% drag)`);

        const netEl = document.getElementById('neon-bt-net');
        if (netEl) netEl.className = `card-value ${bt.net_pnl_usd >= 0 ? 'text-pos' : 'text-neg'}`;

        const tbody = document.getElementById('neon-bt-trades-tbody');
        if (!tbody) return;
        const trades = bt.trades || [];
        if (!trades.length) {
            tbody.innerHTML = '<tr><td colspan="9" class="empty-cell">No trades triggered under current strict 6-gate rules for this sample window.</td></tr>';
            return;
        }

        tbody.innerHTML = trades
            .map((t) => {
                const pnlClass = t.net_pnl_usd >= 0 ? 'text-pos' : 'text-neg';
                const sideClass = t.side === 'LONG' ? 'regime-bull' : 'regime-bear';
                return `<tr>
                    <td class="mono">${String(t.entry_time || '').replace('T', ' ').slice(0, 16)}</td>
                    <td><span class="badge-regime ${sideClass}">${t.side}</span></td>
                    <td class="mono">${fmtPrice(t.entry_price)}</td>
                    <td class="mono">${fmtPrice(t.exit_price)}</td>
                    <td class="mono">${fmtUsd(t.notional_usd, false)}</td>
                    <td class="mono">${t.bars_held}h</td>
                    <td><span class="badge-regime badge-info">${t.exit_reason}</span></td>
                    <td class="mono">${fmtUsd(t.fee_usd, false)}</td>
                    <td class="mono ${pnlClass}"><strong>${fmtUsd(t.net_pnl_usd, true)}</strong></td>
                </tr>`;
            })
            .join('');
    }

    async function loadNeonStrategy() {
        try {
            const resp = await axios.get('/api/neon/overview', { timeout: 10000 });
            const data = resp.data;
            if (!data || !data.success) return;
            neonCachedData = data;

            renderConfigControls(data.strategy && data.strategy.config);
            renderForensicKpis(data.forensic_audit, data.live_scanner);
            renderScannerTable(data.live_scanner);

            if (data.forensic_audit) {
                renderMetricRows('neon-progression-tbody', data.forensic_audit.progression, false);
                renderMetricRows('neon-session-tbody', data.forensic_audit.session_alpha, false);
                renderMetricRows('neon-duration-tbody', data.forensic_audit.duration_alpha, false);
                renderMetricRows('neon-symbol-tbody', data.forensic_audit.symbol_rankings, true);
            }

            if (data.benchmarks) {
                const bear = data.benchmarks.real_bear_1h;
                const bull = data.benchmarks.mirrored_bull_1h;
                setElText(
                    'neon-bench-bear',
                    bear ? `${bear.win_rate_pct}% WR · ${bear.profit_factor}x PF · ${fmtUsd(bear.net_pnl_usd, true)}` : '--'
                );
                setElText(
                    'neon-bench-bull',
                    bull ? `${bull.win_rate_pct}% WR · ${bull.profit_factor}x PF · ${fmtUsd(bull.net_pnl_usd, true)}` : '--'
                );
                renderBacktestResult(bear);
            }

            if (typeof window.loadNeonEquityCurve === 'function') {
                window.loadNeonEquityCurve();
            }
            if (typeof window.runNeonWinSimulationUI === 'function' && !window.getLatestNeonWinSimulation?.()) {
                window.runNeonWinSimulationUI();
            }
            if (typeof window.loadNeonCandlesticks === 'function') {
                window.loadNeonCandlesticks();
            }
            loadNeonDynamicState();
        } catch (err) {
            if (typeof window.showKronosToast === 'function') {
                window.showKronosToast('Failed to load NEON Strategy telemetry.', 'error');
            }
            console.warn('NEON Strategy load failed:', err);
        }
    }

    async function saveNeonStrategyConfig(overridePatch) {
        try {
            const payload = overridePatch || {
                risk_per_trade_pct: Number(document.getElementById('neon-cfg-risk')?.value || 1.5),
                min_adx_14: Number(document.getElementById('neon-cfg-adx')?.value || 18),
                tp_r_multiple: Number(document.getElementById('neon-cfg-tp-r')?.value || 2.0),
                sl_cooldown_minutes: Number(document.getElementById('neon-cfg-cooldown')?.value || 45),
                max_concurrent_positions: Number(document.getElementById('neon-cfg-max-pos')?.value || 3),
                session_gate_enabled: Boolean(document.getElementById('neon-cfg-session-gate')?.checked),
                allow_quarantined_symbols: Boolean(document.getElementById('neon-cfg-quarantine-allow')?.checked),
            };
            const resp = await axios.post('/api/neon/config', payload);
            if (resp.data && resp.data.success) {
                if (typeof window.showKronosToast === 'function') {
                    window.showKronosToast(resp.data.message || 'NEON config saved.', 'success');
                }
                await loadNeonStrategy();
            }
        } catch (err) {
            if (typeof window.showKronosToast === 'function') {
                window.showKronosToast('Failed to save NEON configuration.', 'error');
            }
        }
    }

    async function toggleNeonEngine() {
        const currentlyEnabled = Boolean(neonCachedData?.strategy?.config?.enabled ?? true);
        await saveNeonStrategyConfig({ enabled: !currentlyEnabled });
    }

    async function runNeonInteractiveBacktest() {
        try {
            const symbol = document.getElementById('neon-bt-symbol')?.value || 'BTCUSDT';
            const mode = document.getElementById('neon-bt-mode')?.value || 'REAL';
            const equity = Number(document.getElementById('neon-bt-equity')?.value || 200);
            const btn = document.getElementById('neon-bt-run-btn');
            if (btn) {
                btn.disabled = true;
                btn.textContent = 'Running Decimal Sim...';
            }
            const resp = await axios.post('/api/neon/backtest', {
                symbol,
                initial_equity: equity,
                mirror_bull: mode === 'MIRROR_BULL',
            });
            if (resp.data && resp.data.success) {
                renderBacktestResult(resp.data.backtest);
                if (typeof window.showKronosToast === 'function') {
                    const bt = resp.data.backtest;
                    window.showKronosToast(
                        `NEON Backtest (${bt.symbol}): ${bt.win_rate_pct}% WR · ${bt.profit_factor}x PF · ${fmtUsd(bt.net_pnl_usd, true)}`,
                        'success'
                    );
                }
            }
        } catch (err) {
            if (typeof window.showKronosToast === 'function') {
                window.showKronosToast('Backtest execution failed.', 'error');
            }
        } finally {
            const btn = document.getElementById('neon-bt-run-btn');
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Run Exact-Decimal Backtest';
            }
        }
    }

    async function dispatchNeonTicket(symbol) {
        const ev = (neonCachedData?.live_scanner?.evaluations || []).find((x) => x.symbol === symbol);
        if (!ev || !ev.ticket) return;
        try {
            const resp = await axios.post('/api/neon/execute', {
                symbol: ev.symbol,
                side: ev.ticket.side,
                entry_price: ev.ticket.entry_price,
                stop_loss: ev.ticket.stop_loss,
                take_profit: ev.ticket.take_profit,
                notional_usd: ev.ticket.notional_usd,
            });
            if (resp.data && resp.data.success) {
                if (typeof window.showKronosToast === 'function') {
                    window.showKronosToast(resp.data.message, 'success');
                }
                if (typeof loadBotDashboard === 'function') {
                    loadBotDashboard();
                }
                await loadNeonStrategy();
            }
        } catch (err) {
            if (typeof window.showKronosToast === 'function') {
                window.showKronosToast('Failed to dispatch NEON ticket.', 'error');
            }
        }
    }

    // =========================================================================
    // NEON v2.0 Dynamic Adaptive Engine & AI-Assisted Bleed Auditor
    // =========================================================================

    function tierColorClass(tier) {
        if (tier === 'CRITICAL_BLEED_LOCK') return 'text-neg';
        if (tier === 'BLEED_WARNING') return 'text-neg';
        if (tier === 'WATCH') return 'text-amber';
        return 'text-pos';
    }

    function renderDynamicState(dyn) {
        if (!dyn) return;
        neonDynamicState = dyn;
        const micro = dyn.microstructure || {};
        const bleed = dyn.bleed_telemetry || {};
        const ap = dyn.adaptive_params || {};

        const liveBtn = document.getElementById('neon-bleed-mode-live');
        const winBtn = document.getElementById('neon-bleed-mode-win');
        const drillBtn = document.getElementById('neon-bleed-mode-drill');
        if (liveBtn) liveBtn.classList.toggle('active', neonDynamicMode === 'live');
        if (winBtn) winBtn.classList.toggle('active', neonDynamicMode === 'win');
        if (drillBtn) drillBtn.classList.toggle('active', neonDynamicMode === 'bleed');

        const adaptBtn = document.getElementById('neon-dyn-adapt-btn');
        if (adaptBtn) {
            adaptBtn.textContent = `Auto-Adapt: ${dyn.dynamic_adaptation_enabled ? 'ON' : 'OFF'}`;
            adaptBtn.className = dyn.dynamic_adaptation_enabled ? 'btn-primary btn-sm' : 'btn-secondary btn-sm';
        }
        const guardBtn = document.getElementById('neon-dyn-guard-btn');
        if (guardBtn) {
            guardBtn.textContent = `Bleed Guard: ${dyn.auto_bleed_guard_enabled ? 'ON' : 'OFF'}`;
            guardBtn.className = dyn.auto_bleed_guard_enabled ? 'btn-primary btn-sm' : 'btn-secondary btn-sm';
        }

        setElText('neon-dyn-regime', String(micro.regime || 'NORMAL_BALANCED').replace(/_/g, ' '));
        const tierEl = document.getElementById('neon-dyn-tier');
        if (tierEl) {
            const modeTag =
                bleed.data_mode === 'BLEED_STRESS_DRILL'
                    ? ' [DRILL]'
                    : bleed.data_mode === 'WIN_SIMULATION'
                    ? ' [WIN SIM]'
                    : '';
            tierEl.textContent = `${String(bleed.circuit_tier || 'NOMINAL').replace(/_/g, ' ')} · ${bleed.bleed_score ?? 0}/100${modeTag}`;
            tierEl.className = `neon-eq-stat-val ${tierColorClass(bleed.circuit_tier)}`;
        }

        const expEl = document.getElementById('neon-dyn-exp');
        if (expEl) {
            const expVal = Number(bleed.rolling_10_expectancy_usd || 0);
            expEl.textContent = `${fmtUsd(expVal, true)}/trade · ${bleed.rolling_10_win_rate_pct ?? 0}% WR`;
            expEl.className = `neon-eq-stat-val ${expVal >= 0 ? 'text-pos' : 'text-neg'}`;
        }

        const ddStreakEl = document.getElementById('neon-dyn-dd-streak');
        if (ddStreakEl) {
            ddStreakEl.textContent = `-${bleed.current_drawdown_pct ?? 0}% DD · ${bleed.consecutive_losses ?? 0}L streak`;
            ddStreakEl.className = `neon-eq-stat-val ${(bleed.current_drawdown_pct >= 2.5 || bleed.consecutive_losses >= 3) ? 'text-neg' : 'text-cyan'}`;
        }

        setElText('neon-dyn-risk-mult', `${ap.effective_risk_pct ?? 1.5}% (${ap.risk_multiplier ?? 1}x · Kelly ${ap.kelly_half_pct ?? 1}%)`);
        setElText('neon-dyn-vol-meta', `ATR Vol Ratio: ${micro.vol_expansion_ratio ?? 1}x · Avg ADX: ${micro.avg_adx_14 ?? 20} · Avg ATR: ${micro.avg_atr_pct ?? 0}%`);
        setElText('neon-dyn-feedrag', `Fee Drag: ${bleed.fee_drag_ratio_pct ?? 0}% · Vel: ${fmtUsd(bleed.bleed_velocity_usd_per_trade, true)}/t`);

        const fmtDiff = (base, eff, suffix) => {
            const changed = Number(base) !== Number(eff);
            return changed ? `${base}${suffix} → ${eff}${suffix}` : `${eff}${suffix}`;
        };
        setElText('ndp-risk', fmtDiff(ap.base_risk_pct, ap.effective_risk_pct, '%'));
        setElText('ndp-adx', fmtDiff(ap.base_min_adx, ap.effective_min_adx, ''));
        setElText('ndp-sl', fmtDiff(ap.base_sl_atr, ap.effective_sl_atr, 'x ATR'));
        setElText('ndp-tp', fmtDiff(ap.base_tp_r, ap.effective_tp_r, 'R'));
        setElText('ndp-slots', fmtDiff(ap.base_max_slots, ap.effective_max_slots, ''));
        setElText('ndp-cd', fmtDiff(ap.base_cooldown_min, ap.effective_cooldown_min, 'm'));

        const trigBox = document.getElementById('neon-dyn-triggers');
        if (trigBox) {
            const lines = [...(ap.adaptation_reasons || []), ...(bleed.triggers || [])];
            trigBox.innerHTML = lines
                .map((line) => `<div class="neon-dyn-trigger-line">${escapeHtml(line)}</div>`)
                .join('');
        }

        const symBox = document.getElementById('neon-dyn-symbols-list');
        if (symBox && Array.isArray(bleed.symbol_health)) {
            symBox.innerHTML = bleed.symbol_health
                .map((s) => {
                    const stCls = s.status === 'BLEEDING' ? 'text-neg' : s.status === 'DRIFTING' ? 'text-amber' : 'text-pos';
                    const pnlCls = s.net_pnl_usd >= 0 ? 'text-pos' : 'text-neg';
                    return `<div class="neon-dyn-sym-row">
                        <span class="mono"><strong>${escapeHtml(s.symbol)}</strong></span>
                        <span class="mono text-muted">${s.trades}T (${s.win_rate_pct}% WR)</span>
                        <span class="mono ${pnlCls}"><strong>${fmtUsd(s.net_pnl_usd, true)}</strong></span>
                        <span class="mono ${stCls}">${escapeHtml(s.status)}</span>
                    </div>`;
                })
                .join('');
        }

        if (dyn.latest_ai_assessment) {
            renderAiAssessment(dyn.latest_ai_assessment);
        }
    }

    function renderAiAssessment(a) {
        if (!a) return;
        neonLatestAiPatch = a.recommended_config_patch || null;

        const emptyEl = document.getElementById('neon-ai-empty-state');
        const wrapEl = document.getElementById('neon-ai-result-wrap');
        const errEl = document.getElementById('neon-ai-error-box');
        if (emptyEl) emptyEl.style.display = 'none';
        if (errEl) errEl.style.display = 'none';
        if (wrapEl) wrapEl.style.display = 'flex';

        const ts = String(a.timestamp_utc || '').replace('T', ' ').slice(0, 19) + ' UTC';
        setElText('neon-ai-audit-meta', `${a.model || 'gemini-4-hydrogen'} · ${ts} · ${a.confidence_pct ?? 85}% conf`);
        setElText('neon-ai-headline', a.diagnosis_headline || 'NEON Bleed Audit Complete');

        const vm = document.getElementById('neon-ai-verdict-meta');
        if (vm) {
            const modeTag =
                a.data_mode === 'BLEED_STRESS_DRILL'
                    ? ' · Stress Drill'
                    : a.data_mode === 'WIN_SIMULATION'
                    ? ' · Win Simulation'
                    : ' · Live';
            vm.textContent = `${String(a.bleed_severity || 'NOMINAL').replace(/_/g, ' ')} · Score ${a.bleed_score_at_audit ?? 0}/100${modeTag}`;
            vm.className = `neon-ai-verdict-meta ${tierColorClass(a.bleed_severity)}`;
        }

        setElText('neon-ai-summary', `${a.executive_summary || ''} ${a.expected_impact_summary ? `Expected Impact: ${a.expected_impact_summary}` : ''}`.trim());

        const causesEl = document.getElementById('neon-ai-causes');
        if (causesEl) {
            const causes = Array.isArray(a.root_causes) ? a.root_causes : [];
            causesEl.innerHTML = causes.length
                ? causes
                      .map((c) => {
                          const sevCls = c.severity === 'CRITICAL' || c.severity === 'HIGH' ? 'text-neg' : c.severity === 'MEDIUM' ? 'text-amber' : 'text-cyan';
                          return `<div class="neon-ai-cause-row">
                              <div class="neon-ai-cause-top">
                                  <span class="mono"><strong>${escapeHtml(c.category)}</strong></span>
                                  <span class="mono ${sevCls}">${escapeHtml(c.severity)}</span>
                              </div>
                              <div class="neon-ai-cause-desc">${escapeHtml(c.evidence)} — ${escapeHtml(c.impact)}</div>
                          </div>`;
                      })
                      .join('')
                : '<div class="neon-dyn-trigger-line">No severe bleed vectors detected.</div>';
        }

        const planEl = document.getElementById('neon-ai-plan-list');
        if (planEl) {
            const steps = Array.isArray(a.surgical_remediation_plan) ? a.surgical_remediation_plan : [];
            planEl.innerHTML = steps.map((s) => `<li>${escapeHtml(s)}</li>`).join('');
        }

        const previewEl = document.getElementById('neon-ai-patch-preview');
        const applyBtn = document.getElementById('neon-ai-apply-btn');
        if (previewEl && neonLatestAiPatch) {
            const p = neonLatestAiPatch;
            const qList = Array.isArray(a.symbols_to_quarantine) && a.symbols_to_quarantine.length
                ? ` · Watch/Quarantine: ${a.symbols_to_quarantine.join(', ')}`
                : '';
            previewEl.textContent = `Patch: Risk ${p.risk_per_trade_pct}% · ADX >= ${p.min_adx_14} · SL ${p.sl_atr_multiplier}x ATR · TP ${p.tp_r_multiple}R · Slots ${p.max_concurrent_positions} · Cooldown ${p.sl_cooldown_minutes}m${qList}`;
            if (applyBtn) applyBtn.disabled = false;
        }
    }

    async function loadNeonDynamicState() {
        try {
            const resp = await axios.get('/api/neon/dynamic-state', {
                params: {
                    simulate_bleed: neonDynamicMode === 'bleed' ? 'true' : 'false',
                    simulate_win: neonDynamicMode === 'win' ? 'true' : 'false',
                },
                timeout: 12000,
            });
            if (resp.data && resp.data.success && resp.data.dynamic_state) {
                renderDynamicState(resp.data.dynamic_state);
            }
        } catch (err) {
            console.warn('Failed to load NEON dynamic state:', err);
        }
    }

    function setNeonDynamicTelemetryMode(mode) {
        const next = mode === 'bleed' ? 'bleed' : mode === 'win' ? 'win' : 'live';
        if (next === neonDynamicMode) return;
        neonDynamicMode = next;
        loadNeonDynamicState();
    }

    function setNeonBleedDrillMode(enableDrill) {
        setNeonDynamicTelemetryMode(enableDrill ? 'bleed' : 'live');
    }

    async function toggleNeonDynamicFlag(flagName) {
        if (!neonDynamicState) return;
        const currentVal = Boolean(neonDynamicState[flagName]);
        try {
            const resp = await axios.post('/api/neon/dynamic-mode', {
                [flagName]: !currentVal,
                simulate_bleed: neonDynamicMode === 'bleed',
                simulate_win: neonDynamicMode === 'win',
            });
            if (resp.data && resp.data.success) {
                if (resp.data.dynamic_state) renderDynamicState(resp.data.dynamic_state);
                if (typeof window.showKronosToast === 'function') {
                    window.showKronosToast(resp.data.message || 'Dynamic mode updated.', 'success');
                }
            }
        } catch (err) {
            if (typeof window.showKronosToast === 'function') {
                window.showKronosToast('Failed to update NEON dynamic mode.', 'error');
            }
        }
    }

    async function runNeonAiBleedAudit() {
        const btn = document.getElementById('neon-ai-run-btn');
        const errEl = document.getElementById('neon-ai-error-box');
        const focusInput = document.getElementById('neon-ai-focus-input');
        const focusNote = focusInput ? focusInput.value.trim() : '';

        if (errEl) {
            errEl.style.display = 'none';
            errEl.textContent = '';
        }
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Auditing Telemetry...';
        }

        try {
            const resp = await axios.post(
                '/api/neon/ai-bleed-audit',
                {
                    simulate_bleed: neonDynamicMode === 'bleed',
                    simulate_win: neonDynamicMode === 'win',
                    focus_note: focusNote,
                },
                { timeout: 60000 }
            );
            if (resp.data && resp.data.success && resp.data.assessment) {
                renderAiAssessment(resp.data.assessment);
                if (typeof window.showKronosToast === 'function') {
                    window.showKronosToast(
                        `AI Strategy Audit complete (${resp.data.assessment.bleed_severity}). Review & apply patch below.`,
                        'success'
                    );
                }
            } else {
                throw new Error((resp.data && resp.data.error) || 'AI Strategy Audit failed.');
            }
        } catch (err) {
            const msg =
                (err && err.response && err.response.data && err.response.data.error) ||
                (err && err.message) ||
                'AI Strategy Audit request failed.';
            if (errEl) {
                errEl.textContent = msg;
                errEl.style.display = 'block';
            }
            if (typeof window.showKronosToast === 'function') {
                window.showKronosToast(msg, 'error');
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Run AI Bleed Audit';
            }
        }
    }

    async function applyNeonAiPatch() {
        if (!neonLatestAiPatch) return;
        const btn = document.getElementById('neon-ai-apply-btn');
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Applying...';
        }
        try {
            const resp = await axios.post('/api/neon/ai-apply-patch', {
                patch: neonLatestAiPatch,
                simulate_bleed: neonDynamicMode === 'bleed',
                simulate_win: neonDynamicMode === 'win',
            });
            if (resp.data && resp.data.success) {
                if (typeof window.showKronosToast === 'function') {
                    window.showKronosToast(resp.data.message || 'AI remediation patch applied.', 'success');
                }
                if (resp.data.dynamic_state) renderDynamicState(resp.data.dynamic_state);
                await loadNeonStrategy();
                if (window.BotSwarmBridge && typeof window.BotSwarmBridge.syncNeonTelemetry === 'function') {
                    window.BotSwarmBridge.syncNeonTelemetry();
                }
            }
        } catch (err) {
            if (typeof window.showKronosToast === 'function') {
                window.showKronosToast('Failed to apply AI remediation patch.', 'error');
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Apply AI Patch';
            }
        }
    }

    window.loadNeonStrategy = loadNeonStrategy;
    window.saveNeonStrategyConfig = saveNeonStrategyConfig;
    window.toggleNeonEngine = toggleNeonEngine;
    window.runNeonInteractiveBacktest = runNeonInteractiveBacktest;
    window.dispatchNeonTicket = dispatchNeonTicket;
    window.loadNeonDynamicState = loadNeonDynamicState;
    window.setNeonDynamicTelemetryMode = setNeonDynamicTelemetryMode;
    window.setNeonBleedDrillMode = setNeonBleedDrillMode;
    window.toggleNeonDynamicFlag = toggleNeonDynamicFlag;
    window.runNeonAiBleedAudit = runNeonAiBleedAudit;
    window.applyNeonAiPatch = applyNeonAiPatch;
})();
