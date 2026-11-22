(function () {
    'use strict';

    let winSimState = {
        scenario: 'REALISTIC_LIVE_FRICTION',
        initialEquity: 1000,
        horizonDays: 90,
        dynamicCompounding: true,
        candlestickMode: 'OFF', // 'OFF' | 'VETO_CONFIRM' | 'DIRECT_TRIGGER'
        seed: 20261121,
        chartMode: 'fleet', // 'fleet' | 'bots'
        realityGapCohort: 'ALL_LIVE', // 'ALL_LIVE' | 'NEON_GATED_LIVE'
        data: null,
        loading: false,
    };

    let chartResizeObserver = null;

    function escapeHtml(str) {
        return String(str ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function fmtUsd(val, showSign) {
        const n = Number(val || 0);
        const sign = showSign ? (n > 0 ? '+' : n < 0 ? '-' : '') : n < 0 ? '-' : '';
        return `${sign}$${Math.abs(n).toLocaleString('en-US', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        })}`;
    }

    function fmtPct(val, showSign) {
        const n = Number(val || 0);
        const sign = showSign ? (n > 0 ? '+' : n < 0 ? '-' : '') : n < 0 ? '-' : '';
        return `${sign}${Math.abs(n).toFixed(2)}%`;
    }

    function fmtPrice(val) {
        const n = Number(val || 0);
        if (n >= 1000) return `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        if (n >= 1) return `$${n.toFixed(4)}`;
        return `$${n.toFixed(6)}`;
    }

    function setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function syncControlButtons() {
        const scenSel = document.getElementById('neon-win-scenario');
        if (scenSel) scenSel.value = winSimState.scenario;

        const eqSel = document.getElementById('neon-win-equity');
        if (eqSel) eqSel.value = String(winSimState.initialEquity);

        const csSel = document.getElementById('neon-win-candle-mode');
        if (csSel) csSel.value = winSimState.candlestickMode;

        [30, 90, 180].forEach((d) => {
            const btn = document.getElementById(`neon-win-horizon-${d}`);
            if (btn) btn.classList.toggle('active', winSimState.horizonDays === d);
        });

        const cmpBtn = document.getElementById('neon-win-compound-btn');
        if (cmpBtn) {
            cmpBtn.textContent = `Compounding: ${winSimState.dynamicCompounding ? 'ON' : 'OFF'}`;
            cmpBtn.className = winSimState.dynamicCompounding ? 'btn-primary btn-sm' : 'btn-secondary btn-sm';
        }

        const fleetBtn = document.getElementById('neon-win-chart-fleet');
        const botsBtn = document.getElementById('neon-win-chart-bots');
        if (fleetBtn) fleetBtn.classList.toggle('active', winSimState.chartMode === 'fleet');
        if (botsBtn) botsBtn.classList.toggle('active', winSimState.chartMode === 'bots');
    }

    function renderBotCard(prefix, bot) {
        if (!bot) return;
        const pnlEl = document.getElementById(`${prefix}-pnl`);
        if (pnlEl) {
            pnlEl.textContent = `${fmtUsd(bot.net_pnl_usd, true)} (${fmtPct(bot.return_pct, true)})`;
            pnlEl.className = `neon-win-bot-pnl ${bot.net_pnl_usd >= 0 ? 'text-pos' : 'text-neg'}`;
        }
        setText(`${prefix}-equity`, `${fmtUsd(bot.allocated_equity_usd, false)} → ${fmtUsd(bot.final_equity_usd, false)}`);
        setText(`${prefix}-wr`, `${bot.win_rate_pct}% (${bot.wins}W / ${bot.losses}L)`);
        setText(`${prefix}-pf`, `${bot.profit_factor}x · ${bot.avg_r_multiple >= 0 ? '+' : ''}${bot.avg_r_multiple}R avg`);
        setText(`${prefix}-dd`, `-${bot.max_drawdown_pct}% DD · ${bot.longest_win_streak}W / ${bot.longest_loss_streak ?? 0}L max`);
        setText(
            `${prefix}-best`,
            `Maker ${bot.maker_fill_ratio_pct ?? 0}% · Missed ${bot.missed_limit_fills ?? 0} limits · Friction -${fmtUsd(
                Number(bot.fees_paid_usd || 0) + Number(bot.slippage_paid_usd || 0) + Number(bot.funding_paid_usd || 0),
                false
            )}`
        );
    }

    function renderTradesTable(trades) {
        const tbody = document.getElementById('neon-win-trades-tbody');
        if (!tbody) return;
        if (!Array.isArray(trades) || !trades.length) {
            tbody.innerHTML = '<tr><td colspan="9" class="empty-cell">No simulated trades generated.</td></tr>';
            return;
        }
        const shortRegime = (r) => {
            if (r === 'TREND_EXPANSION') return 'TREND';
            if (r === 'CHOP_WHIPSAW') return 'CHOP';
            if (r === 'VOL_LIQUIDATION_SHOCK') return 'SHOCK';
            return 'BAL';
        };
        tbody.innerHTML = trades
            .map((t) => {
                const pnlCls = t.net_pnl_usd >= 0 ? 'text-pos' : 'text-neg';
                const botCls = t.bot_name === 'NEON-5' ? 'text-cyan' : 'text-pos';
                const sideCls = t.side === 'LONG' ? 'text-pos' : 'text-neg';
                const fricTotal = Number(t.fee_usd || 0) + Number(t.slippage_usd || 0) + Number(t.funding_usd || 0);
                const rail = `${t.entry_type || 'M'}→${t.exit_type || 'T'}`;
                return `<tr>
                    <td class="mono">${escapeHtml(t.timestamp_label)} · <span class="text-muted">${shortRegime(t.regime)}</span></td>
                    <td class="mono ${botCls}"><strong>${escapeHtml(t.bot_name)}</strong></td>
                    <td class="mono"><strong>${escapeHtml(t.symbol)}</strong></td>
                    <td class="mono ${sideCls}">${escapeHtml(t.side)}</td>
                    <td class="mono text-muted">${escapeHtml(rail)} · ${escapeHtml(String(t.exit_reason || '').replace(/_/g, ' '))}</td>
                    <td class="mono ${t.r_multiple >= 0 ? 'text-pos' : 'text-neg'}">${t.r_multiple >= 0 ? '+' : ''}${Number(t.r_multiple).toFixed(2)}R</td>
                    <td class="mono text-neg">-${fmtUsd(fricTotal, false)}</td>
                    <td class="mono ${pnlCls}"><strong>${fmtUsd(t.net_pnl_usd, true)}</strong></td>
                    <td class="mono">${fmtUsd(t.equity_after_usd, false)}</td>
                </tr>`;
            })
            .join('');
    }

    function renderD3WinChart(sim) {
        const host = document.getElementById('neon-win-chart-host');
        if (!host || !sim || !Array.isArray(sim.equity_series) || !sim.equity_series.length) return;
        if (typeof window.d3 === 'undefined') {
            host.innerHTML = '<div class="neon-ai-empty-state">D3 chart engine loading...</div>';
            return;
        }

        const rect = host.getBoundingClientRect();
        const width = Math.max(320, Math.floor(rect.width || 820));
        const height = 270;
        const margin = { top: 18, right: 20, bottom: 28, left: 66 };
        const plotW = Math.max(120, width - margin.left - margin.right);
        const plotH = Math.max(120, height - margin.top - margin.bottom);

        const d3 = window.d3;
        host.innerHTML = '';

        const series = sim.equity_series;
        const initHalf = Math.max(1, Number(sim.initial_equity_usd || 1000) / 2);
        const isBotsMode = winSimState.chartMode === 'bots';

        const svg = d3
            .select(host)
            .append('svg')
            .attr('width', width)
            .attr('height', height)
            .attr('viewBox', `0 0 ${width} ${height}`)
            .style('display', 'block');

        const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

        const x = d3
            .scaleLinear()
            .domain([0, Math.max(1, sim.horizon_days)])
            .range([0, plotW]);

        let yMin = 0;
        let yMax = 100;
        if (isBotsMode) {
            const vals = [];
            series.forEach((d) => {
                vals.push(((d.neon5_equity_usd - initHalf) / initHalf) * 100);
                vals.push(((d.neon6_equity_usd - initHalf) / initHalf) * 100);
                vals.push(d.combined_return_pct);
            });
            yMin = Math.min(0, d3.min(vals) ?? 0);
            yMax = Math.max(5, d3.max(vals) ?? 20);
        } else {
            const vals = [];
            series.forEach((d) => {
                vals.push(d.p10_equity_usd, d.p90_equity_usd, d.combined_equity_usd, sim.initial_equity_usd);
            });
            yMin = d3.min(vals) ?? sim.initial_equity_usd * 0.9;
            yMax = d3.max(vals) ?? sim.initial_equity_usd * 1.2;
        }
        const yPad = Math.max(isBotsMode ? 2 : 10, (yMax - yMin) * 0.1);
        const y = d3.scaleLinear().domain([yMin - yPad * 0.5, yMax + yPad]).range([plotH, 0]);

        // Horizontal grid lines
        const yTicks = y.ticks(5);
        g.selectAll('.win-grid')
            .data(yTicks)
            .enter()
            .append('line')
            .attr('x1', 0)
            .attr('x2', plotW)
            .attr('y1', (d) => y(d))
            .attr('y2', (d) => y(d))
            .attr('stroke', 'rgba(148, 163, 184, 0.10)')
            .attr('stroke-width', 1);

        // Baseline (initial equity or 0%)
        const baseVal = isBotsMode ? 0 : sim.initial_equity_usd;
        g.append('line')
            .attr('x1', 0)
            .attr('x2', plotW)
            .attr('y1', y(baseVal))
            .attr('y2', y(baseVal))
            .attr('stroke', 'rgba(148, 163, 184, 0.30)')
            .attr('stroke-dasharray', '4,4')
            .attr('stroke-width', 1);

        if (!isBotsMode) {
            // Monte Carlo P10–P90 shaded confidence envelope
            const mcArea = d3
                .area()
                .x((d) => x(d.day))
                .y0((d) => y(d.p10_equity_usd))
                .y1((d) => y(d.p90_equity_usd))
                .curve(d3.curveMonotoneX);

            g.append('path')
                .datum(series)
                .attr('fill', 'rgba(16, 185, 129, 0.11)')
                .attr('d', mcArea);

            // P50 Median dashed trajectory
            const p50Line = d3
                .line()
                .x((d) => x(d.day))
                .y((d) => y(d.p50_equity_usd))
                .curve(d3.curveMonotoneX);

            g.append('path')
                .datum(series)
                .attr('fill', 'none')
                .attr('stroke', 'rgba(148, 163, 184, 0.60)')
                .attr('stroke-width', 1.4)
                .attr('stroke-dasharray', '4,4')
                .attr('d', p50Line);

            // Combined NEON Fleet line
            const fleetLine = d3
                .line()
                .x((d) => x(d.day))
                .y((d) => y(d.combined_equity_usd))
                .curve(d3.curveMonotoneX);

            g.append('path')
                .datum(series)
                .attr('fill', 'none')
                .attr('stroke', '#10b981')
                .attr('stroke-width', 2.4)
                .attr('d', fleetLine);
        } else {
            // NEON-5 Trend Hunter (% Return)
            const n5Line = d3
                .line()
                .x((d) => x(d.day))
                .y((d) => y(((d.neon5_equity_usd - initHalf) / initHalf) * 100))
                .curve(d3.curveMonotoneX);

            // NEON-6 Maker Arbiter (% Return)
            const n6Line = d3
                .line()
                .x((d) => x(d.day))
                .y((d) => y(((d.neon6_equity_usd - initHalf) / initHalf) * 100))
                .curve(d3.curveMonotoneX);

            // Combined Return dashed reference
            const combLine = d3
                .line()
                .x((d) => x(d.day))
                .y((d) => y(d.combined_return_pct))
                .curve(d3.curveMonotoneX);

            g.append('path')
                .datum(series)
                .attr('fill', 'none')
                .attr('stroke', 'rgba(226, 232, 240, 0.45)')
                .attr('stroke-width', 1.3)
                .attr('stroke-dasharray', '3,3')
                .attr('d', combLine);

            g.append('path')
                .datum(series)
                .attr('fill', 'none')
                .attr('stroke', '#22d3ee')
                .attr('stroke-width', 2.2)
                .attr('d', n5Line);

            g.append('path')
                .datum(series)
                .attr('fill', 'none')
                .attr('stroke', '#2dd4bf')
                .attr('stroke-width', 2.2)
                .attr('d', n6Line);
        }

        // Axes
        const xAxis = d3
            .axisBottom(x)
            .ticks(Math.min(8, Math.max(4, Math.floor(plotW / 100))))
            .tickFormat((d) => `D${Math.round(d)}`);

        const yAxis = d3
            .axisLeft(y)
            .ticks(5)
            .tickFormat((d) =>
                isBotsMode
                    ? `${d >= 0 ? '+' : ''}${Number(d).toFixed(0)}%`
                    : `$${Number(d).toLocaleString('en-US', { maximumFractionDigits: 0 })}`
            );

        g.append('g')
            .attr('transform', `translate(0,${plotH})`)
            .call(xAxis)
            .call((sel) => sel.select('.domain').attr('stroke', 'rgba(148,163,184,0.18)'))
            .call((sel) => sel.selectAll('line').attr('stroke', 'rgba(148,163,184,0.18)'))
            .call((sel) =>
                sel
                    .selectAll('text')
                    .attr('fill', '#94a3b8')
                    .style('font-family', 'JetBrains Mono, monospace')
                    .style('font-size', '10px')
            );

        g.append('g')
            .call(yAxis)
            .call((sel) => sel.select('.domain').attr('stroke', 'rgba(148,163,184,0.18)'))
            .call((sel) => sel.selectAll('line').attr('stroke', 'rgba(148,163,184,0.18)'))
            .call((sel) =>
                sel
                    .selectAll('text')
                    .attr('fill', '#94a3b8')
                    .style('font-family', 'JetBrains Mono, monospace')
                    .style('font-size', '10px')
            );

        // Hover crosshair & tooltip
        const focusG = g.append('g').style('display', 'none');
        focusG
            .append('line')
            .attr('class', 'win-crosshair')
            .attr('y1', 0)
            .attr('y2', plotH)
            .attr('stroke', 'rgba(226, 232, 240, 0.35)')
            .attr('stroke-dasharray', '3,3');

        const dotMain = focusG
            .append('circle')
            .attr('r', 4.5)
            .attr('fill', isBotsMode ? '#22d3ee' : '#10b981')
            .attr('stroke', '#080c14')
            .attr('stroke-width', 1.6);

        const dotSub = focusG
            .append('circle')
            .attr('r', 4)
            .attr('fill', '#2dd4bf')
            .attr('stroke', '#080c14')
            .attr('stroke-width', 1.4)
            .style('display', isBotsMode ? null : 'none');

        const tooltip = document.getElementById('neon-win-tooltip');
        const bisectDay = d3.bisector((d) => d.day).left;

        g.append('rect')
            .attr('width', plotW)
            .attr('height', plotH)
            .attr('fill', 'transparent')
            .style('cursor', 'crosshair')
            .on('mouseenter', () => {
                focusG.style('display', null);
                if (tooltip) tooltip.style.display = 'block';
            })
            .on('mouseleave', () => {
                focusG.style('display', 'none');
                if (tooltip) tooltip.style.display = 'none';
            })
            .on('mousemove', function (event) {
                const [mx] = d3.pointer(event, this);
                const dayVal = x.invert(mx);
                let idx = bisectDay(series, dayVal, 1);
                idx = Math.min(series.length - 1, Math.max(0, idx));
                const prev = series[Math.max(0, idx - 1)];
                const curr = series[idx];
                const pt = Math.abs(dayVal - prev.day) < Math.abs(curr.day - dayVal) ? prev : curr;

                const px = x(pt.day);
                focusG.select('.win-crosshair').attr('x1', px).attr('x2', px);

                if (isBotsMode) {
                    const r5 = ((pt.neon5_equity_usd - initHalf) / initHalf) * 100;
                    const r6 = ((pt.neon6_equity_usd - initHalf) / initHalf) * 100;
                    dotMain.attr('cx', px).attr('cy', y(r5));
                    dotSub.attr('cx', px).attr('cy', y(r6));
                } else {
                    dotMain.attr('cx', px).attr('cy', y(pt.combined_equity_usd));
                }

                if (tooltip) {
                    const r5 = ((pt.neon5_equity_usd - initHalf) / initHalf) * 100;
                    const r6 = ((pt.neon6_equity_usd - initHalf) / initHalf) * 100;
                    tooltip.innerHTML = `
                        <div class="neon-win-tt-head">Day ${pt.day} · ${escapeHtml(pt.label)} · ${pt.cumulative_trades} trades</div>
                        <div class="neon-win-tt-row"><span>Combined Fleet</span><strong class="text-pos">${fmtUsd(pt.combined_equity_usd, false)} (${fmtPct(pt.combined_return_pct, true)})</strong></div>
                        <div class="neon-win-tt-row"><span>NEON-5 Trend</span><strong class="text-cyan">${fmtUsd(pt.neon5_equity_usd, false)} (${fmtPct(r5, true)})</strong></div>
                        <div class="neon-win-tt-row"><span>NEON-6 Maker</span><strong class="text-pos">${fmtUsd(pt.neon6_equity_usd, false)} (${fmtPct(r6, true)})</strong></div>
                        <div class="neon-win-tt-row"><span>MC P10 / P50 / P90</span><strong>${fmtUsd(pt.p10_equity_usd, false)} / ${fmtUsd(pt.p50_equity_usd, false)} / ${fmtUsd(pt.p90_equity_usd, false)}</strong></div>
                    `;
                    const leftPos = Math.min(width - 255, Math.max(12, margin.left + px + 14));
                    tooltip.style.left = `${leftPos}px`;
                    tooltip.style.top = '12px';
                }
            });
    }

    function renderWinSimulation(sim) {
        if (!sim) return;
        winSimState.data = sim;
        const fs = sim.fleet_summary || {};
        const mc = sim.monte_carlo || {};
        const anc = sim.empirical_anchor || {};

        setText(
            'neon-win-subtitle',
            `${sim.scenario_label} · ${sim.horizon_days}D exact-Decimal dual-bot replay (${mc.paths || 250} Monte Carlo paths · Seed #${sim.seed})`
        );

        const verdictEl = document.getElementById('neon-win-verdict');
        if (verdictEl) {
            const labelMap = {
                STRONG_WIN: 'STRONG WIN',
                STEADY_WIN: 'WINNING',
                FLAT_CONTESTED: 'CONTESTED',
                DRAWDOWN: 'DRAWDOWN',
            };
            const vTxt = labelMap[sim.verdict] || 'WINNING';
            verdictEl.textContent = `${vTxt} · ${fmtUsd(fs.net_pnl_usd, true)} (${fmtPct(fs.return_pct, true)})`;
            verdictEl.className = `neon-eq-stat-val ${fs.net_pnl_usd >= 0 ? 'text-pos' : 'text-neg'}`;
        }

        setText('neon-win-final-eq', `${fmtUsd(sim.initial_equity_usd, false)} → ${fmtUsd(fs.final_equity_usd, false)}`);
        setText('neon-win-prob', `${mc.win_probability_pct ?? 0}% P(Win) · ${fs.win_rate_pct ?? 0}% WR`);
        setText('neon-win-pf', `${fs.profit_factor ?? 0}x PF · ${fmtUsd(fs.expectancy_usd, true)}/trade`);
        setText('neon-win-dd', `-${fs.max_drawdown_pct ?? 0}% DD · Sharpe ${fs.sharpe_annualized ?? 0}`);

        const ef = sim.execution_friction || {};
        setText(
            'neon-win-fees',
            `Total Drag: -${fmtUsd(ef.total_friction_drag_usd, false)} (${ef.avg_blended_cost_bps_per_trade ?? 0} bps/trade)`
        );

        const rMix = ef.regime_day_share_pct || {};
        setText(
            'neon-win-regime-mix',
            `Markov Days: Trend ${rMix.trend ?? 0}% · Balanced ${rMix.balanced ?? 0}% · Chop ${rMix.chop ?? 0}% · Vol Shock ${rMix.vol_shock ?? 0}%`
        );
        const grossEl = document.getElementById('nwf-gross');
        if (grossEl) {
            grossEl.textContent = fmtUsd(ef.gross_pnl_before_friction_usd, true);
            grossEl.className = `neon-win-fric-val ${Number(ef.gross_pnl_before_friction_usd || 0) >= 0 ? 'text-pos' : 'text-neg'}`;
        }
        setText('nwf-fees', `-${fmtUsd(ef.exchange_fees_usd, false)} (${ef.maker_fill_ratio_pct ?? 0}% M)`);
        setText('nwf-slip', `-${fmtUsd(ef.slippage_cost_usd, false)}`);
        setText('nwf-fund', `-${fmtUsd(ef.funding_cost_usd, false)}`);
        setText('nwf-missed', `${ef.missed_limit_fills ?? 0} breakouts`);
        setText('nwf-bps', `${ef.avg_blended_cost_bps_per_trade ?? 0} bps · ${ef.bleed_guard_throttled_trades ?? 0} guarded`);

        setText(
            'neon-win-mc-summary',
            `${mc.paths || 250}-Path Realistic Bootstrap: P10 ${fmtUsd(mc.p10_final_equity_usd, false)} (${fmtPct(mc.p10_return_pct, true)}) · Median P50 ${fmtUsd(mc.p50_final_equity_usd, false)} (${fmtPct(mc.p50_return_pct, true)}) · P90 ${fmtUsd(mc.p90_final_equity_usd, false)} (${fmtPct(mc.p90_return_pct, true)}) · Med DD -${mc.median_max_dd_pct ?? 0}% (P90 -${mc.p90_max_dd_pct ?? 0}%) · Anchor: ${anc.historical_trades ?? 0} real Tier-1 trades (${anc.historical_win_rate_pct ?? 0}% WR)`
        );

        renderBotCard('neon-win-b5', sim.bots && sim.bots.neon5);
        renderBotCard('neon-win-b6', sim.bots && sim.bots.neon6);
        renderTradesTable(sim.recent_trades);
        renderD3WinChart(sim);
        if (sim.reality_gap) {
            renderRealityGapPanel(sim.reality_gap);
        }
        if (typeof window.syncCandlestickFromWinSim === 'function') {
            window.syncCandlestickFromWinSim(sim);
        }

        const legendEl = document.getElementById('neon-win-chart-legend');
        if (legendEl) {
            legendEl.innerHTML =
                winSimState.chartMode === 'fleet'
                    ? '<span class="text-pos">■ Combined NEON Fleet ($)</span> · <span class="text-muted">--- MC Median P50</span> · <span style="color:rgba(16,185,129,0.75);">▓ P10–P90 Envelope</span>'
                    : '<span class="text-cyan">■ BOT-05 NEON-5 Trend Hunter (%)</span> · <span class="text-pos">■ BOT-06 NEON-6 Maker Arbiter (%)</span> · <span class="text-muted">--- Fleet Avg (%)</span>';
        }
    }

    function fmtGapUnit(val, unit, signed) {
        const n = Number(val || 0);
        const sign = signed ? (n > 0 ? '+' : n < 0 ? '-' : '') : n < 0 ? '-' : '';
        const abs = Math.abs(n);
        if (unit === 'pct') return `${sign}${abs.toFixed(1)}${signed ? ' pp' : '%'}`;
        if (unit === 'x') return `${sign}${abs.toFixed(2)}x`;
        if (unit === 'bps') return `${sign}${abs.toFixed(2)} bps`;
        return `${sign}$${abs.toFixed(2)}`;
    }

    function buildCompareBarRow(label, valueText, pctWidth, toneClass) {
        const w = Math.max(2, Math.min(100, Number(pctWidth || 0)));
        return `<div class="neon-rg-bar-item">
            <div class="neon-rg-bar-meta">
                <span>${escapeHtml(label)}</span>
                <strong class="${toneClass}">${escapeHtml(valueText)}</strong>
            </div>
            <div class="neon-rg-bar-track">
                <div class="neon-rg-bar-fill ${toneClass}" style="width: ${w.toFixed(1)}%;"></div>
            </div>
        </div>`;
    }

    function renderRealityGapPanel(rg) {
        if (!rg || !rg.cohorts) return;
        const cohortKey = winSimState.realityGapCohort === 'NEON_GATED_LIVE' ? 'NEON_GATED_LIVE' : 'ALL_LIVE';
        const c = rg.cohorts[cohortKey] || rg.cohorts.ALL_LIVE;
        if (!c) return;

        const allBtn = document.getElementById('neon-rg-cohort-all');
        const gatedBtn = document.getElementById('neon-rg-cohort-gated');
        if (allBtn) {
            allBtn.classList.toggle('active', cohortKey === 'ALL_LIVE');
            if (rg.cohorts.ALL_LIVE) {
                allBtn.textContent = `All ${rg.cohorts.ALL_LIVE.observed_live.trades} Live Trades`;
            }
        }
        if (gatedBtn) {
            gatedBtn.classList.toggle('active', cohortKey === 'NEON_GATED_LIVE');
            if (rg.cohorts.NEON_GATED_LIVE) {
                gatedBtn.textContent = `NEON-Gated (${rg.cohorts.NEON_GATED_LIVE.observed_live.trades})`;
            }
        }

        const sim = c.simulated;
        const obs = c.observed_live;
        const v = c.variances;
        const sd = c.slippage_audit_detail || {};

        setText('neon-rg-subtitle', `${c.cohort_label} vs. ${rg.scenario_label} · Exact-Decimal Binance Execution Audit`);

        const calEl = document.getElementById('neon-rg-calibration');
        if (calEl) {
            const labelMap = {
                WELL_CALIBRATED: 'WELL CALIBRATED',
                MODERATE_DRIFT: 'MODERATE DRIFT',
                OPTIMISM_BIAS: 'OPTIMISM BIAS',
                CONSERVATIVE_BIAS: 'CONSERVATIVE',
            };
            calEl.textContent = `${labelMap[c.alignment_status] || c.alignment_status} · ${c.calibration_score_pct}/100`;
            const cls =
                c.alignment_status === 'WELL_CALIBRATED'
                    ? 'text-pos'
                    : c.alignment_status === 'OPTIMISM_BIAS'
                    ? 'text-neg'
                    : 'text-amber';
            calEl.className = `neon-eq-stat-val ${cls}`;
        }
        setText('neon-rg-scenario-tag', rg.scenario_label);

        const wrEl = document.getElementById('neon-rg-wr-gap');
        if (wrEl) {
            wrEl.textContent = `${fmtGapUnit(v.win_rate_gap_pp, 'pct', true)} WR`;
            wrEl.className = `neon-eq-stat-val ${
                Math.abs(v.win_rate_gap_pp) <= 5 ? 'text-pos' : v.win_rate_gap_pp > 8 ? 'text-neg' : 'text-amber'
            }`;
        }
        setText('neon-rg-wr-sub', `Sim ${sim.win_rate_pct}% vs Live ${obs.win_rate_pct}% (${obs.wins}W/${obs.losses}L)`);

        const pfEl = document.getElementById('neon-rg-pf-gap');
        if (pfEl) {
            pfEl.textContent = fmtGapUnit(v.profit_factor_gap, 'x', true);
            pfEl.className = `neon-eq-stat-val ${
                Math.abs(v.profit_factor_gap) <= 0.35 ? 'text-pos' : v.profit_factor_gap > 0.65 ? 'text-amber' : 'text-cyan'
            }`;
        }
        setText('neon-rg-pf-sub', `Sim ${sim.profit_factor}x vs Live ${obs.profit_factor}x`);

        const feeEl = document.getElementById('neon-rg-fee-gap');
        if (feeEl) {
            feeEl.textContent = `${fmtGapUnit(v.fee_drag_gap_pp, 'pct', true)} Drag`;
            feeEl.className = `neon-eq-stat-val ${v.fee_drag_gap_pp <= 0 ? 'text-pos' : 'text-neg'}`;
        }
        setText('neon-rg-fee-sub', `Sim ${sim.fee_bps} bps vs Live ${obs.fee_bps} bps (${fmtGapUnit(v.fee_bps_gap, 'bps', true)})`);

        const slipEl = document.getElementById('neon-rg-slip-gap');
        if (slipEl) {
            slipEl.textContent = fmtGapUnit(v.slippage_bps_gap, 'bps', true);
            slipEl.className = `neon-eq-stat-val ${
                sim.slippage_bps === 0 || v.slippage_bps_gap < -1.5
                    ? 'text-neg'
                    : Math.abs(v.slippage_bps_gap) <= 2.0
                    ? 'text-pos'
                    : 'text-amber'
            }`;
        }
        setText('neon-rg-slip-sub', `Sim ${sim.slippage_bps} bps vs Live ${obs.slippage_bps} bps`);

        // Render Fee Drag & Slippage side-by-side comparison bars
        setText(
            'neon-rg-fee-delta-label',
            `Fee Drag Δ ${fmtGapUnit(v.fee_drag_gap_pp, 'pct', true)} · Rate Δ ${fmtGapUnit(v.fee_bps_gap, 'bps', true)}`
        );
        const feeBarsEl = document.getElementById('neon-rg-fee-bars');
        if (feeBarsEl) {
            const maxDrag = Math.max(100, sim.fee_drag_pct, obs.fee_drag_pct);
            const maxBps = Math.max(12, sim.fee_bps, obs.fee_bps);
            feeBarsEl.innerHTML = [
                buildCompareBarRow('Simulated Fee Drag (% Gross)', `${sim.fee_drag_pct}%`, (sim.fee_drag_pct / maxDrag) * 100, 'bar-cyan'),
                buildCompareBarRow('Observed Live Fee Drag (% Gross)', `${obs.fee_drag_pct}%`, (obs.fee_drag_pct / maxDrag) * 100, 'bar-neg'),
                buildCompareBarRow('Simulated Effective Fee Rate', `${sim.fee_bps} bps (${sim.inferred_taker_share_pct}% taker)`, (sim.fee_bps / maxBps) * 100, 'bar-cyan'),
                buildCompareBarRow('Observed Live Binance Fee Rate', `${obs.fee_bps} bps (${obs.inferred_taker_share_pct}% taker)`, (obs.fee_bps / maxBps) * 100, 'bar-amber'),
            ].join('');
        }

        setText(
            'neon-rg-slip-delta-label',
            `Slippage Δ ${fmtGapUnit(v.slippage_bps_gap, 'bps', true)} · Total Friction Δ ${fmtGapUnit(v.total_friction_bps_gap, 'bps', true)}`
        );
        const slipBarsEl = document.getElementById('neon-rg-slip-bars');
        if (slipBarsEl) {
            const maxSlip = Math.max(10, sim.slippage_bps, obs.slippage_bps);
            const maxTot = Math.max(18, sim.total_friction_bps, obs.total_friction_bps);
            slipBarsEl.innerHTML = [
                buildCompareBarRow('Simulated Slippage (SL + Spread)', `${sim.slippage_bps} bps`, (sim.slippage_bps / maxSlip) * 100, sim.slippage_bps === 0 ? 'bar-neg' : 'bar-cyan'),
                buildCompareBarRow('Observed Live Slippage Proxy', `${obs.slippage_bps} bps`, (obs.slippage_bps / maxSlip) * 100, 'bar-amber'),
                buildCompareBarRow('Simulated All-In Friction (Fee+Slip+Fund)', `${sim.total_friction_bps} bps`, (sim.total_friction_bps / maxTot) * 100, 'bar-pos'),
                buildCompareBarRow('Observed Live All-In Friction', `${obs.total_friction_bps} bps`, (obs.total_friction_bps / maxTot) * 100, 'bar-neg'),
            ].join('');
        }

        setText('neon-rg-headline', c.headline || '');
        const startStr = c.date_start_utc ? String(c.date_start_utc).slice(0, 10) : '--';
        const endStr = c.date_end_utc ? String(c.date_end_utc).slice(0, 10) : '--';
        setText(
            'neon-rg-footnote',
            `Live Ledger (${startStr} → ${endStr}): ${obs.trades} trades · $${obs.total_notional_usd.toLocaleString('en-US', { minimumFractionDigits: 2 })} notional · $${obs.fees_usd.toFixed(2)} fees · ${sd.sl_fills_count ?? 0} SL fills (avg -${sd.avg_sl_loss_pct ?? 0}% vs 1.00% nominal = ${sd.sl_overshoot_bps ?? 0} bps overshoot + ${sd.spread_impact_bps ?? 0} bps spread + ${sd.price_residual_bps ?? 0} bps tick drift)`
        );

        const tbody = document.getElementById('neon-rg-tbody');
        if (tbody && Array.isArray(c.rows)) {
            const statusClass = (st) => {
                if (st === 'ALIGNED') return 'text-pos';
                if (st === 'FAVORABLE_EDGE') return 'text-cyan';
                if (st === 'UNDER_MODELED' || st === 'OPTIMISM_RISK') return 'text-neg';
                return 'text-amber';
            };
            const statusLabel = (st) => String(st || '').replace(/_/g, ' ');
            tbody.innerHTML = c.rows
                .map((r) => {
                    const cls = statusClass(r.status);
                    return `<tr>
                        <td><strong>${escapeHtml(r.metric_label)}</strong></td>
                        <td class="mono">${escapeHtml(fmtGapUnit(r.simulated_value, r.unit, false))}</td>
                        <td class="mono">${escapeHtml(fmtGapUnit(r.observed_value, r.unit, false))}</td>
                        <td class="mono ${cls}"><strong>${escapeHtml(fmtGapUnit(r.variance, r.unit, true))}</strong></td>
                        <td class="mono ${cls}">${escapeHtml(statusLabel(r.status))}</td>
                        <td class="text-secondary" style="font-size: 11.5px; white-space: normal;">${escapeHtml(r.note)}</td>
                    </tr>`;
                })
                .join('');
        }
    }

    function setNeonRealityGapCohort(cohortKey) {
        winSimState.realityGapCohort = cohortKey === 'NEON_GATED_LIVE' ? 'NEON_GATED_LIVE' : 'ALL_LIVE';
        if (winSimState.data && winSimState.data.reality_gap) {
            renderRealityGapPanel(winSimState.data.reality_gap);
        }
    }

    async function runNeonWinSimulationUI(options) {
        if (options && typeof options === 'object') {
            if (options.scenario) winSimState.scenario = options.scenario;
            if (options.initialEquity) winSimState.initialEquity = Number(options.initialEquity);
            if (options.horizonDays) winSimState.horizonDays = Number(options.horizonDays);
            if (typeof options.dynamicCompounding === 'boolean') {
                winSimState.dynamicCompounding = options.dynamicCompounding;
            }
            if (options.candlestickMode) {
                winSimState.candlestickMode = String(options.candlestickMode).toUpperCase();
            }
            if (options.reroll) {
                winSimState.seed = Math.floor(100000 + Math.random() * 899999);
            }
        }
        syncControlButtons();

        const runBtn = document.getElementById('neon-win-run-btn');
        if (runBtn) {
            runBtn.disabled = true;
            runBtn.textContent = 'Simulating...';
        }
        winSimState.loading = true;

        try {
            const resp = await axios.post(
                '/api/neon/win-simulation',
                {
                    scenario: winSimState.scenario,
                    initial_equity: winSimState.initialEquity,
                    horizon_days: winSimState.horizonDays,
                    dynamic_compounding: winSimState.dynamicCompounding,
                    candlestick_mode: winSimState.candlestickMode,
                    seed: winSimState.seed,
                },
                { timeout: 15000 }
            );
            if (resp.data && resp.data.success && resp.data.simulation) {
                renderWinSimulation(resp.data.simulation);
            } else {
                throw new Error((resp.data && resp.data.error) || 'Win simulation failed.');
            }
        } catch (err) {
            if (typeof window.showKronosToast === 'function') {
                window.showKronosToast('NEON Win Simulation failed to compute.', 'error');
            }
            console.warn('NEON Win Simulation error:', err);
        } finally {
            winSimState.loading = false;
            if (runBtn) {
                runBtn.disabled = false;
                runBtn.textContent = 'Run Win Sim';
            }
        }
    }

    function setNeonWinChartMode(mode) {
        winSimState.chartMode = mode === 'bots' ? 'bots' : 'fleet';
        syncControlButtons();
        if (winSimState.data) {
            renderWinSimulation(winSimState.data);
        }
    }

    function toggleNeonWinCompounding() {
        runNeonWinSimulationUI({ dynamicCompounding: !winSimState.dynamicCompounding });
    }

    function syncWinSimToSwarmDeck() {
        if (window.BotSwarmBridge && typeof window.BotSwarmBridge.setNeonSimMode === 'function') {
            window.BotSwarmBridge.setNeonSimMode('win', winSimState.data);
        }
        if (typeof window.setNeonDynamicTelemetryMode === 'function') {
            window.setNeonDynamicTelemetryMode('win');
        }
        if (typeof window.showKronosToast === 'function') {
            window.showKronosToast(
                'NEON Win Simulation synced to NEON-5 & NEON-6 on the Dashboard Swarm Deck.',
                'success'
            );
        }
    }

    function initResizeObserver() {
        const host = document.getElementById('neon-win-chart-host');
        if (!host || typeof ResizeObserver === 'undefined') return;
        if (chartResizeObserver) chartResizeObserver.disconnect();
        chartResizeObserver = new ResizeObserver(() => {
            if (winSimState.data && host.getBoundingClientRect().width > 80) {
                renderD3WinChart(winSimState.data);
            }
        });
        chartResizeObserver.observe(host);
    }

    document.addEventListener('DOMContentLoaded', () => {
        initResizeObserver();
        syncControlButtons();
    });

    window.runNeonWinSimulationUI = runNeonWinSimulationUI;
    window.setNeonWinChartMode = setNeonWinChartMode;
    window.toggleNeonWinCompounding = toggleNeonWinCompounding;
    window.syncWinSimToSwarmDeck = syncWinSimToSwarmDeck;
    window.setNeonRealityGapCohort = setNeonRealityGapCohort;
    window.getLatestNeonWinSimulation = function () {
        return winSimState.data;
    };
})();
