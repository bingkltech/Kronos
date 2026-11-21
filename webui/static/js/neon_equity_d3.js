(function () {
    'use strict';

    const state = {
        scope: 'CORE_BASKET',
        mirrorBull: false,
        metric: 'pnl', // 'pnl' | 'pct'
        initialEquity: 200,
        payload: null,
        loading: false,
        error: null,
        requestSeq: 0,
        zoomBehavior: null,
        zoomTarget: null,
        currentTransform: null,
        lastWidth: 0,
    };

    let resizeObserver = null;
    let resizeRaf = null;

    function fmtUsd(val, showSign) {
        const num = Number(val || 0);
        const sign = showSign ? (num > 0 ? '+' : num < 0 ? '-' : '') : num < 0 ? '-' : '';
        return `${sign}$${Math.abs(num).toFixed(2)}`;
    }

    function fmtPct(val, showSign) {
        const num = Number(val || 0);
        const sign = showSign ? (num > 0 ? '+' : num < 0 ? '-' : '') : num < 0 ? '-' : '';
        return `${sign}${Math.abs(num).toFixed(2)}%`;
    }

    function fmtUtcShort(ms) {
        const d = new Date(ms);
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        const mon = months[d.getUTCMonth()];
        const day = String(d.getUTCDate()).padStart(2, '0');
        const hh = String(d.getUTCHours()).padStart(2, '0');
        const mm = String(d.getUTCMinutes()).padStart(2, '0');
        return `${mon} ${day} ${hh}:${mm} UTC`;
    }

    function setElText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function setElClass(id, cls) {
        const el = document.getElementById(id);
        if (el) el.className = cls;
    }

    function updateControlStates() {
        const scopeSel = document.getElementById('neon-eq-scope');
        if (scopeSel && scopeSel.value !== state.scope) {
            scopeSel.value = state.scope;
        }

        const realBtn = document.getElementById('neon-eq-regime-real');
        const bullBtn = document.getElementById('neon-eq-regime-bull');
        if (realBtn && bullBtn) {
            realBtn.classList.toggle('active', !state.mirrorBull);
            bullBtn.classList.toggle('active', state.mirrorBull);
        }

        const pnlBtn = document.getElementById('neon-eq-metric-pnl');
        const pctBtn = document.getElementById('neon-eq-metric-pct');
        if (pnlBtn && pctBtn) {
            pnlBtn.classList.toggle('active', state.metric === 'pnl');
            pctBtn.classList.toggle('active', state.metric === 'pct');
        }
    }

    function updateResetButtonState(transform) {
        const btn = document.getElementById('neon-eq-reset-btn');
        if (!btn) return;
        const isZoomed = Boolean(transform && (transform.k > 1.005 || Math.abs(transform.x) > 1.5));
        btn.disabled = !isZoomed;
        btn.classList.toggle('is-zoomed', isZoomed);
    }

    function renderSummaryStrip(payload) {
        if (!payload || !payload.summary) return;
        const s = payload.summary;
        const isPct = state.metric === 'pct';

        const neonPrimary = isPct ? fmtPct(s.neon_final_return_pct, true) : fmtUsd(s.neon_final_pnl_usd, true);
        const neonSecondary = isPct ? fmtUsd(s.neon_final_pnl_usd, true) : fmtPct(s.neon_final_return_pct, true);
        setElText('neon-eq-sum-neon', `${neonPrimary} (${neonSecondary})`);
        setElClass('neon-eq-sum-neon', `neon-eq-stat-val ${s.neon_final_pnl_usd >= 0 ? 'text-pos' : 'text-neg'}`);

        const bhPrimary = isPct ? fmtPct(s.bh_final_return_pct, true) : fmtUsd(s.bh_final_pnl_usd, true);
        const bhSecondary = isPct ? fmtUsd(s.bh_final_pnl_usd, true) : fmtPct(s.bh_final_return_pct, true);
        setElText('neon-eq-sum-bh', `${bhPrimary} (${bhSecondary})`);
        setElClass('neon-eq-sum-bh', `neon-eq-stat-val ${s.bh_final_pnl_usd >= 0 ? 'text-secondary' : 'text-neg'}`);

        const alphaPrimary = isPct ? fmtPct(s.alpha_spread_pct, true) : fmtUsd(s.alpha_spread_usd, true);
        const alphaSecondary = isPct ? fmtUsd(s.alpha_spread_usd, true) : fmtPct(s.alpha_spread_pct, true);
        setElText('neon-eq-sum-alpha', `${alphaPrimary} (${alphaSecondary})`);
        setElClass('neon-eq-sum-alpha', `neon-eq-stat-val ${s.alpha_spread_usd >= 0 ? 'text-cyan' : 'text-neg'}`);

        const ddRedLabel = s.dd_reduction_pct > 0 ? `-${s.dd_reduction_pct}% vs B&H` : `vs -${s.bh_max_dd_pct}% B&H`;
        setElText('neon-eq-sum-dd', `-${s.neon_max_dd_pct}% (${ddRedLabel})`);
        setElClass('neon-eq-sum-dd', 'neon-eq-stat-val text-cyan');

        setElText('neon-eq-sum-trades', `${s.total_trades} (${s.wins}W/${s.losses}L · ${s.win_rate_pct}%)`);

        const sub = document.getElementById('neon-eq-subtitle');
        if (sub) {
            const regimeText = payload.regime_mode === 'MIRRORED_BULL_STRESS' ? 'Mirrored Bull Stress Test' : 'Real Market 1h OHLCV';
            sub.textContent = `${payload.scope_label} · ${regimeText} · ${payload.bars_plotted} aligned 1h bars · $${s.initial_equity_usd} start`;
        }
    }

    function setChartStatus(mode, message) {
        const stage = document.getElementById('neon-d3-equity-container');
        if (!stage) return;
        const overlay = document.getElementById('neon-d3-state-overlay');
        if (!overlay) return;

        if (mode === 'ready') {
            overlay.style.display = 'none';
            overlay.innerHTML = '';
            return;
        }

        overlay.style.display = 'flex';
        if (mode === 'loading') {
            overlay.innerHTML = `<div class="neon-d3-loading"><span class="neon-d3-spinner"></span><span>${message || 'Computing exact-decimal equity curve...'}</span></div>`;
        } else if (mode === 'error') {
            overlay.innerHTML = `<div class="neon-d3-empty text-neg"><span>${message || 'Unable to render equity curve.'}</span><button type="button" class="btn-secondary btn-sm" onclick="loadNeonEquityCurve()">Retry</button></div>`;
        } else {
            overlay.innerHTML = `<div class="neon-d3-empty">${message || 'No aligned candle history available for this scope.'}</div>`;
        }
    }

    function renderD3EquityChart(payload) {
        const container = document.getElementById('neon-d3-equity-container');
        if (!container) return;

        if (typeof window.d3 === 'undefined') {
            setChartStatus('error', 'D3.js library failed to load.');
            return;
        }

        const series = payload && Array.isArray(payload.series) ? payload.series : [];
        if (series.length < 2) {
            container.querySelectorAll('svg.neon-d3-svg').forEach((n) => n.remove());
            setChartStatus('empty', 'Insufficient aligned bars to plot Neon vs. Buy-and-Hold curve.');
            return;
        }

        const rect = container.getBoundingClientRect();
        const width = Math.floor(rect.width);
        if (width < 120) {
            // View is likely hidden right now; ResizeObserver will re-trigger when visible
            return;
        }
        state.lastWidth = width;
        setChartStatus('ready');

        const d3 = window.d3;
        const isPct = state.metric === 'pct';
        const markers = Array.isArray(payload.trade_markers) ? payload.trade_markers : [];

        // Group markers by timestamp for fast tooltip lookup
        const markersByTime = new Map();
        for (const m of markers) {
            const list = markersByTime.get(m.time_ms) || [];
            list.push(m);
            markersByTime.set(m.time_ms, list);
        }

        // Clean previous SVG
        d3.select(container).selectAll('svg.neon-d3-svg').remove();

        const margin = { top: 16, right: 20, bottom: 26, left: 66 };
        const mainH = 300;
        const gapH = 34;
        const ddH = 112;
        const totalH = margin.top + mainH + gapH + ddH + margin.bottom;
        const plotW = Math.max(200, width - margin.left - margin.right);

        const uid = `neq-${Date.now().toString(36)}`;
        const svg = d3
            .select(container)
            .append('svg')
            .attr('class', 'neon-d3-svg')
            .attr('width', width)
            .attr('height', totalH)
            .attr('viewBox', `0 0 ${width} ${totalH}`)
            .attr('role', 'img')
            .attr('aria-label', 'Neon Strategy vs Buy-and-Hold Equity Curve and Underwater Drawdown');

        const defs = svg.append('defs');

        // Plot bounds clips
        defs.append('clipPath')
            .attr('id', `${uid}-main-clip`)
            .append('rect')
            .attr('x', 0)
            .attr('y', -6)
            .attr('width', plotW)
            .attr('height', mainH + 12);

        defs.append('clipPath')
            .attr('id', `${uid}-dd-clip`)
            .append('rect')
            .attr('x', 0)
            .attr('y', 0)
            .attr('width', plotW)
            .attr('height', ddH + 2);

        // Dynamic split alpha clip paths (above B&H = green outperformance, below B&H = red underperformance)
        const clipAbovePath = defs.append('clipPath').attr('id', `${uid}-clip-above`).append('path');
        const clipBelowPath = defs.append('clipPath').attr('id', `${uid}-clip-below`).append('path');

        // Subtle underwater gradients
        const neonDdGrad = defs
            .append('linearGradient')
            .attr('id', `${uid}-neon-dd-grad`)
            .attr('x1', '0')
            .attr('y1', '0')
            .attr('x2', '0')
            .attr('y2', '1');
        neonDdGrad.append('stop').attr('offset', '0%').attr('stop-color', '#38bdf8').attr('stop-opacity', 0.14);
        neonDdGrad.append('stop').attr('offset', '100%').attr('stop-color', '#38bdf8').attr('stop-opacity', 0.36);

        const bhDdGrad = defs
            .append('linearGradient')
            .attr('id', `${uid}-bh-dd-grad`)
            .attr('x1', '0')
            .attr('y1', '0')
            .attr('x2', '0')
            .attr('y2', '1');
        bhDdGrad.append('stop').attr('offset', '0%').attr('stop-color', '#ef4444').attr('stop-opacity', 0.10);
        bhDdGrad.append('stop').attr('offset', '100%').attr('stop-color', '#ef4444').attr('stop-opacity', 0.28);

        // Accessors
        const getNeonVal = (d) => (isPct ? d.neon_cum_return_pct : d.neon_cum_pnl_usd);
        const getBhVal = (d) => (isPct ? d.bh_cum_return_pct : d.bh_cum_pnl_usd);
        const getMarkerVal = (m) => (isPct ? m.neon_cum_return_pct : m.neon_cum_pnl_usd);

        // Scales
        const timeExtent = d3.extent(series, (d) => d.time_ms);
        const xBase = d3.scaleUtc().domain([new Date(timeExtent[0]), new Date(timeExtent[1])]).range([0, plotW]);

        function computeYDomain(visibleSeries) {
            const vals = [0];
            for (const d of visibleSeries) {
                vals.push(getNeonVal(d), getBhVal(d));
            }
            let minV = d3.min(vals);
            let maxV = d3.max(vals);
            if (minV === maxV) {
                minV -= isPct ? 1 : 2;
                maxV += isPct ? 1 : 2;
            }
            const pad = (maxV - minV) * 0.12;
            return [minV - pad, maxV + pad];
        }

        const yMain = d3.scaleLinear().domain(computeYDomain(series)).range([mainH, 0]).nice();

        const minDdVal = Math.min(
            -1.0,
            d3.min(series, (d) => Math.min(d.neon_drawdown_pct, d.bh_drawdown_pct)) || -1.0
        );
        const yDd = d3.scaleLinear().domain([minDdVal * 1.15, 0]).range([ddH, 0]).nice();

        // Main panel group
        const mainG = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

        // Gridlines & Axes for Main Equity Chart
        const mainGridG = mainG.append('g').attr('class', 'neon-d3-grid');
        const mainYAxisG = mainG.append('g').attr('class', 'neon-d3-axis neon-d3-axis-y');
        const zeroLine = mainG.append('line').attr('class', 'neon-d3-zero-line').attr('x1', 0).attr('x2', plotW);

        // Main clipped content group
        const mainPlot = mainG.append('g').attr('clip-path', `url(#${uid}-main-clip)`);

        // Split alpha outperformance fills
        const alphaAbovePath = mainPlot
            .append('path')
            .attr('class', 'neon-d3-alpha-pos')
            .attr('clip-path', `url(#${uid}-clip-above)`);

        const alphaBelowPath = mainPlot
            .append('path')
            .attr('class', 'neon-d3-alpha-neg')
            .attr('clip-path', `url(#${uid}-clip-below)`);

        // Buy & Hold line (dashed slate)
        const bhLinePath = mainPlot.append('path').attr('class', 'neon-d3-line-bh');

        // Neon Strategy line (solid cyan)
        const neonLinePath = mainPlot.append('path').attr('class', 'neon-d3-line-neon');

        // Trade Marker Dots along Neon Curve
        const markerGroup = mainPlot.append('g').attr('class', 'neon-d3-markers');
        const markerDots = markerGroup
            .selectAll('circle')
            .data(markers)
            .enter()
            .append('circle')
            .attr('r', 3.6)
            .attr('class', (m) => (m.is_win ? 'neon-d3-dot-win' : 'neon-d3-dot-loss'));

        // Divider header between Equity Curve & Underwater Drawdown Subplot
        const ddTop = margin.top + mainH + gapH;
        const dividerG = svg.append('g').attr('transform', `translate(${margin.left},${margin.top + mainH + 10})`);
        dividerG
            .append('line')
            .attr('x1', 0)
            .attr('x2', plotW)
            .attr('y1', 0)
            .attr('y2', 0)
            .attr('stroke', 'rgba(148, 163, 184, 0.14)')
            .attr('stroke-width', 1);
        dividerG
            .append('text')
            .attr('x', 0)
            .attr('y', 16)
            .attr('class', 'neon-d3-subplot-label')
            .text('UNDERWATER DRAWDOWN (%) — NEON VS. BUY & HOLD');

        // Underwater Drawdown Subplot Group
        const ddG = svg.append('g').attr('transform', `translate(${margin.left},${ddTop})`);
        const ddGridG = ddG.append('g').attr('class', 'neon-d3-grid');
        const ddYAxisG = ddG.append('g').attr('class', 'neon-d3-axis neon-d3-axis-y');
        const ddXAxisG = ddG
            .append('g')
            .attr('class', 'neon-d3-axis neon-d3-axis-x')
            .attr('transform', `translate(0,${ddH})`);

        const ddPlot = ddG.append('g').attr('clip-path', `url(#${uid}-dd-clip)`);

        const bhDdAreaPath = ddPlot.append('path').attr('fill', `url(#${uid}-bh-dd-grad)`);
        const bhDdLinePath = ddPlot.append('path').attr('class', 'neon-d3-dd-line-bh');
        const neonDdAreaPath = ddPlot.append('path').attr('fill', `url(#${uid}-neon-dd-grad)`);
        const neonDdLinePath = ddPlot.append('path').attr('class', 'neon-d3-dd-line-neon');

        // Synchronized Crosshair Layer spanning both charts
        const crosshairG = svg
            .append('g')
            .attr('class', 'neon-d3-crosshair')
            .attr('transform', `translate(${margin.left},0)`)
            .style('display', 'none');

        const crosshairLine = crosshairG
            .append('line')
            .attr('class', 'neon-d3-crosshair-line')
            .attr('y1', margin.top)
            .attr('y2', ddTop + ddH);

        const focusNeon = crosshairG.append('circle').attr('r', 4.8).attr('class', 'neon-d3-focus-neon');
        const focusBh = crosshairG.append('circle').attr('r', 4.2).attr('class', 'neon-d3-focus-bh');
        const focusNeonDd = crosshairG.append('circle').attr('r', 3.8).attr('class', 'neon-d3-focus-neon');
        const focusBhDd = crosshairG.append('circle').attr('r', 3.5).attr('class', 'neon-d3-focus-dd-bh');

        // Generators
        function makeGenerators(xScale, yScale) {
            const diffArea = d3
                .area()
                .x((d) => xScale(new Date(d.time_ms)))
                .y0((d) => yScale(getBhVal(d)))
                .y1((d) => yScale(getNeonVal(d)))
                .curve(d3.curveMonotoneX);

            const aboveClipArea = d3
                .area()
                .x((d) => xScale(new Date(d.time_ms)))
                .y0(-10)
                .y1((d) => yScale(getBhVal(d)))
                .curve(d3.curveMonotoneX);

            const belowClipArea = d3
                .area()
                .x((d) => xScale(new Date(d.time_ms)))
                .y0((d) => yScale(getBhVal(d)))
                .y1(mainH + 10)
                .curve(d3.curveMonotoneX);

            const neonLine = d3
                .line()
                .x((d) => xScale(new Date(d.time_ms)))
                .y((d) => yScale(getNeonVal(d)))
                .curve(d3.curveMonotoneX);

            const bhLine = d3
                .line()
                .x((d) => xScale(new Date(d.time_ms)))
                .y((d) => yScale(getBhVal(d)))
                .curve(d3.curveMonotoneX);

            const neonDdArea = d3
                .area()
                .x((d) => xScale(new Date(d.time_ms)))
                .y0(yDd(0))
                .y1((d) => yDd(d.neon_drawdown_pct))
                .curve(d3.curveMonotoneX);

            const neonDdLine = d3
                .line()
                .x((d) => xScale(new Date(d.time_ms)))
                .y((d) => yDd(d.neon_drawdown_pct))
                .curve(d3.curveMonotoneX);

            const bhDdArea = d3
                .area()
                .x((d) => xScale(new Date(d.time_ms)))
                .y0(yDd(0))
                .y1((d) => yDd(d.bh_drawdown_pct))
                .curve(d3.curveMonotoneX);

            const bhDdLine = d3
                .line()
                .x((d) => xScale(new Date(d.time_ms)))
                .y((d) => yDd(d.bh_drawdown_pct))
                .curve(d3.curveMonotoneX);

            return {
                diffArea,
                aboveClipArea,
                belowClipArea,
                neonLine,
                bhLine,
                neonDdArea,
                neonDdLine,
                bhDdArea,
                bhDdLine,
            };
        }

        const formatYMainTick = (v) => {
            if (isPct) return `${v > 0 ? '+' : ''}${Number(v).toFixed(1)}%`;
            return `${v > 0 ? '+' : v < 0 ? '-' : ''}$${Math.abs(Number(v)).toFixed(Math.abs(v) < 10 ? 1 : 0)}`;
        };

        let activeXScale = xBase;

        function redraw(transform) {
            state.currentTransform = transform;
            updateResetButtonState(transform);

            activeXScale = transform.rescaleX(xBase);
            const [d0, d1] = activeXScale.domain();
            const t0 = d0.getTime();
            const t1 = d1.getTime();

            // Auto-fit main Y scale to visible range when zoomed so fine alpha movements stay legible
            const visible = series.filter((d) => d.time_ms >= t0 && d.time_ms <= t1);
            yMain.domain(computeYDomain(visible.length >= 2 ? visible : series)).nice();

            const g = makeGenerators(activeXScale, yMain);

            // Update main grid & Y axis
            const yMainTicks = yMain.ticks(6);
            mainGridG
                .call(d3.axisLeft(yMain).tickValues(yMainTicks).tickSize(-plotW).tickFormat(''))
                .call((sel) => sel.select('.domain').remove());

            mainYAxisG
                .call(d3.axisLeft(yMain).tickValues(yMainTicks).tickSize(0).tickPadding(10).tickFormat(formatYMainTick))
                .call((sel) => sel.select('.domain').remove());

            const zeroY = yMain(0);
            zeroLine
                .attr('y1', zeroY)
                .attr('y2', zeroY)
                .style('display', zeroY >= 0 && zeroY <= mainH ? null : 'none');

            // Update split alpha clip paths & fills
            clipAbovePath.datum(series).attr('d', g.aboveClipArea);
            clipBelowPath.datum(series).attr('d', g.belowClipArea);
            alphaAbovePath.datum(series).attr('d', g.diffArea);
            alphaBelowPath.datum(series).attr('d', g.diffArea);

            // Update lines
            bhLinePath.datum(series).attr('d', g.bhLine);
            neonLinePath.datum(series).attr('d', g.neonLine);

            // Update trade marker dots
            markerDots
                .attr('cx', (m) => activeXScale(new Date(m.time_ms)))
                .attr('cy', (m) => yMain(getMarkerVal(m)));

            // Update underwater drawdown subplot
            const ddTicks = yDd.ticks(3);
            ddGridG
                .call(d3.axisLeft(yDd).tickValues(ddTicks).tickSize(-plotW).tickFormat(''))
                .call((sel) => sel.select('.domain').remove());

            ddYAxisG
                .call(
                    d3
                        .axisLeft(yDd)
                        .tickValues(ddTicks)
                        .tickSize(0)
                        .tickPadding(10)
                        .tickFormat((v) => `${Number(v).toFixed(1)}%`)
                )
                .call((sel) => sel.select('.domain').remove());

            const xTickCount = Math.max(4, Math.min(8, Math.floor(plotW / 120)));
            ddXAxisG
                .call(d3.axisBottom(activeXScale).ticks(xTickCount).tickSize(4).tickPadding(8))
                .call((sel) => sel.select('.domain').attr('stroke', 'rgba(148, 163, 184, 0.16)'));

            bhDdAreaPath.datum(series).attr('d', g.bhDdArea);
            bhDdLinePath.datum(series).attr('d', g.bhDdLine);
            neonDdAreaPath.datum(series).attr('d', g.neonDdArea);
            neonDdLinePath.datum(series).attr('d', g.neonDdLine);
        }

        // Initial render at identity transform
        redraw(d3.zoomIdentity);

        // Tooltip & Bisector Interaction
        const tooltipEl = document.getElementById('neon-d3-tooltip');
        const bisectTime = d3.bisector((d) => d.time_ms).center;

        function hideCrosshair() {
            crosshairG.style('display', 'none');
            if (tooltipEl) tooltipEl.style.display = 'none';
        }

        function updateCrosshair(pointerX, pointerY) {
            const clampedX = Math.max(0, Math.min(plotW, pointerX));
            const hoveredDate = activeXScale.invert(clampedX);
            const idx = bisectTime(series, hoveredDate.getTime());
            const d = series[Math.max(0, Math.min(series.length - 1, idx))];
            if (!d) return;

            const cx = activeXScale(new Date(d.time_ms));
            if (cx < 0 || cx > plotW) {
                hideCrosshair();
                return;
            }

            crosshairG.style('display', null);
            crosshairLine.attr('x1', cx).attr('x2', cx);
            focusNeon.attr('cx', cx).attr('cy', margin.top + yMain(getNeonVal(d)));
            focusBh.attr('cx', cx).attr('cy', margin.top + yMain(getBhVal(d)));
            focusNeonDd.attr('cx', cx).attr('cy', ddTop + yDd(d.neon_drawdown_pct));
            focusBhDd.attr('cx', cx).attr('cy', ddTop + yDd(d.bh_drawdown_pct));

            if (!tooltipEl) return;

            const barTrades = markersByTime.get(d.time_ms) || [];
            const tradesHtml = barTrades.length
                ? `<div class="neon-d3-tt-trades">${barTrades
                      .map(
                          (m) =>
                              `<div class="neon-d3-tt-trade-row">
                                  <span class="${m.is_win ? 'text-pos' : 'text-neg'}">${m.is_win ? '●' : '●'} ${m.symbol} ${m.side}</span>
                                  <span class="mono ${m.is_win ? 'text-pos' : 'text-neg'}">${fmtUsd(m.net_pnl_usd, true)} · ${m.exit_reason}</span>
                              </div>`
                      )
                      .join('')}</div>`
                : '';

            const alphaCls = d.alpha_spread_usd >= 0 ? 'text-pos' : 'text-neg';
            const neonCls = d.neon_cum_pnl_usd >= 0 ? 'text-cyan' : 'text-neg';
            const bhCls = d.bh_cum_pnl_usd >= 0 ? 'text-secondary' : 'text-neg';

            tooltipEl.innerHTML = `
                <div class="neon-d3-tt-time">${fmtUtcShort(d.time_ms)}</div>
                <div class="neon-d3-tt-grid">
                    <span class="neon-d3-tt-lbl"><i class="tt-swatch tt-swatch-neon"></i>NEON Strategy</span>
                    <span class="mono ${neonCls}"><strong>${fmtUsd(d.neon_cum_pnl_usd, true)}</strong> (${fmtPct(d.neon_cum_return_pct, true)})</span>

                    <span class="neon-d3-tt-lbl"><i class="tt-swatch tt-swatch-bh"></i>Buy &amp; Hold</span>
                    <span class="mono ${bhCls}">${fmtUsd(d.bh_cum_pnl_usd, true)} (${fmtPct(d.bh_cum_return_pct, true)})</span>

                    <span class="neon-d3-tt-lbl">Alpha Spread</span>
                    <span class="mono ${alphaCls}"><strong>${fmtUsd(d.alpha_spread_usd, true)}</strong> (${fmtPct(d.alpha_spread_pct, true)})</span>

                    <span class="neon-d3-tt-lbl">Drawdown (Neon / B&amp;H)</span>
                    <span class="mono">${d.neon_drawdown_pct.toFixed(2)}% / <span class="text-neg">${d.bh_drawdown_pct.toFixed(2)}%</span></span>
                </div>
                ${tradesHtml}
            `;

            tooltipEl.style.display = 'block';
            const ttW = tooltipEl.offsetWidth || 250;
            const ttH = tooltipEl.offsetHeight || 130;
            const stageW = container.clientWidth || width;
            const stageH = totalH;

            let left = margin.left + cx + 16;
            if (left + ttW > stageW - 10) {
                left = margin.left + cx - ttW - 16;
            }
            left = Math.max(8, left);

            let top = Math.max(10, Math.min(stageH - ttH - 10, pointerY - ttH * 0.35));
            tooltipEl.style.left = `${left}px`;
            tooltipEl.style.top = `${top}px`;
        }

        // Interactive Overlay Group for pixel-accurate Zoom + Pan + Crosshair in [0, plotW]
        const overlayG = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);
        const overlayH = mainH + gapH + ddH;
        const overlay = overlayG
            .append('rect')
            .attr('class', 'neon-d3-overlay')
            .attr('x', 0)
            .attr('y', 0)
            .attr('width', plotW)
            .attr('height', overlayH)
            .attr('fill', 'transparent');

        const zoom = d3
            .zoom()
            .scaleExtent([1, 12])
            .translateExtent([
                [0, 0],
                [plotW, overlayH],
            ])
            .extent([
                [0, 0],
                [plotW, overlayH],
            ])
            .on('zoom', (event) => {
                redraw(event.transform);
                hideCrosshair();
            });

        overlay.call(zoom);
        overlay.on('dblclick.zoom', () => {
            overlay.transition().duration(240).call(zoom.transform, d3.zoomIdentity);
        });
        overlay.on('mousemove', (event) => {
            const [mx, my] = d3.pointer(event, overlay.node());
            updateCrosshair(mx, my + margin.top);
        });
        overlay.on('mouseleave', hideCrosshair);

        state.zoomBehavior = zoom;
        state.zoomTarget = overlay;
    }

    async function loadNeonEquityCurve(options) {
        if (options && typeof options === 'object') {
            if (typeof options.scope === 'string') state.scope = options.scope;
            if (typeof options.mirrorBull === 'boolean') state.mirrorBull = options.mirrorBull;
            if (typeof options.metric === 'string') state.metric = options.metric;
            if (typeof options.initialEquity === 'number' && options.initialEquity > 0) {
                state.initialEquity = options.initialEquity;
            }
        }

        updateControlStates();
        ensureResizeObserver();

        const seq = ++state.requestSeq;
        state.loading = true;
        state.error = null;
        if (!state.payload) {
            setChartStatus('loading', 'Simulating exact-decimal NEON vs. Buy-and-Hold curves...');
        }

        try {
            const resp = await axios.get('/api/neon/equity-curve', {
                params: {
                    scope: state.scope,
                    mirror_bull: state.mirrorBull ? 'true' : 'false',
                    initial_equity: state.initialEquity,
                },
                timeout: 12000,
            });
            if (seq !== state.requestSeq) return; // superseded by newer toggle

            const payload = resp.data && resp.data.equity_curve;
            if (!resp.data || !resp.data.success || !payload) {
                throw new Error('Invalid equity curve response');
            }

            state.payload = payload;
            state.loading = false;
            renderSummaryStrip(payload);
            renderD3EquityChart(payload);
        } catch (err) {
            if (seq !== state.requestSeq) return;
            state.loading = false;
            state.error = err;
            setChartStatus('error', 'Failed to load equity curve telemetry. Check connection and retry.');
            console.warn('NEON equity curve load failed:', err);
        }
    }

    function setNeonEquityScope(scope) {
        if (!scope || scope === state.scope) return;
        state.scope = scope;
        loadNeonEquityCurve();
    }

    function setNeonEquityRegime(mirrorBull) {
        const next = Boolean(mirrorBull);
        if (next === state.mirrorBull) return;
        state.mirrorBull = next;
        loadNeonEquityCurve();
    }

    function setNeonEquityMetric(metric) {
        const next = metric === 'pct' ? 'pct' : 'pnl';
        if (next === state.metric) return;
        state.metric = next;
        updateControlStates();
        if (state.payload) {
            renderSummaryStrip(state.payload);
            renderD3EquityChart(state.payload);
        }
    }

    function resetNeonEquityZoom() {
        if (state.zoomTarget && state.zoomBehavior && typeof window.d3 !== 'undefined') {
            state.zoomTarget.transition().duration(240).call(state.zoomBehavior.transform, window.d3.zoomIdentity);
        }
    }

    function ensureResizeObserver() {
        if (resizeObserver) return;
        const container = document.getElementById('neon-d3-equity-container');
        if (!container || typeof ResizeObserver === 'undefined') return;

        resizeObserver = new ResizeObserver((entries) => {
            const entry = entries[0];
            if (!entry) return;
            const w = Math.floor(entry.contentRect.width);
            if (w < 120 || Math.abs(w - state.lastWidth) < 4) return;
            if (resizeRaf) cancelAnimationFrame(resizeRaf);
            resizeRaf = requestAnimationFrame(() => {
                if (state.payload) {
                    renderD3EquityChart(state.payload);
                }
            });
        });
        resizeObserver.observe(container);
    }

    // Bind ResizeObserver once DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', ensureResizeObserver);
    } else {
        ensureResizeObserver();
    }

    window.loadNeonEquityCurve = loadNeonEquityCurve;
    window.setNeonEquityScope = setNeonEquityScope;
    window.setNeonEquityRegime = setNeonEquityRegime;
    window.setNeonEquityMetric = setNeonEquityMetric;
    window.resetNeonEquityZoom = resetNeonEquityZoom;
})();
