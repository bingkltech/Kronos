(function () {
    'use strict';

    let csState = {
        symbol: 'BTCUSDT',
        interval: '1h',
        mode: 'OFF', // 'OFF' | 'VETO_CONFIRM' | 'DIRECT_TRIGGER'
        filter: 'ALL', // 'ALL' | 'ACTIVE' | 'BULLISH' | 'BEARISH' | 'INDECISION' | 'TIER_1'
        data: null,
        loading: false,
    };

    function escapeHtml(str) {
        return String(str ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function fmtUsd(val, showSign) {
        const n = Number(val || 0);
        const sign = showSign ? (n > 0 ? '+' : n < 0 ? '-' : '') : n < 0 ? '-' : '';
        return `${sign}$${Math.abs(n).toLocaleString('en-US', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        })}`;
    }

    function fmtBiasLabel(label) {
        return String(label || 'NEUTRAL').replace(/_/g, ' ');
    }

    function fmtGateAction(action) {
        const map = {
            CONFIRM_LONG: 'CONFIRM LONG',
            CONFIRM_SHORT: 'CONFIRM SHORT',
            VETO_LONG_KNIFE: 'VETO LONG (KNIFE)',
            VETO_SHORT_SQUEEZE: 'VETO SHORT (SQUEEZE)',
            POST_MAKER_LIMIT: 'ROUTE MAKER LIMIT',
            TIGHTEN_STOP_DOJI: 'TIGHTEN SL (DOJI)',
            NEUTRAL_PASS: 'NEUTRAL PASS',
        };
        return map[action] || String(action || 'NEUTRAL PASS');
    }

    function gateToneClass(action) {
        if (action === 'CONFIRM_LONG' || action === 'POST_MAKER_LIMIT') return 'text-pos';
        if (action === 'VETO_LONG_KNIFE' || action === 'CONFIRM_SHORT') return 'text-neg';
        if (action === 'VETO_SHORT_SQUEEZE') return 'text-cyan';
        if (action === 'TIGHTEN_STOP_DOJI') return 'text-amber';
        return 'text-secondary';
    }

    function scoreToneClass(score) {
        if (score >= 14) return 'text-pos';
        if (score <= -14) return 'text-neg';
        return 'text-amber';
    }

    function syncControls() {
        const symSel = document.getElementById('neon-cs-symbol');
        if (symSel) symSel.value = csState.symbol;

        ['15m', '1h', '4h'].forEach((tf) => {
            const btn = document.getElementById(`neon-cs-tf-${tf}`);
            if (btn) btn.classList.toggle('active', csState.interval === tf);
        });

        ['OFF', 'VETO_CONFIRM', 'DIRECT_TRIGGER'].forEach((m) => {
            const btn = document.getElementById(`neon-cs-mode-${m}`);
            if (btn) btn.classList.toggle('active', csState.mode === m);
        });

        ['ALL', 'ACTIVE', 'BULLISH', 'BEARISH', 'INDECISION', 'TIER_1'].forEach((f) => {
            const btn = document.getElementById(`neon-cs-filter-${f}`);
            if (btn) btn.classList.toggle('active', csState.filter === f);
        });
    }

    function renderModeBenchmarks(benchmarks) {
        const host = document.getElementById('neon-cs-ab-grid');
        if (!host) return;
        if (!Array.isArray(benchmarks) || !benchmarks.length) {
            host.innerHTML = '<div class="neon-ai-empty-state">A/B decision-mode benchmarks unavailable.</div>';
            return;
        }

        host.innerHTML = benchmarks
            .map((b) => {
                const isActive = csState.mode === b.mode;
                const mcPnl = Number(b.mc_p50_pnl_usd ?? b.net_pnl_usd ?? 0);
                const mcDelta = Number(b.delta_mc_p50_vs_off_usd ?? b.delta_pnl_vs_off_usd ?? 0);
                const pnlCls = mcPnl >= 0 ? 'text-pos' : 'text-neg';
                const deltaCls = mcDelta > 0 ? 'text-pos' : mcDelta < 0 ? 'text-neg' : 'text-muted';
                const deltaLabel =
                    b.mode === 'OFF'
                        ? 'Baseline'
                        : `${fmtUsd(mcDelta, true)} vs Off`;
                const recTag = b.recommended ? ' · Recommended' : '';
                const modeLabel =
                    b.mode === 'VETO_CONFIRM'
                        ? 'Veto & Maker Gate'
                        : b.mode === 'DIRECT_TRIGGER'
                        ? 'Raw Top-25 Trigger'
                        : 'Candlesticks Off';

                return `<div class="neon-cs-ab-col ${isActive ? 'is-selected' : ''}">
                    <div class="neon-cs-ab-top">
                        <div>
                            <div class="neon-cs-ab-title">${escapeHtml(modeLabel)}<span class="text-cyan">${recTag}</span></div>
                            <div class="neon-cs-ab-sub">${escapeHtml(b.role_summary)}</div>
                        </div>
                        <button type="button" class="${isActive ? 'btn-primary' : 'btn-secondary'} btn-sm" onclick="setNeonCandlestickMode('${b.mode}')">
                            ${isActive ? 'Active in Sim' : 'Apply to Sim'}
                        </button>
                    </div>
                    <div class="neon-cs-ab-metrics">
                        <div class="neon-cs-ab-kpi">
                            <span class="neon-eq-stat-lbl">250-Path MC Median (P50)</span>
                            <span class="mono ${pnlCls}"><strong>${fmtUsd(mcPnl, true)}</strong> <span class="${deltaCls}" style="font-size:11px;">(${deltaLabel})</span></span>
                        </div>
                        <div class="neon-cs-ab-kpi">
                            <span class="neon-eq-stat-lbl">MC P(Win) / Hero WR &amp; PF</span>
                            <span class="mono"><strong>${b.mc_win_prob_pct ?? 0}% P(Win)</strong> · ${b.win_rate_pct}% WR · ${b.profit_factor}x PF</span>
                        </div>
                        <div class="neon-cs-ab-kpi">
                            <span class="neon-eq-stat-lbl">Fee Drag / Slippage</span>
                            <span class="mono ${b.fee_drag_pct > 45 ? 'text-neg' : 'text-secondary'}">${b.fee_drag_pct}% drag · ${b.fee_bps}f / ${b.slippage_bps}s bps (${b.trades} tr)</span>
                        </div>
                        <div class="neon-cs-ab-kpi">
                            <span class="neon-eq-stat-lbl">MC Median DD / Fidelity</span>
                            <span class="mono">-${b.mc_median_dd_pct ?? b.max_drawdown_pct}% DD · ${b.calibration_score_pct}/100 fidelity</span>
                        </div>
                    </div>
                </div>`;
            })
            .join('');
    }

    function renderFleetStrip(summaries) {
        const host = document.getElementById('neon-cs-fleet-strip');
        if (!host) return;
        if (!Array.isArray(summaries) || !summaries.length) {
            host.innerHTML = '';
            return;
        }
        host.innerHTML = summaries
            .map((s) => {
                const active = s.symbol === csState.symbol;
                const scCls = scoreToneClass(s.composite_score);
                const gCls = gateToneClass(s.gate_action);
                const sign = s.composite_score > 0 ? '+' : '';
                return `<button type="button" class="neon-cs-fleet-btn ${active ? 'active' : ''}" onclick="setNeonCandlestickSymbol('${escapeHtml(s.symbol)}')">
                    <div class="neon-cs-fleet-row">
                        <strong class="mono">${escapeHtml(s.symbol.replace('USDT', ''))}</strong>
                        <span class="mono ${scCls}"><strong>${sign}${s.composite_score}</strong></span>
                    </div>
                    <div class="neon-cs-fleet-gate mono ${gCls}">${escapeHtml(fmtGateAction(s.gate_action))}</div>
                    <div class="neon-cs-fleet-pat">${escapeHtml(s.top_pattern_name)}</div>
                </button>`;
            })
            .join('');
    }

    function renderPatternsTable(patterns) {
        const tbody = document.getElementById('neon-cs-tbody');
        if (!tbody) return;
        if (!Array.isArray(patterns) || !patterns.length) {
            tbody.innerHTML = '<tr><td colspan="8" class="empty-cell">No candlestick scan data loaded.</td></tr>';
            return;
        }

        const filtered = patterns.filter((p) => {
            if (csState.filter === 'ACTIVE') return p.detected_recently;
            if (csState.filter === 'BULLISH') return p.bias === 'BULLISH';
            if (csState.filter === 'BEARISH') return p.bias === 'BEARISH';
            if (csState.filter === 'INDECISION') return p.bias === 'INDECISION';
            if (csState.filter === 'TIER_1') return p.tier === 'TIER_1_CORE';
            return true;
        });

        // Sort active detections first, then by rank
        const sorted = [...filtered].sort((a, b) => {
            if (a.detected_recently !== b.detected_recently) return a.detected_recently ? -1 : 1;
            if (a.detected_recently && b.detected_recently) {
                return Math.abs(b.active_score) - Math.abs(a.active_score);
            }
            return a.rank - b.rank;
        });

        if (!sorted.length) {
            tbody.innerHTML = `<tr><td colspan="8" class="empty-cell">No patterns matched filter "${escapeHtml(csState.filter)}" on ${escapeHtml(csState.symbol)} (${escapeHtml(csState.interval)}).</td></tr>`;
            return;
        }

        tbody.innerHTML = sorted
            .map((p) => {
                const biasCls =
                    p.bias === 'BULLISH' ? 'text-pos' : p.bias === 'BEARISH' ? 'text-neg' : 'text-amber';
                const tierLabel =
                    p.tier === 'TIER_1_CORE'
                        ? 'Tier-1 Core'
                        : p.tier === 'VETO_ONLY'
                        ? 'Veto / Filter'
                        : 'Tier-2';
                const liveHtml = p.detected_recently
                    ? `<strong class="${biasCls}">${p.bars_ago === 0 ? 'LIVE BAR' : `${p.bars_ago} bar${p.bars_ago > 1 ? 's' : ''} ago`}</strong> · ${p.latest_vol_ratio ?? 1}x vol · ${p.latest_body_atr ?? 0} ATR`
                    : '<span class="text-muted">Inactive (5 bars)</span>';

                const hitCls =
                    p.occurrences_512 === 0
                        ? 'text-muted'
                        : p.forward_3bar_hit_rate_pct >= 55
                        ? 'text-pos'
                        : p.forward_3bar_hit_rate_pct < 45
                        ? 'text-neg'
                        : 'text-amber';
                const hitText = p.occurrences_512 > 0 ? `${p.forward_3bar_hit_rate_pct}%` : '--';
                const atrMoveText =
                    p.occurrences_512 > 0
                        ? `${p.avg_3bar_move_atr >= 0 ? '+' : ''}${p.avg_3bar_move_atr} ATR`
                        : '--';

                return `<tr class="${p.detected_recently ? 'neon-cs-row-active' : ''}">
                    <td class="mono text-muted">#${String(p.rank).padStart(2, '0')}</td>
                    <td>
                        <strong>${escapeHtml(p.name)}</strong>
                        <div class="text-muted" style="font-size:11px;white-space:normal;max-width:290px;">${escapeHtml(p.description)}</div>
                    </td>
                    <td class="mono ${biasCls}"><strong>${escapeHtml(p.bias)}</strong></td>
                    <td class="mono text-secondary">${escapeHtml(p.family)} · ${tierLabel}</td>
                    <td class="mono">${liveHtml}</td>
                    <td class="mono">${p.occurrences_512} <span class="text-muted">(${p.avg_rel_volume}x vol)</span></td>
                    <td class="mono ${hitCls}"><strong>${hitText}</strong> <span class="text-muted">(${atrMoveText})</span></td>
                    <td class="text-secondary" style="font-size:11.5px;white-space:normal;">${escapeHtml(p.neon_role)}</td>
                </tr>`;
            })
            .join('');
    }

    function renderCandlestickPanel(payload) {
        if (!payload) return;
        csState.data = payload;
        const s = payload.selected_summary || {};
        const benchmarks = payload.mode_benchmarks || [];

        setText(
            'neon-cs-subtitle',
            `${payload.selected_symbol} · ${payload.interval} (${s.bars_analyzed || 512} tail bars) · ATR ${s.atr_14_pct ?? 0}% · Rel Vol ${s.rel_volume ?? 1}x SMA20`
        );

        const biasEl = document.getElementById('neon-cs-score');
        if (biasEl) {
            const sign = Number(s.composite_score || 0) > 0 ? '+' : '';
            biasEl.textContent = `${sign}${s.composite_score ?? 0} · ${fmtBiasLabel(s.bias_label)}`;
            biasEl.className = `neon-eq-stat-val ${scoreToneClass(Number(s.composite_score || 0))}`;
        }
        setText('neon-cs-score-sub', `Last Close $${Number(s.last_close || 0).toLocaleString('en-US', { maximumFractionDigits: 4 })} · ATR ${s.atr_14_pct ?? 0}%`);

        const gateEl = document.getElementById('neon-cs-gate');
        if (gateEl) {
            gateEl.textContent = fmtGateAction(s.gate_action);
            gateEl.className = `neon-eq-stat-val ${gateToneClass(s.gate_action)}`;
        }
        setText('neon-cs-gate-sub', s.gate_reason || '--');

        setText(
            'neon-cs-counts',
            `${s.bullish_active_count ?? 0} Bull · ${s.bearish_active_count ?? 0} Bear · ${s.indecision_active_count ?? 0} Doji`
        );
        setText('neon-cs-counts-sub', 'Detected inside last 5 closed bars');

        const topEl = document.getElementById('neon-cs-top-pat');
        if (topEl) {
            topEl.textContent = s.top_pattern_name || 'None';
            topEl.className = `neon-eq-stat-val ${
                s.top_pattern_bias === 'BULLISH'
                    ? 'text-pos'
                    : s.top_pattern_bias === 'BEARISH'
                    ? 'text-neg'
                    : 'text-secondary'
            }`;
        }
        setText(
            'neon-cs-top-pat-sub',
            s.top_pattern_bars_ago !== null && s.top_pattern_bars_ago !== undefined
                ? `${s.top_pattern_bias} · ${s.top_pattern_bars_ago === 0 ? 'Current closed bar' : `${s.top_pattern_bars_ago} bars ago`}`
                : 'Awaiting high-volume candle trigger'
        );

        const vetoBm = benchmarks.find((b) => b.mode === 'VETO_CONFIRM');
        const trigBm = benchmarks.find((b) => b.mode === 'DIRECT_TRIGGER');
        const edgeEl = document.getElementById('neon-cs-edge-delta');
        if (edgeEl && vetoBm) {
            const vDelta = Number(vetoBm.delta_mc_p50_vs_off_usd ?? vetoBm.delta_pnl_vs_off_usd ?? 0);
            edgeEl.textContent = `${fmtUsd(vDelta, true)} MC P50 (Veto)`;
            edgeEl.className = `neon-eq-stat-val ${vDelta >= 0 ? 'text-pos' : 'text-neg'}`;
        }
        if (vetoBm && trigBm) {
            const tDelta = Number(trigBm.delta_mc_p50_vs_off_usd ?? trigBm.delta_pnl_vs_off_usd ?? 0);
            setText(
                'neon-cs-edge-sub',
                `Veto P(Win) ${vetoBm.mc_win_prob_pct ?? 0}% vs Raw Top-25: ${fmtUsd(tDelta, true)} (${trigBm.mc_win_prob_pct ?? 0}% P(Win), ${trigBm.fee_drag_pct}% fee drag)`
            );
        }

        renderModeBenchmarks(benchmarks);
        renderFleetStrip(payload.fleet_summaries);
        renderPatternsTable(payload.patterns);
        syncControls();
    }

    async function loadNeonCandlesticks(opts) {
        if (opts && typeof opts === 'object') {
            if (opts.symbol) csState.symbol = String(opts.symbol).toUpperCase();
            if (opts.interval) csState.interval = String(opts.interval).toLowerCase();
            if (opts.mode) csState.mode = String(opts.mode).toUpperCase();
        }
        syncControls();

        const btn = document.getElementById('neon-cs-scan-btn');
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Scanning...';
        }
        csState.loading = true;

        try {
            const sim = typeof window.getLatestNeonWinSimulation === 'function' ? window.getLatestNeonWinSimulation() : null;
            const params = new URLSearchParams({
                symbol: csState.symbol,
                interval: csState.interval,
                mode: csState.mode,
                scenario: (sim && sim.scenario) || 'REALISTIC_LIVE_FRICTION',
                initial_equity: String((sim && sim.initial_equity_usd) || 1000),
                horizon_days: String((sim && sim.horizon_days) || 90),
                seed: String((sim && sim.seed) || 20261121),
                include_benchmarks: 'true',
            });
            const resp = await axios.get(`/api/neon/candlesticks?${params.toString()}`, { timeout: 15000 });
            if (resp.data && resp.data.success && resp.data.candlesticks) {
                renderCandlestickPanel(resp.data.candlesticks);
            } else {
                throw new Error((resp.data && resp.data.error) || 'Candlestick scan failed.');
            }
        } catch (err) {
            console.warn('NEON Candlestick Engine error:', err);
            if (typeof window.showKronosToast === 'function') {
                window.showKronosToast('Top 25 Candlestick scan failed.', 'error');
            }
        } finally {
            csState.loading = false;
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Scan Candles';
            }
        }
    }

    function setNeonCandlestickSymbol(sym) {
        loadNeonCandlesticks({ symbol: sym });
    }

    function setNeonCandlestickInterval(tf) {
        loadNeonCandlesticks({ interval: tf });
    }

    function setNeonCandlestickFilter(filterKey) {
        csState.filter = filterKey || 'ALL';
        syncControls();
        if (csState.data && csState.data.patterns) {
            renderPatternsTable(csState.data.patterns);
        }
    }

    function setNeonCandlestickMode(mode, skipWinSimTrigger) {
        const norm = mode === 'VETO_CONFIRM' ? 'VETO_CONFIRM' : mode === 'DIRECT_TRIGGER' ? 'DIRECT_TRIGGER' : 'OFF';
        csState.mode = norm;
        syncControls();
        if (csState.data && csState.data.mode_benchmarks) {
            renderModeBenchmarks(csState.data.mode_benchmarks);
        }
        if (!skipWinSimTrigger && typeof window.runNeonWinSimulationUI === 'function') {
            window.runNeonWinSimulationUI({ candlestickMode: norm });
        }
    }

    function syncCandlestickFromWinSim(sim) {
        if (!sim) return;
        if (sim.candlestick_mode && sim.candlestick_mode !== csState.mode) {
            csState.mode = sim.candlestick_mode;
            syncControls();
            if (csState.data && csState.data.mode_benchmarks) {
                renderModeBenchmarks(csState.data.mode_benchmarks);
            }
        }
    }

    window.loadNeonCandlesticks = loadNeonCandlesticks;
    window.setNeonCandlestickSymbol = setNeonCandlestickSymbol;
    window.setNeonCandlestickInterval = setNeonCandlestickInterval;
    window.setNeonCandlestickFilter = setNeonCandlestickFilter;
    window.setNeonCandlestickMode = setNeonCandlestickMode;
    window.syncCandlestickFromWinSim = syncCandlestickFromWinSim;
})();
