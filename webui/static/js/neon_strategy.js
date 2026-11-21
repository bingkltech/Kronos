(function () {
    'use strict';

    let neonCachedData = null;

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

    window.loadNeonStrategy = loadNeonStrategy;
    window.saveNeonStrategyConfig = saveNeonStrategyConfig;
    window.toggleNeonEngine = toggleNeonEngine;
    window.runNeonInteractiveBacktest = runNeonInteractiveBacktest;
    window.dispatchNeonTicket = dispatchNeonTicket;
})();
