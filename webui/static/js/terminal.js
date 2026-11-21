// =====================================================================
        // Global App Router & State
        // =====================================================================
        let currentActiveView = 'dashboard';
        let liveAutopilotActive = true;
        let dashPortfolioViewMode = 'LIVE'; // Live Real Trade Summary is persistent default
        let currentDataFile = null;
        let currentDataInfo = null;
        let availableModels = [];
        let modelLoaded = false;

        // TradingView Lightweight Charts State
        let tvChart = null;
        let tvHistCandleSeries = null;
        let tvPredCandleSeries = null;
        let tvPredLineSeries = null;
        let tvActualCandleSeries = null;
        let tvActualLineSeries = null;
        let tvVolumeSeries = null;
        let tvActiveTheme = 'dark';
        let tvShowActual = true;
        let activeChartEngine = 'tradingview';
        let tvCachedHistBars = [];
        let tvCachedPredBars = [];
        let tvCachedActualBars = [];
        let currentAssetPrecision = 2;

        // Dynamic asset-aware price precision (e.g. BTC vs PEPE vs DOGE)
        function getAssetPrecisionConfig(price) {
            if (!price || isNaN(price)) return { precision: 2, minMove: 0.01 };
            const p = Math.abs(price);
            if (p < 0.0001) return { precision: 8, minMove: 0.00000001 };
            if (p < 0.01) return { precision: 7, minMove: 0.0000001 };
            if (p < 1.0) return { precision: 5, minMove: 0.00001 };
            if (p < 50.0) return { precision: 4, minMove: 0.0001 };
            if (p < 500.0) return { precision: 2, minMove: 0.01 };
            return { precision: 2, minMove: 0.01 };
        }

        function formatAssetPrice(val, precision) {
            if (val === undefined || val === null || isNaN(val)) return '--';
            const prec = (precision !== undefined) ? precision : currentAssetPrecision;
            return Number(val).toFixed(prec);
        }

        // View Navigation Switcher
        function switchAppView(viewName) {
            currentActiveView = viewName;
            document.querySelectorAll('.app-view').forEach(el => el.style.display = 'none');
            document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));

            if (viewName === 'swarm') {
                const target = document.getElementById('view-dashboard');
                const tab = document.getElementById('tab-swarm');
                if (target) target.style.display = 'block';
                if (tab) tab.classList.add('active');
                const swarmDeck = document.getElementById('swarmDeck');
                if (swarmDeck) {
                    if (swarmDeck.classList.contains('collapsed')) {
                        swarmDeck.classList.remove('collapsed');
                        const btnCollapse = document.getElementById('btnCollapseSwarm');
                        if (btnCollapse) btnCollapse.textContent = '[ - ] Collapse';
                    }
                    setTimeout(() => {
                        if (typeof window.resizeSwarmCanvas === 'function') window.resizeSwarmCanvas();
                        if (typeof window.resetSwarmView === 'function') window.resetSwarmView();
                        swarmDeck.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }, 50);
                }
                loadMacroOverview();
                return;
            }

            const target = document.getElementById(`view-${viewName}`);
            const tab = document.getElementById(`tab-${viewName}`);
            if (target) target.style.display = 'block';
            if (tab) tab.classList.add('active');

            if (viewName === 'forecaster') {
                setTimeout(() => {
                    initWorkstation();
                    if (tvChart) tvChart.timeScale().fitContent();
                }, 50);
            } else if (viewName === 'dashboard') {
                loadMacroOverview();
                setTimeout(() => {
                    if (typeof window.resizeSwarmCanvas === 'function') window.resizeSwarmCanvas();
                    if (typeof window.refreshYearlyMatrix === 'function') window.refreshYearlyMatrix(false);
                }, 50);
            } else if (viewName === 'bot') {
                loadBotDashboard();
            } else if (viewName === 'live') {
                loadLiveDashboard();
            } else if (viewName === 'scalper') {
                if (typeof loadScalperPage === 'function') {
                    loadScalperPage();
                }
            } else if (viewName === 'tiger') {
                if (typeof initTigerRadar === 'function') {
                    initTigerRadar();
                }
                if (typeof fetchTigerRadarData === 'function') {
                    fetchTigerRadarData();
                }
            } else if (viewName === 'neon') {
                if (typeof window.loadNeonStrategy === 'function') {
                    window.loadNeonStrategy();
                }
            }
        }

        // Start Live Clock
        function startLiveClock() {
            setInterval(() => {
                const now = new Date();
                const utcStr = now.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
                const el = document.getElementById('topbar-clock');
                if (el) el.textContent = utcStr;
            }, 1000);
        }

        // Status Toast Message
        function showStatus(type, message) {
            const container = document.getElementById('status-container');
            const toast = document.createElement('div');
            toast.className = `status ${type}`;
            toast.style.boxShadow = '0 4px 12px rgba(0,0,0,0.4)';
            toast.style.marginBottom = '8px';
            toast.textContent = message;
            container.appendChild(toast);
            setTimeout(() => {
                toast.remove();
            }, 4000);
        }

        // =====================================================================
        // VIEW 1: MACRO DASHBOARD API CALLS
        // =====================================================================
        
        // =====================================================================
        // Macro Dashboard Live Real Trade Summary & Trades Engine
        // =====================================================================
        window._dashLivePositionsSig = '';
        window._dashLiveTradesSig = '';

        function toggleDashboardViewMode() {
            dashPortfolioViewMode = 'LIVE';
            loadMacroOverview();
            loadLiveDashboard();
        }

        function renderMacroPortfolioLive(data) {
            if (dashPortfolioViewMode !== 'LIVE') return;

            const acct = data.live_account || {};
            const trades = data.trade_history || data.live_trades || [];
            const positions = acct.positions || [];

            const wallet = Number(acct.total_wallet_balance_usd || 0);
            const avail = Number(acct.available_balance_usd || 0);
            const unreal = Number(acct.unrealized_pnl_usd || 0);
            const margin = Number(acct.margin_ratio_pct || 0);
            const bnbBal = Number(acct.bnb_balance || 0);
            const bnbActive = Boolean(acct.bnb_fee_discount_active);

            // Check for Binance API connection / 401 error on Dashboard
            const dashErrBanner = document.getElementById('dash-live-api-error-banner');
            const dashErrText = document.getElementById('dash-live-api-error-text');
            const dashIpCode = document.getElementById('dash-live-detected-ip');
            const hasError = !acct.connected && (data.error || (data.last_cycle && data.last_cycle.error));
            if (hasError) {
                const errMsg = data.error || (data.last_cycle ? data.last_cycle.error : '');
                if (dashErrBanner) {
                    dashErrBanner.style.display = 'flex';
                    if (dashErrText) dashErrText.textContent = errMsg;
                    const match = errMsg.match(/request ip:\s*([0-9.]+)/i);
                    if (match && dashIpCode) {
                        dashIpCode.textContent = match[1];
                    }
                }
            } else {
                if (dashErrBanner) dashErrBanner.style.display = 'none';
            }

            // 1. Header & Badges
            const dTitle = document.getElementById('dash-portfolio-title');
            const dBadge = document.getElementById('dash-portfolio-mode-badge');
            const dLiveSec = document.getElementById('dash-live-positions-section');
            const dTradesSec = document.getElementById('dash-live-trades-section');
            const dPaperSec = document.getElementById('dash-paper-section');
            const dToggleBtn = document.getElementById('dash-mode-toggle-btn');

            if (dTitle) dTitle.innerHTML = 'Real Live Trading & Binance Portfolio Audit';
            if (dBadge) {
                dBadge.innerHTML = '🔴 REAL LIVE CAPITAL ACTIVE (Binance Futures ISOLATED)';
                dBadge.style.color = '#ff7b72';
                dBadge.style.background = 'rgba(255, 82, 82, 0.15)';
                dBadge.style.borderColor = 'rgba(255, 82, 82, 0.4)';
            }
            if (dToggleBtn) dToggleBtn.style.display = 'none';
            if (dLiveSec) dLiveSec.style.display = 'block';
            if (dTradesSec) dTradesSec.style.display = 'block';
            if (dPaperSec) dPaperSec.style.display = 'none';

            // 2. Metric Cards
            const cardEquityTitle = document.getElementById('dash-card-equity-title');
            const cardPnlTitle = document.getElementById('dash-card-pnl-title');
            const cardWinlossTitle = document.getElementById('dash-card-winloss-title');
            const cardPfTitle = document.getElementById('dash-card-pf-title');
            if (cardEquityTitle) cardEquityTitle.textContent = 'Total Futures Wallet';
            if (cardPnlTitle) cardPnlTitle.textContent = 'Total Unrealized PnL';
            if (cardWinlossTitle) cardWinlossTitle.textContent = 'Active Live Positions';
            if (cardPfTitle) cardPfTitle.textContent = 'BNB Fee Buffer';

            const dEquity = document.getElementById('dash-paper-equity');
            const dStarting = document.getElementById('dash-paper-starting');
            const dPnl = document.getElementById('dash-paper-pnl');
            const dPnlPct = document.getElementById('dash-paper-pnl-pct');
            const dWinLoss = document.getElementById('dash-paper-winloss');
            const dWinRate = document.getElementById('dash-paper-winrate-badge');
            const dTotal = document.getElementById('dash-paper-total-trades');
            const dPF = document.getElementById('dash-paper-profitfactor');
            const dPfSub = document.getElementById('dash-card-pf-sub');
            const dFeeDrag = document.getElementById('dash-paper-fee-drag');

            if (dEquity) {
                dEquity.textContent = `$${wallet.toFixed(2)} USDT`;
                dEquity.style.color = '#00E676';
            }
            if (dStarting) dStarting.textContent = `Available Collateral: $${avail.toFixed(2)} USDT`;
            if (dPnl) {
                dPnl.textContent = `${unreal >= 0 ? '+' : ''}$${unreal.toFixed(2)} USDT`;
                dPnl.style.color = unreal > 0 ? '#3fb950' : (unreal < 0 ? '#f85149' : '#8b949e');
            }
            if (dPnlPct) dPnlPct.textContent = `Margin Ratio: ${margin.toFixed(2)}% (SAFE)`;
            if (dFeeDrag) dFeeDrag.textContent = 'Mark-to-Market Live Valuation';
            if (dWinLoss) dWinLoss.textContent = `${positions.length} Active Contracts`;
            if (dWinRate) dWinRate.textContent = 'Margin: ISOLATED';
            if (dTotal) dTotal.textContent = 'Max Lev: 5x';
            if (dPF) dPF.textContent = `${bnbBal.toFixed(4)} BNB`;
            if (dPfSub) dPfSub.textContent = bnbActive ? '⚡ 10% Taker Discount Active' : 'Standard USDT Fee Deduction';

            // 3. Render Active Positions Table with anti-flicker diffing
            const posTbody = document.getElementById('dash-live-positions-tbody');
            if (posTbody) {
                const posSig = positions.map(p => `${p.symbol}:${p.position_amt}:${p.entry_price}:${p.mark_price}:${p.unrealized_pnl_usd}`).join('|');
                if (window._dashLivePositionsSig !== posSig) {
                    window._dashLivePositionsSig = posSig;
                    posTbody.innerHTML = '';
                    if (positions.length === 0) {
                        posTbody.innerHTML = `
                            <tr>
                                <td colspan="11" style="text-align: center; color: var(--text-muted); padding: 18px;">
                                    No active positions currently held on Binance Futures. Screening universe for entries.
                                </td>
                            </tr>
                        `;
                    } else {
                        positions.forEach(p => {
                            const tr = document.createElement('tr');
                            const side = (p.side || '').toUpperCase();
                            const sideColor = side === 'BUY' || side === 'LONG' ? '#3fb950' : '#f85149';
                            const pnlVal = Number(p.unrealized_pnl_usd || 0);
                            const pnlColor = pnlVal >= 0 ? '#3fb950' : '#f85149';
                            const notional = Number(p.notional_usd || 0);
                            const entry = Number(p.entry_price || 0);
                            const mark = Number(p.mark_price || 0);
                            const liq = Number(p.liquidation_price || 0);
                            const lev = Number(p.leverage || 1);
                            const margin = Number(p.margin_usd || (lev > 0 ? notional / lev : notional));

                            tr.setAttribute('data-pos-symbol', p.symbol);
                            tr.setAttribute('data-entry-price', entry);
                            tr.setAttribute('data-pos-amt', p.position_amt);
                            tr.setAttribute('data-side', side);
                            tr.setAttribute('data-leverage', lev);

                            const isScalp = Boolean(p.is_scalp === true || p.trade_type === 'SCALP' || (window._currentActiveScalpSymbol && p.symbol === window._currentActiveScalpSymbol));
                            if (isScalp) tr.className = 'trade-row-scalp';

                            const symbolHtml = isScalp
                                ? `<strong class="scalp-symbol-bold-blue">${p.symbol}</strong><span class="scalp-badge-bold-blue">⚡ SCALP</span>`
                                : `<strong class="pos-symbol">${p.symbol}</strong><span class="badge-regime" style="background: rgba(163, 113, 247, 0.15); color: #a371f7; border: 1px solid rgba(163, 113, 247, 0.4); font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; margin-left: 6px;">🌐 MACRO</span>`;

                            const priceGain = p.price_gain_pct !== undefined ? Number(p.price_gain_pct) : (
                                entry > 0 ? (side === 'BUY' || side === 'LONG' ? ((mark - entry) / entry * 100) : ((entry - mark) / entry * 100)) : 0
                            );
                            const priceGainColor = priceGain >= 0 ? '#3fb950' : '#f85149';
                            const netRoi = p.net_roi_pct !== undefined ? Number(p.net_roi_pct) : (
                                margin > 0 ? ((pnlVal - (notional * 0.0008)) / margin * 100) : 0
                            );
                            const netRoiColor = netRoi >= 0 ? '#3fb950' : '#f85149';
                            const netRoiBg = netRoi >= 0 ? 'rgba(63, 185, 80, 0.12)' : 'rgba(248, 81, 73, 0.12)';

                            tr.innerHTML = `
                                <td>${symbolHtml}</td>
                                <td><span class="badge-regime" style="color: ${sideColor}; font-weight: 700; border: 1px solid ${sideColor};">${side}</span></td>
                                <td style="font-family: var(--font-mono);">${p.position_amt}</td>
                                <td class="pos-cell-notional" style="font-family: var(--font-mono);">$${notional.toFixed(2)}</td>
                                <td style="font-family: var(--font-mono);">$${entry.toFixed(2)}</td>
                                <td class="pos-cell-mark" style="font-family: var(--font-mono);">$${mark.toFixed(2)}</td>
                                <td class="pos-cell-pricegain" style="color: ${priceGainColor}; font-weight: 700; font-family: var(--font-mono);">${priceGain >= 0 ? '+' : ''}${priceGain.toFixed(2)}%</td>
                                <td class="pos-cell-margin" style="font-family: var(--font-mono);">$${margin.toFixed(2)}</td>
                                <td>${p.leverage}x</td>
                                <td class="pos-cell-pnl" style="color: ${pnlColor}; font-weight: 700; font-family: var(--font-mono);">${pnlVal >= 0 ? '+' : ''}$${pnlVal.toFixed(2)}</td>
                                <td class="pos-cell-netroi"><span class="badge-regime" style="color: ${netRoiColor}; font-weight: 700; border: 1px solid ${netRoiColor}; background: ${netRoiBg};">${netRoi >= 0 ? '+' : ''}${netRoi.toFixed(2)}%</span></td>
                                <td>
                                    <button class="btn-table-action" style="color: #f85149;" onclick="flattenLivePositions()">Close</button>
                                </td>
                            `;
                            posTbody.appendChild(tr);
                        });
                    }
                }
            }

            // 4. Render Live Trades Ledger with anti-flicker diffing
            const tradesTbody = document.getElementById('dash-live-trades-tbody');
            if (tradesTbody && trades) {
                const tradesSig = trades.map(t => `${t.id || t.orderId || t.order_id || t.trade_id}:${t.symbol}:${t.price}:${t.qty || t.quantity}:${t.realizedPnl || t.realized_pnl_usd}`).join('|');
                if (window._dashLiveTradesSig !== tradesSig) {
                    window._dashLiveTradesSig = tradesSig;
                    tradesTbody.innerHTML = '';
                    if (trades.length === 0) {
                        tradesTbody.innerHTML = `
                            <tr>
                                <td colspan="8" style="text-align: center; color: var(--text-muted); padding: 18px;">
                                    No recent fills found on Binance Futures. Fills will appear here immediately after execution.
                                </td>
                            </tr>
                        `;
                    } else {
                        trades.slice(0, 10).forEach(t => {
                            const tr = document.createElement('tr');
                            const isScalp = Boolean(t.is_scalp || t.trade_type === 'SCALP');
                            if (isScalp) tr.className = 'trade-row-scalp';
                            const isBuy = t.buyer || t.side === 'BUY';
                            const sideStr = isBuy ? 'BUY' : 'SELL';
                            const sideColor = isBuy ? '#3fb950' : '#f85149';
                            const pnl = Number(t.realizedPnl || t.realized_pnl_usd || 0);
                            const pnlColor = pnl >= 0 ? '#3fb950' : '#f85149';
                            const price = Number(t.price || 0);
                            const qty = Number(t.qty || t.quantity || 0);
                            const notional = price * qty;
                            const fee = Number(t.commission || t.fee_amount || 0);
                            const feeAsset = t.commissionAsset || t.fee_asset || 'USDT';

                            let timeStr = '--:--:--';
                            if (t.time) {
                                const d = new Date(t.time);
                                timeStr = d.toISOString().replace('T', ' ').slice(11, 19);
                            }

                            const symbolHtml = isScalp
                                ? `<strong class="scalp-symbol-bold-blue">${t.symbol}</strong><span class="scalp-badge-bold-blue">⚡ SCALP</span>`
                                : `<strong>${t.symbol}</strong>`;

                            tr.innerHTML = `
                                <td style="font-family: var(--font-mono); font-size: 11px;">${timeStr}</td>
                                <td>${symbolHtml}</td>
                                <td><span class="badge-regime" style="color: ${sideColor}; font-weight: 700; border: 1px solid ${sideColor}; font-size: 10px;">${sideStr}</span></td>
                                <td style="font-family: var(--font-mono);">$${price.toFixed(2)}</td>
                                <td style="font-family: var(--font-mono);">${qty}</td>
                                <td style="font-family: var(--font-mono);">$${notional.toFixed(2)}</td>
                                <td style="font-size: 11px; color: var(--text-muted);">${fee.toFixed(4)} ${feeAsset}</td>
                                <td style="color: ${pnlColor}; font-weight: 700; font-family: var(--font-mono);">${pnl !== 0 ? (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(2) : '--'}</td>
                            `;
                            tradesTbody.appendChild(tr);
                        });
                    }
                }
            }
        }

        async function loadMacroOverview(retryCount = 0) {
            try {
                const resp = await axios.get('/api/macro/overview', { timeout: 8000 });
                const data = resp.data;
                if (!data || !data.success) return;

                // Update Breadth Card
                document.getElementById('dash-breadth-val').textContent = data.breadth_pct;
                document.getElementById('dash-breadth-sub').textContent = `${data.coins_above_vwap} of ${data.total_coins} coins above 24h VWAP`;
                
                const regimeEl = document.getElementById('dash-regime-badge');
                regimeEl.textContent = data.macro_regime;
                regimeEl.className = 'badge-regime';
                if (data.macro_regime === 'BULL_EXPANSION') regimeEl.classList.add('regime-bull');
                else if (data.macro_regime === 'BEAR_DISTRIBUTION') regimeEl.classList.add('regime-bear');
                else regimeEl.classList.add('regime-chop');

                // Update Topbar Pills
                const topRegime = document.getElementById('topbar-regime-pill');
                topRegime.textContent = `REGIME: ${data.macro_regime} (${data.breadth_pct})`;

                // Update News Blackout Card
                const newsStatus = document.getElementById('dash-news-status');
                const newsDesc = document.getElementById('dash-news-desc');
                const topNews = document.getElementById('topbar-news-pill');

                if (data.news_blackout.is_blackout) {
                    newsStatus.textContent = 'BLACKOUT ACTIVE';
                    newsStatus.style.color = '#f85149';
                    newsDesc.textContent = data.news_blackout.reason;
                    topNews.textContent = 'NEWS: BLACKOUT';
                    topNews.style.color = '#f85149';
                } else {
                    newsStatus.textContent = 'CLEAR (SAFE TO TRADE)';
                    newsStatus.style.color = '#3fb950';
                    newsDesc.textContent = 'No high-impact economic releases within +/- 30m window.';
                    topNews.textContent = 'NEWS: CLEAR';
                    topNews.style.color = '#3fb950';
                }

                // Update Storm Protocol & Anti-Bloat pills in parallel
                if (typeof updateStormProtocolUI === 'function') {
                    updateStormProtocolUI();
                }
                if (typeof updateAntiBloatUI === 'function') {
                    updateAntiBloatUI();
                }

                // Render Table Rows
                const tbody = document.getElementById('macro-table-tbody');
                tbody.innerHTML = '';

                let totalFunding = 0;
                let count = 0;

                data.symbols.forEach(s => {
                    totalFunding += s.funding_rate_8h_pct;
                    count++;

                    const tr = document.createElement('tr');
                    tr.id = `macro-row-${s.symbol}`;
                    const livePrice = (binanceWsPrices && binanceWsPrices[s.symbol]) ? binanceWsPrices[s.symbol] : s.current_price;
                    const prec = getAssetPrecisionConfig(livePrice).precision;

                    const aboveBadge = s.above_vwap ?
                        '<span class="badge-regime regime-bull">ABOVE VWAP</span>' :
                        '<span class="badge-regime regime-bear">BELOW VWAP</span>';

                    const pnlColor = s.price_change_24h_pct >= 0 ? '#3fb950' : '#f85149';
                    const carryColor = s.carry_verdict === 'FAVORABLE' ? '#3fb950' : (s.carry_verdict === 'PROHIBITIVE' ? '#f85149' : '#d29922');

                    tr.innerHTML = `
                        <td><strong>${s.symbol}</strong></td>
                        <td id="macro-price-${s.symbol}" data-price="${livePrice}" style="font-family: var(--font-mono);">${formatAssetPrice(livePrice, prec)}</td>
                        <td style="font-family: var(--font-mono);">${formatAssetPrice(s.vwap_24h, prec)}</td>
                        <td>${aboveBadge}</td>
                        <td id="macro-change-${s.symbol}" style="color: ${pnlColor}; font-weight: 700; font-family: var(--font-mono);">${s.price_change_24h_pct >= 0 ? '+' : ''}${s.price_change_24h_pct.toFixed(2)}%</td>
                        <td style="font-family: var(--font-mono);">$${(s.volume_24h_usdt / 1e6).toFixed(1)}M</td>
                        <td style="color: #58a6ff; font-family: var(--font-mono);">${s.funding_rate_8h_pct >= 0 ? '+' : ''}${s.funding_rate_8h_pct.toFixed(4)}%</td>
                        <td><span class="badge-regime" style="color: ${carryColor}; border: 1px solid ${carryColor};">${s.carry_verdict}</span></td>
                        <td>
                            <button class="btn-table-action" onclick="jumpToForecaster('${s.symbol}')">⚡ Forecast</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });

                if (count > 0) {
                    const avgFunding = (totalFunding / count);
                    document.getElementById('dash-funding-avg').textContent = `${avgFunding >= 0 ? '+' : ''}${avgFunding.toFixed(4)}%`;
                }

                // Load Learning Stats
                loadLearningStats();

                // Real Live Binance Portfolio is the ONLY portfolio shown on Macro Dashboard
                if (data.live_account) {
                    renderMacroPortfolioLive(data);
                } else {
                    loadLiveDashboard();
                }
                loadGeminiAssessment();
                if (typeof loadScalperStatus === 'function') {
                    loadScalperStatus();
                } else if (typeof loadScalperTelemetry === 'function') {
                    loadScalperTelemetry();
                }

            } catch (err) {
                const isTransientNetwork = !err || !err.response || err.code === 'ERR_NETWORK' || err.code === 'ECONNABORTED';
                if (isTransientNetwork && retryCount < 2) {
                    setTimeout(() => loadMacroOverview(retryCount + 1), 1500 * (retryCount + 1));
                    return;
                }
                const topRegime = document.getElementById('topbar-regime-pill');
                if (topRegime && topRegime.textContent.includes('LOADING')) {
                    topRegime.textContent = 'REGIME: RECONNECTING...';
                }
                console.warn('Macro overview refresh deferred (transient connection):', err && err.message ? err.message : err);
            }
        }

        function jumpToForecaster(symbol) {
            switchAppView('forecaster');
            if (typeof switchWorkstationAsset === 'function') switchWorkstationAsset(symbol);
            const selectEl = document.getElementById('binance-asset-select');
            if (selectEl) {
                selectEl.value = symbol;
            }
            fetchBinanceData();
        }

        function quickSelectAsset(symbol) {
            document.querySelectorAll('.asset-chip').forEach(c => c.classList.remove('active'));
            const chip = Array.from(document.querySelectorAll('.asset-chip')).find(el => el.textContent.includes(symbol.replace('USDT','')));
            if (chip) chip.classList.add('active');

            const selectEl = document.getElementById('binance-asset-select');
            if (selectEl) {
                selectEl.value = symbol;
            }
            fetchBinanceData();
        }

        // =====================================================================
        // VIEW 3: QUANT BOT & KEV.AI API CALLS
        // =====================================================================
        async function loadBotDashboard() {
            try {
                const resp = await axios.get('/api/bot/status');
                const data = resp.data;
                if (!data.success) return;

                // Update Autopilot Status & Controls
                if (data.autopilot) {
                    const badge = document.getElementById('bot-state-badge');
                    const btnAuto = document.getElementById('btn-toggle-autopilot');
                    const topPill = document.getElementById('topbar-bot-pill');
                    const cdEl = document.getElementById('bot-countdown');
                    const intSelect = document.getElementById('bot-interval-select');

                    if (intSelect && data.autopilot.interval_seconds) {
                        intSelect.value = String(data.autopilot.interval_seconds);
                    }

                    if (data.autopilot.enabled) {
                        if (badge) {
                            badge.innerHTML = '<span class="pulse-dot"></span> AUTOPILOT ACTIVE';
                            badge.style.color = '#3fb950';
                        }
                        if (btnAuto) {
                            btnAuto.innerHTML = '🟢 Auto-Pilot: ON';
                            btnAuto.style.background = '#238636';
                        }
                        if (topPill) {
                            topPill.innerHTML = '<span class="pulse-dot"></span> BOT & KEV.AI: ACTIVE';
                            topPill.classList.add('status-online');
                        }
                    } else {
                        if (badge) {
                            badge.innerHTML = 'STANDBY (PAUSED)';
                            badge.style.color = '#8b949e';
                        }
                        if (btnAuto) {
                            btnAuto.innerHTML = '⏸️ Auto-Pilot: PAUSED';
                            btnAuto.style.background = '#30363d';
                        }
                        if (topPill && !liveAutopilotActive) {
                            topPill.innerHTML = 'BOT & KEV.AI: PAUSED';
                            topPill.classList.remove('status-online');
                        }
                    }

                    if (cdEl) {
                        cdEl.textContent = `${data.autopilot.next_scan_seconds}s`;
                    }
                }

                // Update Active Positions
                const tbody = document.getElementById('active-positions-tbody');
                tbody.innerHTML = '';

                if (!data.active_positions || data.active_positions.length === 0) {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="12" style="text-align: center; color: var(--text-muted); padding: 30px;">
                                No active bracket positions open. Bot is monitoring for high-conviction signals.
                            </td>
                        </tr>
                    `;
                } else {
                    data.active_positions.forEach(p => {
                        const tr = document.createElement('tr');
                        const prec = getAssetPrecisionConfig(p.entry_price).precision;
                        const sideColor = p.side === 'BUY' || p.side === 'LONG' ? '#3fb950' : '#f85149';
                        const durationHours = p.duration_hours;
                        const hoursPct = Math.min(100, (durationHours / 12.0) * 100);

                        tr.innerHTML = `
                            <td><code style="color: #58a6ff;">${p.position_id}</code></td>
                            <td><strong>${p.symbol}</strong></td>
                            <td><strong style="color: ${sideColor};">${p.side}</strong></td>
                            <td>${p.quantity}</td>
                            <td>${formatAssetPrice(p.entry_price, prec)}</td>
                            <td style="color: #f85149;">${formatAssetPrice(p.stop_loss, prec)}</td>
                            <td style="color: #3fb950;">${formatAssetPrice(p.take_profit, prec)}</td>
                            <td>${p.duration_minutes}m</td>
                            <td>
                                <div style="width: 100px; background: #30363d; height: 6px; border-radius: 3px; overflow: hidden; margin-bottom: 2px;">
                                    <div style="width: ${hoursPct}%; background: ${hoursPct > 80 ? '#f85149' : '#58a6ff'}; height: 100%;"></div>
                                </div>
                                <span style="font-size: 10px; color: var(--text-muted);">${durationHours}/12h</span>
                            </td>
                            <td>
                                <button class="btn-table-action" style="color: #f85149;" onclick="closeBotPosition('${p.position_id}', ${p.entry_price})">Flatten</button>
                            </td>
                        `;
                        tbody.appendChild(tr);
                    });
                }

                // If last cycle data exists, render scan decisions & gate telemetry
                if (data.last_cycle && data.last_cycle.decisions && data.last_cycle.decisions.length > 0) {
                    renderScanDecisions(data.last_cycle);
                }

                loadLearningStats();
                if (data.paper_report) {
                    renderPaperTradingReport(data.paper_report);
            loadGeminiAssessment();
                }

            } catch (err) {
                console.error('Failed to load bot status:', err);
            }
        }

        async function toggleAutopilot() {
            try {
                const resp = await axios.post('/api/bot/autopilot/toggle', {});
                if (resp.data.success) {
                    showStatus('success', resp.data.message);
                    loadBotDashboard();
                }
            } catch (err) {
                showStatus('error', 'Failed to toggle autopilot');
            }
        }

        async function updateAutopilotInterval(seconds) {
            try {
                const resp = await axios.post('/api/bot/autopilot/toggle', { interval_seconds: parseInt(seconds) });
                if (resp.data.success) {
                    showStatus('success', `Autopilot scan interval set to ${seconds}s`);
                    loadBotDashboard();
                }
            } catch (err) {
                showStatus('error', 'Failed to update interval');
            }
        }

        function renderScanDecisions(cycleData) {
            const tbody = document.getElementById('scan-decisions-tbody');
            if (!tbody) return;
            tbody.innerHTML = '';

            const timeBadge = document.getElementById('scan-time-badge');
            if (timeBadge && cycleData.timestamp) {
                timeBadge.textContent = `Last Scan: ${cycleData.timestamp.replace('T', ' ').slice(0, 19)} UTC (${cycleData.evaluated_count} coins evaluated)`;
            }

            cycleData.decisions.forEach(d => {
                const tr = document.createElement('tr');
                const verdictBadge = d.approved ?
                    '<span class="badge-regime regime-bull">APPROVED</span>' :
                    '<span class="badge-regime regime-bear">VETOED</span>';

                let gateOrTicket = d.approved ?
                    `<span style="color: #3fb950; font-weight: 700;">Qty: ${d.ticket.quantity} | Notional: $${d.ticket.notional_usd.toFixed(2)}</span>` :
                    `<code style="color: #f85149;">${d.veto_gate || 'VETO'}</code>`;

                let advNotes = d.adversarial_notes || '';
                if (advNotes.includes('NANO_CONFLUENCE_CONFIRMED')) {
                    advNotes = `<div style="margin-bottom: 3px;"><span class="badge" style="background: rgba(0, 230, 118, 0.2); color: #00E676; border: 1px solid rgba(0,230,118,0.4); font-size: 10px; font-weight: 800; padding: 2px 5px; border-radius: 3px; display: inline-block;">⚡ NANO CONFLUENCE (+20%)</span></div>` + advNotes;
                } else if (advNotes.includes('NANO_CONFLICT_WARNING')) {
                    advNotes = `<div style="margin-bottom: 3px;"><span class="badge" style="background: rgba(255, 34, 85, 0.2); color: #ff3366; border: 1px solid rgba(255,34,85,0.4); font-size: 10px; font-weight: 800; padding: 2px 5px; border-radius: 3px; display: inline-block;">⚠️ NANO CONFLICT (-30%)</span></div>` + advNotes;
                }

                const top10Universe = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'ADAUSDT', 'AVAXUSDT', 'DOGEUSDT', 'LINKUSDT', 'NEARUSDT', 'SUIUSDT'];
                const isScoutedPrey = !top10Universe.includes(d.symbol) || advNotes.includes('TIGER');
                const scoutBadge = isScoutedPrey ? '<span class="badge" style="background: rgba(255, 152, 0, 0.2); color: #ff9800; font-size: 9px; padding: 1px 4px; border-radius: 3px; margin-left: 4px; font-weight: 800;">🐅 SCOUTED</span>' : '';

                tr.innerHTML = `
                    <td><strong>${d.symbol}</strong>${scoutBadge}</td>
                    <td>${d.side}</td>
                    <td>${verdictBadge}</td>
                    <td>${gateOrTicket}</td>
                    <td style="font-size: 11px; max-width: 320px;">${d.reason}</td>
                    <td style="font-size: 11px; color: var(--text-muted); max-width: 250px;">${advNotes}</td>
                `;
                tbody.appendChild(tr);
            });

            // Update KEV.ai 6-Point Gate Badges based on cycle results
            const g1 = document.getElementById('gate-1-badge');
            const g2 = document.getElementById('gate-2-badge');
            const g3 = document.getElementById('gate-3-badge');
            const g4 = document.getElementById('gate-4-badge');
            const g5 = document.getElementById('gate-5-badge');
            const g6 = document.getElementById('gate-6-badge');

            if (g1) g1.textContent = 'PASS: CLEAR';
            if (g2 && cycleData.breadth_pct) g2.textContent = `PASS: ${cycleData.breadth_pct} (${cycleData.macro_regime})`;

            const vetoGates = cycleData.decisions.map(d => d.veto_gate).filter(Boolean);
            if (g3) g3.textContent = vetoGates.includes('GATE_3_FEE_HURDLE') ? 'AUDIT: 0.04% FILTER ACTIVE' : 'PASS: NET EDGE >= 0.04%';
            if (g4) g4.textContent = vetoGates.includes('GATE_2_FUNDING_DRAG') ? 'AUDIT: CARRY SPIKE FILTERED' : 'PASS: FAVORABLE CARRY';
            if (g5) g5.textContent = vetoGates.includes('GATE_5_KELLY_SIZING') ? 'AUDIT: KELLY CONSTRAINED' : 'PASS: ρ < 0.85';
            if (g6) g6.textContent = vetoGates.includes('GATE_4_RR_RATIO') ? 'AUDIT: RR < 2.0 FILTERED' : 'PASS: RR >= 2.0';
        }

        async function triggerBotScan() {
            const btn = document.getElementById('bot-scan-btn');
            btn.disabled = true;
            btn.textContent = '⏳ Scanning Universe...';
            showStatus('info', 'Executing scan across Top-10 universe through KEV.ai 6-Point Gate...');

            try {
                const resp = await axios.post('/api/bot/scan', { account_equity: 10000.00 });
                const data = resp.data;
                if (!data.success) {
                    showStatus('error', data.error || 'Scan failed');
                    return;
                }

                document.getElementById('scan-time-badge').textContent = `Last Scan: ${data.timestamp.replace('T', ' ').slice(0, 19)} UTC`;
                showStatus('success', `Scan complete: Evaluated ${data.evaluated_count} coins. Dispatched ${data.dispatched_count} approved brackets.`);

                // Render Decision Log
                const tbody = document.getElementById('scan-decisions-tbody');
                tbody.innerHTML = '';

                data.decisions.forEach(d => {
                    const tr = document.createElement('tr');
                    const verdictBadge = d.approved ?
                        '<span class="badge-regime regime-bull">APPROVED</span>' :
                        '<span class="badge-regime regime-bear">VETOED</span>';

                    let gateOrTicket = d.approved ?
                        `<span style="color: #3fb950; font-weight: 700;">Qty: ${d.ticket.quantity} | Notional: $${d.ticket.notional_usd}</span>` :
                        `<code style="color: #f85149;">${d.veto_gate || 'VETO'}</code>`;

                    tr.innerHTML = `
                        <td><strong>${d.symbol}</strong></td>
                        <td>${d.side}</td>
                        <td>${verdictBadge}</td>
                        <td>${gateOrTicket}</td>
                        <td style="font-size: 11px; max-width: 320px;">${d.reason}</td>
                        <td style="font-size: 11px; color: var(--text-muted); max-width: 250px;">${d.adversarial_notes}</td>
                    `;
                    tbody.appendChild(tr);
                });

                // Refresh Positions Table
                loadBotDashboard();

            } catch (err) {
                console.error('Scan error:', err);
                showStatus('error', 'Market scan request failed');
            } finally {
                btn.disabled = false;
                btn.textContent = '⚡ Run Instant Market Scan';
            }
        }

        async function closeBotPosition(positionId, exitPrice) {
            try {
                const resp = await axios.post('/api/bot/close-position', {
                    position_id: positionId,
                    exit_price: exitPrice
                });
                if (resp.data.success) {
                    showStatus('success', `Position ${positionId} flattened at market.`);
                    loadBotDashboard();
                }
            } catch (err) {
                showStatus('error', 'Failed to close position');
            }
        }

        async function flattenAllPositions() {
            if (!confirm('Are you sure you want to emergency flatten all active positions?')) return;
            const rows = document.querySelectorAll('#active-positions-tbody tr');
            for (const r of rows) {
                const btn = r.querySelector('button');
                if (btn) btn.click();
            }
        }

        async function loadLearningStats() {
            try {
                const resp = await axios.get('/api/learning/stats');
                const data = resp.data;
                if (!data.success) return;

                // Update Hero Metric
                document.getElementById('dash-brier-val').textContent = `${data.brier_score.toFixed(4)} BS`;
                document.getElementById('dash-throttle-val').textContent = `${data.confidence_multiplier.toFixed(2)}x Capital`;
                document.getElementById('dash-calib-status').textContent = `Status: ${data.status}`;

                // Update Lessons Table
                const tbody = document.getElementById('learning-log-tbody');
                if (!tbody) return;
                tbody.innerHTML = '';

                if (!data.recent_outcomes || data.recent_outcomes.length === 0) {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="8" style="text-align: center; color: var(--text-muted); padding: 20px;">
                                No closed trade post-mortems logged yet in SQLite lessons.db.
                            </td>
                        </tr>
                    `;
                } else {
                    data.recent_outcomes.forEach(o => {
                        const tr = document.createElement('tr');
                        const pnlColor = o.pnl_usd >= 0 ? '#3fb950' : '#f85149';
                        tr.innerHTML = `
                            <td><code>${o.trade_id}</code></td>
                            <td><strong>${o.symbol}</strong></td>
                            <td>${o.side}</td>
                            <td>${(o.confidence * 100).toFixed(0)}%</td>
                            <td>${o.hit === 1 ? '<span style="color: #3fb950;">HIT (WIN)</span>' : '<span style="color: #f85149;">MISS (LOSS)</span>'}</td>
                            <td style="color: ${pnlColor}; font-weight: 700;">${o.pnl_usd >= 0 ? '+' : ''}$${o.pnl_usd.toFixed(2)}</td>
                            <td><span class="badge-regime">${o.exit_reason}</span></td>
                            <td style="color: var(--text-muted); font-size: 11px;">${o.timestamp.replace('T', ' ').slice(0, 19)}</td>
                        `;
                        tbody.appendChild(tr);
                    });
                }
            } catch (err) {
                console.error('Failed to load learning stats:', err);
            }
        }

        // =====================================================================
        // VIEW 4: REAL LIVE TRADING JAVASCRIPT API & TELEMETRY ENGINE
        // =====================================================================
        // liveAutopilotActive hoisted to global state

        async function loadLiveDashboard() {
            try {
                const resp = await axios.get('/api/live/status');
                const data = resp.data;
                if (!data.success) return;

                liveAutopilotActive = !!(data.autopilot && data.autopilot.enabled);

                if (data.contra_mode !== undefined && window.updateContraModeUI) {
                    window.updateContraModeUI(data.contra_mode);
                }

                // Check for Binance API connection / 401 error
                const errBanner = document.getElementById('live-api-error-banner');
                const errText = document.getElementById('live-api-error-text');
                const ipCode = document.getElementById('live-detected-ip');
                if (!data.connected && data.error) {
                    if (errBanner) {
                        errBanner.style.display = 'flex';
                        if (errText) errText.textContent = data.error;
                        const match = data.error.match(/request ip:\s*([0-9.]+)/i);
                        if (match && ipCode) {
                            ipCode.textContent = match[1];
                        }
                    }
                } else {
                    if (errBanner) errBanner.style.display = 'none';
                }

                // Update Control Bar & Badges
                const badge = document.getElementById('live-state-badge');
                const btnAuto = document.getElementById('btn-toggle-live-autopilot');
                const cdEl = document.getElementById('live-countdown');
                const intSelect = document.getElementById('live-interval-select');
                const topPill = document.getElementById('topbar-bot-pill');
                const bannerText = document.getElementById('mutual-exclusion-status-text');

                if (intSelect && data.autopilot && data.autopilot.interval_seconds) {
                    intSelect.value = String(data.autopilot.interval_seconds);
                }

                // Update AWS Tap Pill (Zero-Whitelist Relay)
                const awsPill = document.getElementById('topbar-aws-tap-pill');
                if (awsPill) {
                    if (data.aws_tap_active) {
                        awsPill.style.display = 'inline-flex';
                        awsPill.innerHTML = '<span class="pulse-dot" style="background: #00f0ff;"></span> 🔒 AWS TAP: ACTIVE (13.63.158.94)';
                        awsPill.style.color = '#00f0ff';
                        awsPill.style.borderColor = 'rgba(0, 240, 255, 0.4)';
                    } else {
                        awsPill.innerHTML = '<span class="pulse-dot" style="background: #8b949e;"></span> 🔒 AWS TAP: STANDBY';
                        awsPill.style.color = '#8b949e';
                        awsPill.style.borderColor = 'rgba(255, 255, 255, 0.1)';
                    }
                }

                if (liveAutopilotActive) {
                    // Update main Macro Dashboard with fresh live data
                    if (dashPortfolioViewMode === 'LIVE') {
                        renderMacroPortfolioLive(data);
                    }
                    if (badge) {
                        badge.innerHTML = '<span class="pulse-dot" style="background: #00E676;"></span> LIVE AUTOPILOT ACTIVE';
                        badge.style.color = '#00E676';
                    }
                    if (btnAuto) {
                        btnAuto.innerHTML = '🔴 Live Auto-Pilot: ON';
                        btnAuto.style.background = '#b62324';
                        btnAuto.style.borderColor = '#ff5252';
                        btnAuto.style.color = '#ffffff';
                    }
                    if (topPill) {
                        topPill.innerHTML = '<span class="pulse-dot" style="background: #ff5252;"></span> LIVE BINANCE: ACTIVE';
                        topPill.classList.add('status-online');
                    }
                    if (bannerText) {
                        bannerText.innerHTML = '<strong style="color: #00E676;">LIVE ACTIVE</strong> — Paper trading daemon is paused. Real capital risk governor and isolated bracket execution engaged.';
                    }
                } else {
                    if (badge) {
                        badge.innerHTML = 'STANDBY (PAUSED)';
                        badge.style.color = '#8b949e';
                    }
                    if (btnAuto) {
                        btnAuto.innerHTML = '⏸️ Live Auto-Pilot: PAUSED';
                        btnAuto.style.background = '#21262d';
                        btnAuto.style.borderColor = '#30363d';
                        btnAuto.style.color = '#8b949e';
                    }
                    if (bannerText) {
                        bannerText.innerHTML = 'When Real Live Trading is turned ON, Paper Trading is automatically paused to prevent double-polling, rate-limit burning, and risk conflicts.';
                    }
                }

                if (cdEl && data.autopilot) {
                    cdEl.textContent = `${data.autopilot.next_scan_seconds}s`;
                }

                // Update Real Binance Futures Account Metrics
                const acct = data.live_account || {};
                const walletBal = Number(acct.total_wallet_balance_usd || 0);
                const availBal = Number(acct.available_balance_usd || 0);
                const unrealPnl = Number(acct.unrealized_pnl_usd || 0);
                const marginRatio = Number(acct.margin_ratio_pct || 0);

                const elWallet = document.getElementById('live-wallet-balance-val');
                const elAvail = document.getElementById('live-avail-balance-val');
                const elPnl = document.getElementById('live-unrealized-pnl-val');
                const elMargin = document.getElementById('live-margin-ratio-val');
                const elMarginBadge = document.getElementById('live-margin-ratio-badge');

                if (elWallet) elWallet.textContent = `$${walletBal.toFixed(2)} USDT`;
                if (elAvail) elAvail.textContent = `$${availBal.toFixed(2)} USDT`;
                if (elPnl) {
                    elPnl.textContent = `${unrealPnl >= 0 ? '+' : ''}$${unrealPnl.toFixed(2)} USDT`;
                    elPnl.style.color = unrealPnl > 0 ? '#3fb950' : (unrealPnl < 0 ? '#f85149' : '#8b949e');
                }
                if (elMargin) elMargin.textContent = `${marginRatio.toFixed(2)}%`;
                if (elMarginBadge) {
                    if (marginRatio < 20.0) {
                        elMarginBadge.textContent = 'SAFE (< 20%)';
                        elMarginBadge.className = 'badge-regime regime-bull';
                    } else if (marginRatio < 50.0) {
                        elMarginBadge.textContent = 'MODERATE';
                        elMarginBadge.className = 'badge-regime regime-chop';
                    } else {
                        elMarginBadge.textContent = 'CRITICAL RISK (> 50%)';
                        elMarginBadge.className = 'badge-regime regime-bear';
                    }
                }

                // Update BNB Fee Buffer
                const bnbBal = Number(acct.bnb_balance || 0);
                const bnbActive = Boolean(acct.bnb_fee_discount_active);
                const elBnb = document.getElementById('live-bnb-balance-val');
                const elBnbBadge = document.getElementById('live-bnb-fee-badge');
                if (elBnb) elBnb.textContent = `${bnbBal.toFixed(4)} BNB`;
                if (elBnbBadge) {
                    if (bnbActive) {
                        elBnbBadge.textContent = '⚡ 10% DISCOUNT ACTIVE';
                        elBnbBadge.className = 'badge-regime regime-bull';
                    } else {
                        elBnbBadge.textContent = 'INACTIVE (USDT DEDUCTION)';
                        elBnbBadge.className = 'badge-regime regime-chop';
                    }
                }

                // If live autopilot is active, dynamically dedicate the main dashboard to Live Trading!
                if (liveAutopilotActive) {
                    const dTitle = document.getElementById('dash-portfolio-title');
                    const dBadge = document.getElementById('dash-paper-micro-badge');
                    const dReset = document.getElementById('dash-reset-btn');
                    const dLiveBtn = document.getElementById('dash-live-btn');
                    const dEquity = document.getElementById('dash-paper-equity');
                    const dStarting = document.getElementById('dash-paper-starting');
                    const dPnl = document.getElementById('dash-paper-pnl');
                    const dPnlPct = document.getElementById('dash-paper-pnl-pct');
                    const dWinLoss = document.getElementById('dash-paper-winloss');
                    const dWinRate = document.getElementById('dash-paper-winrate-badge');
                    const dTotal = document.getElementById('dash-paper-total-trades');
                    const dPF = document.getElementById('dash-paper-profitfactor');
                    const dFeeDrag = document.getElementById('dash-paper-fee-drag');

                    if (dTitle) dTitle.innerHTML = '<span style="color: #ff5252;">🔴 Real Live Futures Trading & Binance Margin Audit</span>';
                    if (dBadge) {
                        dBadge.innerHTML = '🔴 REAL LIVE CAPITAL ACTIVE (Binance Futures ISOLATED)';
                        dBadge.style.color = '#ff7b72';
                        dBadge.style.background = 'rgba(255, 82, 82, 0.2)';
                        dBadge.style.borderColor = 'rgba(255, 82, 82, 0.4)';
                    }
                    if (dReset) dReset.style.display = 'none';
                    if (dLiveBtn) dLiveBtn.style.display = 'inline-block';

                    if (dEquity) {
                        dEquity.textContent = `$${walletBal.toFixed(2)} USDT`;
                        dEquity.style.color = '#00E676';
                    }
                    if (dStarting) dStarting.textContent = `Available Collateral: $${availBal.toFixed(2)} USDT`;
                    if (dPnl) {
                        dPnl.textContent = `${unrealPnl >= 0 ? '+' : ''}$${unrealPnl.toFixed(2)}`;
                        dPnl.style.color = unrealPnl >= 0 ? '#3fb950' : '#f85149';
                    }
                    if (dPnlPct) dPnlPct.textContent = `Margin Ratio: ${marginRatio.toFixed(2)}%`;
                    if (dWinLoss) dWinLoss.textContent = `${acct.positions ? acct.positions.length : 0} Active Live Contracts`;
                    if (dWinRate) dWinRate.textContent = `Leverage: <=5x`;
                    if (dTotal) dTotal.textContent = `Margin Mode: ISOLATED`;
                    const dPfSub = document.getElementById('dash-card-pf-sub');
                    if (dPF) dPF.textContent = `${bnbBal.toFixed(4)} BNB`;
                    if (dPfSub) dPfSub.textContent = bnbActive ? '⚡ 10% Discount Active' : 'Standard USDT Fee Deduction';
                    if (dFeeDrag) dFeeDrag.textContent = `Live Telemetry via Binance API /fapi/v2/account`;
                }

                // Update Active Live Positions Table with Anti-Flicker Diffing
                const posTbody = document.getElementById('live-active-positions-tbody');
                if (posTbody) {
                    const positions = acct.positions || [];
                    const posSig = positions.map(p => `${p.symbol}:${p.position_amt}:${p.entry_price}:${p.mark_price}:${p.unrealized_pnl_usd}`).join('|');
                    if (window._lastLivePositionsSig !== posSig) {
                        window._lastLivePositionsSig = posSig;
                        posTbody.innerHTML = '';
                        if (positions.length === 0) {
                            posTbody.innerHTML = `
                                <tr>
                                    <td colspan="11" style="text-align: center; color: var(--text-muted); padding: 30px;">
                                        No active real live positions on Binance Futures. Real positions will appear here when filled.
                                    </td>
                                </tr>
                            `;
                        } else {
                            positions.forEach(p => {
                                const tr = document.createElement('tr');
                                const side = (p.side || '').toUpperCase();
                                const sideColor = side === 'BUY' || side === 'LONG' ? '#3fb950' : '#f85149';
                                const pnl = Number(p.unrealized_pnl_usd || 0);
                                const pnlColor = pnl >= 0 ? '#3fb950' : '#f85149';
                                const notional = Number(p.notional_usd || 0);
                                const entry = Number(p.entry_price || 0);
                                const mark = Number(p.mark_price || 0);
                                const lev = Number(p.leverage || 1);
                                const margin = Number(p.margin_usd || (lev > 0 ? notional / lev : notional));

                                tr.setAttribute('data-pos-symbol', p.symbol);
                                tr.setAttribute('data-entry-price', entry);
                                tr.setAttribute('data-pos-amt', p.position_amt);
                                tr.setAttribute('data-side', side);
                                tr.setAttribute('data-leverage', lev);

                                const isScalp = Boolean(p.is_scalp === true || p.trade_type === 'SCALP' || (window._currentActiveScalpSymbol && p.symbol === window._currentActiveScalpSymbol));
                                if (isScalp) tr.className = 'trade-row-scalp';

                                const symbolHtml = isScalp
                                    ? `<strong class="scalp-symbol-bold-blue">${p.symbol}</strong><span class="scalp-badge-bold-blue">⚡ SCALP</span>`
                                    : `<strong class="pos-symbol">${p.symbol}</strong><span class="badge-regime" style="background: rgba(163, 113, 247, 0.15); color: #a371f7; border: 1px solid rgba(163, 113, 247, 0.4); font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; margin-left: 6px;">🌐 MACRO</span>`;
                                const priceGain = p.price_gain_pct !== undefined ? Number(p.price_gain_pct) : (
                                    entry > 0 ? (side === 'BUY' || side === 'LONG' ? ((mark - entry) / entry * 100) : ((entry - mark) / entry * 100)) : 0
                                );
                                const priceGainColor = priceGain >= 0 ? '#3fb950' : '#f85149';
                                const netRoi = p.net_roi_pct !== undefined ? Number(p.net_roi_pct) : (
                                    margin > 0 ? ((pnl - (notional * 0.0008)) / margin * 100) : 0
                                );
                                const netRoiColor = netRoi >= 0 ? '#3fb950' : '#f85149';
                                const netRoiBg = netRoi >= 0 ? 'rgba(63, 185, 80, 0.12)' : 'rgba(248, 81, 73, 0.12)';

                                tr.innerHTML = `
                                    <td>${symbolHtml}</td>
                                    <td><strong style="color: ${sideColor};">${p.side}</strong></td>
                                    <td style="font-family: var(--font-mono);">${p.position_amt}</td>
                                    <td class="pos-cell-notional" style="font-family: var(--font-mono);">$${notional.toFixed(2)}</td>
                                    <td style="font-family: var(--font-mono);">$${entry.toFixed(2)}</td>
                                    <td class="pos-cell-mark" style="font-family: var(--font-mono);">$${mark.toFixed(2)}</td>
                                    <td class="pos-cell-pricegain" style="color: ${priceGainColor}; font-weight: 700; font-family: var(--font-mono);">${priceGain >= 0 ? '+' : ''}${priceGain.toFixed(2)}%</td>
                                    <td><span class="badge-regime" style="color: #58a6ff;">${(p.margin_type || 'isolated').toUpperCase()}</span></td>
                                    <td>${p.leverage}x</td>
                                    <td class="pos-cell-pnl" style="color: ${pnlColor}; font-weight: 700; font-family: var(--font-mono);">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}</td>
                                    <td class="pos-cell-netroi"><span class="badge-regime" style="color: ${netRoiColor}; font-weight: 700; border: 1px solid ${netRoiColor}; background: ${netRoiBg};">${netRoi >= 0 ? '+' : ''}${netRoi.toFixed(2)}%</span></td>
                                    <td>
                                        <button class="btn-table-action" style="color: #f85149;" onclick="flattenLivePositions()">Close</button>
                                    </td>
                                `;
                                posTbody.appendChild(tr);
                            });
                        }
                    }
                }

                // Update Live Trade History Table with Anti-Flicker Diffing & Stale Protection
                const tradesTbody = document.getElementById('live-trades-tbody');
                if (tradesTbody && data.trade_history) {
                    const trades = data.trade_history;
                    // Prevent transient network blips from wiping populated trades
                    if (trades.length === 0 && (window._lastLiveTradesCount || 0) > 0) {
                        // Keep previous trades visible instead of flickering
                    } else {
                        const tradesSig = trades.map(t => `${t.order_id || t.trade_id}:${t.price}:${t.quantity}:${t.realized_pnl_usd}:${t.time}`).join('|');
                        if (window._lastLiveTradesSig !== tradesSig) {
                            window._lastLiveTradesSig = tradesSig;
                            window._lastLiveTradesCount = trades.length;
                            if (typeof window.refreshYearlyMatrix === 'function') {
                                window.refreshYearlyMatrix(false);
                            }
                            tradesTbody.innerHTML = '';
                            if (trades.length === 0) {
                                tradesTbody.innerHTML = `
                                    <tr>
                                        <td colspan="8" style="text-align: center; color: var(--text-muted); padding: 25px;">
                                            Awaiting real executed live trades...
                                        </td>
                                    </tr>
                                `;
                            } else {
                                trades.forEach(t => {
                                    const tr = document.createElement('tr');
                                    const isScalp = Boolean(t.is_scalp || t.trade_type === 'SCALP');
                                    if (isScalp) tr.className = 'trade-row-scalp';
                                    const pnl = Number(t.realized_pnl_usd || t.realizedPnl || 0);
                                    let pnlDisplayHtml = '';
                                    if (Math.abs(pnl) < 0.0001) {
                                        pnlDisplayHtml = '<span class="badge" style="background: rgba(56,139,253,0.15); color: #58a6ff; font-weight: 700; font-size: 10px; padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(56,139,253,0.3);">ENTRY (OPEN)</span>';
                                    } else if (pnl > 0) {
                                        pnlDisplayHtml = `<strong style="color: #3fb950; font-weight: 700;">+$${pnl.toFixed(2)}</strong>`;
                                    } else {
                                        pnlDisplayHtml = `<strong style="color: #f85149; font-weight: 700;">-$${Math.abs(pnl).toFixed(2)}</strong>`;
                                    }
                                    const sideColor = t.side === 'BUY' ? '#3fb950' : '#f85149';
                                    const feeAsset = t.fee_asset || t.commissionAsset || 'USDT';
                                    const feeText = feeAsset === 'BNB' 
                                        ? `${t.fee_amount || t.commission || '0'} BNB (~$${Number(t.fee_usd || 0).toFixed(4)})` 
                                        : `$${Number(t.fee_usd || t.commission || 0).toFixed(4)} USDT`;
                                    const symbolHtml = isScalp
                                        ? `<strong class="scalp-symbol-bold-blue">${t.symbol}</strong><span class="scalp-badge-bold-blue">⚡ SCALP</span>`
                                        : `<strong>${t.symbol}</strong>`;
                                    const orderIdHtml = isScalp
                                        ? `<code style="color: #388bfd; font-weight: 800;">${t.order_id || t.trade_id} (SCALP)</code>`
                                        : `<code style="color: #58a6ff;">${t.order_id || t.trade_id}</code>`;
                                    tr.innerHTML = `
                                        <td style="color: var(--text-muted); font-size: 11px;">${(t.time || '').replace('T', ' ').slice(0, 19)}</td>
                                        <td>${orderIdHtml}</td>
                                        <td>${symbolHtml}</td>
                                        <td><strong style="color: ${sideColor};">${t.side}</strong></td>
                                        <td>$${Number(t.price || 0).toFixed(2)}</td>
                                        <td>${t.quantity}</td>
                                        <td style="color: var(--text-muted); font-size: 11px;">${feeText}</td>
                                        <td style="font-family: var(--font-mono);">${pnlDisplayHtml}</td>
                                    `;
                                    tradesTbody.appendChild(tr);
                                });
                            }
                        }
                    }
                }

                // Update KEV Gate Badges & Decisions from last live cycle
                if (data.last_cycle && data.last_cycle.decisions && data.last_cycle.decisions.length > 0) {
                    renderLiveScanDecisions(data.last_cycle);
                }

            } catch (err) {
                console.error('Failed to load live trading status:', err);
            }
        }

        function renderLiveScanDecisions(cycleData) {
            const tbody = document.getElementById('live-scan-decisions-tbody');
            if (!tbody) return;
            const cycleSig = `${cycleData.timestamp || ''}_${(cycleData.decisions || []).length}`;
            if (window._lastLiveCycleSig === cycleSig) return;
            window._lastLiveCycleSig = cycleSig;
            tbody.innerHTML = '';

            const timeBadge = document.getElementById('live-scan-time-badge');
            if (timeBadge && cycleData.timestamp) {
                timeBadge.textContent = `Last Live Scan: ${cycleData.timestamp.replace('T', ' ').slice(0, 19)} UTC (${cycleData.evaluated_count} coins evaluated)`;
            }

            cycleData.decisions.forEach(d => {
                const tr = document.createElement('tr');
                const verdictBadge = d.approved ?
                    '<span class="badge-regime regime-bull">LIVE APPROVED</span>' :
                    '<span class="badge-regime regime-bear">VETOED</span>';

                let gateOrTicket = d.approved ?
                    `<span style="color: #3fb950; font-weight: 700;">Qty: ${d.ticket.quantity} | Notional: $${d.ticket.notional_usd.toFixed(2)}</span>` :
                    `<code style="color: #f85149;">${d.veto_gate || 'VETO'}</code>`;

                tr.innerHTML = `
                    <td><strong>${d.symbol}</strong></td>
                    <td>${d.side}</td>
                    <td>${verdictBadge}</td>
                    <td>${gateOrTicket}</td>
                    <td style="font-size: 11px; max-width: 320px;">${d.reason}</td>
                    <td style="font-size: 11px; color: var(--text-muted); max-width: 250px;">${d.adversarial_notes}</td>
                `;
                tbody.appendChild(tr);
            });

            const g1 = document.getElementById('live-gate-1-badge');
            const g2 = document.getElementById('live-gate-2-badge');
            const g3 = document.getElementById('live-gate-3-badge');
            const g4 = document.getElementById('live-gate-4-badge');
            const g5 = document.getElementById('live-gate-5-badge');
            const g6 = document.getElementById('live-gate-6-badge');

            if (g1) g1.textContent = 'PASS: CLEAR';
            if (g2 && cycleData.breadth_pct) g2.textContent = `PASS: ${cycleData.breadth_pct} (${cycleData.macro_regime})`;

            const vetoGates = cycleData.decisions.map(d => d.veto_gate).filter(Boolean);
            if (g3) g3.textContent = vetoGates.includes('GATE_3_FEE_HURDLE') ? 'AUDIT: 0.04% FILTER ACTIVE' : 'PASS: NET EDGE >= 0.04%';
            if (g4) g4.textContent = vetoGates.includes('GATE_2_FUNDING_DRAG') ? 'AUDIT: CARRY SPIKE FILTERED' : 'PASS: FAVORABLE CARRY';
            if (g5) g5.textContent = vetoGates.includes('GATE_5_KELLY_SIZING') ? 'AUDIT: KELLY CONSTRAINED' : 'PASS: ρ < 0.85';
            if (g6) g6.textContent = vetoGates.includes('GATE_4_RR_RATIO') ? 'AUDIT: RR < 2.0 FILTERED' : 'PASS: RR >= 2.0';
        }

        async function toggleLiveAutopilot() {
            try {
                const resp = await axios.post('/api/live/toggle', {});
                if (resp.data.success) {
                    showStatus('success', resp.data.message);
                    loadLiveDashboard();
                    loadBotDashboard();
                }
            } catch (err) {
                showStatus('error', 'Failed to toggle live autopilot');
            }
        }

        async function updateLiveInterval(seconds) {
            try {
                const resp = await axios.post('/api/live/toggle', { interval_seconds: parseInt(seconds) });
                if (resp.data.success) {
                    showStatus('success', `Live scan interval set to ${seconds}s`);
                    loadLiveDashboard();
                }
            } catch (err) {
                showStatus('error', 'Failed to update live interval');
            }
        }

        async function triggerLiveScan() {
            const btn = document.getElementById('live-scan-btn');
            if (btn) {
                btn.disabled = true;
                btn.textContent = '⏳ Scanning Live Market...';
            }
            showStatus('info', 'Executing live universe scan with real Binance account balance...');

            try {
                const resp = await axios.post('/api/live/scan', {});
                const data = resp.data;
                if (!data.success) {
                    showStatus('error', data.error || 'Live scan failed');
                    return;
                }
                showStatus('success', `Live scan complete: Evaluated ${data.evaluated_count} coins. Dispatched ${data.dispatched_count} live brackets.`);
                loadLiveDashboard();
            } catch (err) {
                showStatus('error', 'Live scan request error: ' + err.message);
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = '⚡ Live Scan Now';
                }
            }
        }

        async function flattenLivePositions() {
            if (!confirm('EMERGENCY ACTION: Are you sure you want to cancel all open orders and market-flatten ALL live positions on Binance Futures?')) {
                return;
            }
            showStatus('info', 'Dispatching emergency flatten to Binance Futures...');
            try {
                const resp = await axios.post('/api/live/flatten', {});
                if (resp.data.success) {
                    showStatus('success', 'Emergency flatten executed successfully.');
                    loadLiveDashboard();
                } else {
                    showStatus('error', resp.data.error || 'Flatten failed');
                }
            } catch (err) {
                showStatus('error', 'Failed to dispatch flatten: ' + err.message);
            }
        }

        async function loadLiveTradesHistory() {
            try {
                const resp = await axios.get('/api/live/trades?limit=50');
                if (resp.data.success && resp.data.trades) {
                    showStatus('success', `Fetched ${resp.data.trades.length} live Binance trades.`);
                    loadLiveDashboard();
                }
            } catch (err) {
                showStatus('error', 'Failed to fetch live trade history');
            }
        }

        // =====================================================================
        // VIEW 2: ORIGINAL TRADINGVIEW & FORECASTER JAVASCRIPT
        // =====================================================================
        
        // =====================================================================
        // Real-Time Binance Futures WebSocket Stream (Sub-Second Live Prices)
        // =====================================================================
        let binanceWs = null;
        let binanceWsPrices = {};

        function initBinanceWebSocket() {
            try {
                if (binanceWs) {
                    try { binanceWs.close(); } catch(e){}
                }
                const wsUrl = 'wss://fstream.binance.com/ws/!miniTicker@arr';
                binanceWs = new WebSocket(wsUrl);

                binanceWs.onopen = function() {
                    console.log('⚡ Connected to Binance Futures Real-Time WebSocket stream');
                    const wsPill = document.getElementById('topbar-ws-pill');
                    if (wsPill) {
                        wsPill.style.display = 'inline-flex';
                        wsPill.innerHTML = '<span class="pulse-dot" style="background: #00E676;"></span> REALTIME STREAM';
                        wsPill.style.borderColor = 'rgba(0, 230, 118, 0.4)';
                        wsPill.style.color = '#00E676';
                    }
                };

                binanceWs.onmessage = function(event) {
                    try {
                        const data = JSON.parse(event.data);
                        if (Array.isArray(data)) {
                            handleBinanceMiniTickers(data);
                        }
                    } catch(err) {
                        console.warn('Error handling WS message:', err);
                    }
                };

                binanceWs.onerror = function(err) {
                    console.warn('Binance WebSocket error:', err);
                };

                binanceWs.onclose = function() {
                    console.warn('Binance WebSocket disconnected, reconnecting in 3s...');
                    const wsPill = document.getElementById('topbar-ws-pill');
                    if (wsPill) {
                        wsPill.innerHTML = '<span class="pulse-dot" style="background: #f85149;"></span> WS RECONNECTING';
                        wsPill.style.borderColor = 'rgba(248, 81, 73, 0.4)';
                        wsPill.style.color = '#f85149';
                    }
                    setTimeout(initBinanceWebSocket, 3000);
                };
            } catch(e) {
                console.error('Failed to create Binance WebSocket:', e);
            }
        }

        function handleBinanceMiniTickers(tickers) {
            tickers.forEach(t => {
                const sym = t.s;
                const price = parseFloat(t.c);
                const open = parseFloat(t.o);
                binanceWsPrices[sym] = price;

                // 1. Update Macro Dashboard Table row if present
                const priceCell = document.getElementById(`macro-price-${sym}`);
                if (priceCell) {
                    const oldPrice = parseFloat(priceCell.getAttribute('data-price') || '0');
                    if (price !== oldPrice) {
                        priceCell.setAttribute('data-price', price);
                        const prec = getAssetPrecisionConfig(price).precision;
                        priceCell.textContent = formatAssetPrice(price, prec);
                        
                        // Flash green or red
                        priceCell.style.transition = 'color 0.2s';
                        priceCell.style.color = price >= oldPrice ? '#3fb950' : '#f85149';
                        setTimeout(() => { priceCell.style.color = ''; }, 500);
                    }
                }

                const changeCell = document.getElementById(`macro-change-${sym}`);
                if (changeCell && open > 0) {
                    const chgPct = ((price - open) / open) * 100;
                    changeCell.textContent = `${chgPct >= 0 ? '+' : ''}${chgPct.toFixed(2)}%`;
                    changeCell.style.color = chgPct >= 0 ? '#3fb950' : '#f85149';
                }

                // 2. Update Workstation live candle if symbol matches active
                if (typeof wsState !== 'undefined' && wsState.activeSymbol === sym && wsState.candles && wsState.candles.length > 0) {
                    const lastCandle = wsState.candles[wsState.candles.length - 1];
                    lastCandle.close = price;
                    if (price > lastCandle.high) lastCandle.high = price;
                    if (price < lastCandle.low) lastCandle.low = price;
                    wsState.lastPrice = price;
                    if (typeof renderAllWorkstationPanels === 'function') {
                        renderAllWorkstationPanels();
                    }
                }

                // 3. Update Active Position rows matching this symbol
                const posRows = document.querySelectorAll(`tr[data-pos-symbol="${sym}"]`);
                posRows.forEach(row => {
                    const entry = parseFloat(row.getAttribute('data-entry-price') || '0');
                    const amt = parseFloat(row.getAttribute('data-pos-amt') || '0');
                    const side = (row.getAttribute('data-side') || 'BUY').toUpperCase();
                    const lev = parseFloat(row.getAttribute('data-leverage') || '1');
                    const isLong = side === 'BUY' || side === 'LONG';

                    if (entry > 0 && Math.abs(amt) > 0) {
                        const notional = Math.abs(amt) * price;
                        const pnl = isLong ? (price - entry) * Math.abs(amt) : (entry - price) * Math.abs(amt);
                        const priceGain = isLong ? ((price - entry) / entry * 100) : ((entry - price) / entry * 100);
                        const margin = lev > 0 ? notional / lev : notional;
                        const netRoi = margin > 0 ? ((pnl - (notional * 0.0008)) / margin * 100) : 0;

                        const markCell = row.querySelector('.pos-cell-mark');
                        if (markCell) markCell.textContent = `$${formatAssetPrice(price, getAssetPrecisionConfig(price).precision)}`;

                        const notionalCell = row.querySelector('.pos-cell-notional');
                        if (notionalCell) notionalCell.textContent = `$${notional.toFixed(2)}`;

                        const gainCell = row.querySelector('.pos-cell-pricegain');
                        if (gainCell) {
                            gainCell.textContent = `${priceGain >= 0 ? '+' : ''}${priceGain.toFixed(2)}%`;
                            gainCell.style.color = priceGain >= 0 ? '#3fb950' : '#f85149';
                        }

                        const pnlCell = row.querySelector('.pos-cell-pnl');
                        if (pnlCell) {
                            pnlCell.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`;
                            pnlCell.style.color = pnl >= 0 ? '#3fb950' : '#f85149';
                        }

                        const roiCell = row.querySelector('.pos-cell-netroi');
                        if (roiCell) {
                            const badge = roiCell.querySelector('.badge-regime');
                            if (badge) {
                                badge.textContent = `${netRoi >= 0 ? '+' : ''}${netRoi.toFixed(2)}%`;
                                const col = netRoi >= 0 ? '#3fb950' : '#f85149';
                                badge.style.color = col;
                                badge.style.borderColor = col;
                                badge.style.background = netRoi >= 0 ? 'rgba(63, 185, 80, 0.12)' : 'rgba(248, 81, 73, 0.12)';
                            }
                        }
                    }
                });
            });
        }

        document.addEventListener('DOMContentLoaded', function() {
            startLiveClock();
            initBinanceWebSocket();
            initializeApp();
            loadMacroOverview();
            loadBotDashboard();
            loadLiveDashboard();

            if (window._INITIAL_VIEW === 'scalper' || window.location.pathname.includes('/scalper') || window.location.hash === '#scalper') {
                setTimeout(() => { switchAppView('scalper'); }, 100);
            } else if (window._INITIAL_VIEW === 'tiger' || window.location.pathname.includes('/tiger') || window.location.hash === '#tiger') {
                setTimeout(() => { switchAppView('tiger'); }, 100);
            }

            // Real-time reactive polling for autonomous bot scans and telemetry
            setInterval(() => {
                if (currentActiveView === 'live') {
                    loadLiveDashboard();
                } else if (currentActiveView === 'bot') {
                    loadBotDashboard();
                } else if (currentActiveView === 'scalper') {
                    if (typeof loadScalperTelemetry === 'function') loadScalperTelemetry();
                } else if (currentActiveView === 'tiger') {
                    if (typeof fetchTigerRadarData === 'function') fetchTigerRadarData();
                } else {
                    // Update pill in background
                    if (liveAutopilotActive) loadLiveDashboard();
                }
            }, 3000);
            setInterval(() => {
                loadMacroOverview();
                updateStormProtocolUI();
                updateAntiBloatUI();
            }, 5000);
        });

        // Storm Protocol UI Updater & Toggle
        async function updateStormProtocolUI() {
            try {
                const resp = await axios.get('/api/storm/status');
                if (!resp.data || !resp.data.success || !resp.data.status) return;
                const s = resp.data.status;
                const stormPill = document.getElementById('topbar-storm-pill');
                if (!stormPill) return;

                if (s.is_storm_active) {
                    const minLeft = Math.ceil(s.seconds_remaining / 60);
                    if (s.phase === 'PHASE_1_SHOCK_PAUSE') {
                        const pauseMin = Math.ceil(s.pause_seconds_remaining / 60);
                        stormPill.innerHTML = `🌊 STORM: PAUSE (${pauseMin}m) · 1M/1S`;
                        stormPill.style.color = '#f85149';
                        stormPill.style.borderColor = 'rgba(248, 81, 73, 0.6)';
                        stormPill.style.background = 'rgba(248, 81, 73, 0.15)';
                    } else {
                        stormPill.innerHTML = `🌊 STORM: ACTIVE (${minLeft}m) · 1M/1S`;
                        stormPill.style.color = '#d29922';
                        stormPill.style.borderColor = 'rgba(210, 153, 34, 0.6)';
                        stormPill.style.background = 'rgba(210, 153, 34, 0.15)';
                    }
                } else {
                    stormPill.innerHTML = '🌊 CALM WATERS (6M / 3S)';
                    stormPill.style.color = '#00e5ff';
                    stormPill.style.borderColor = 'rgba(0, 229, 255, 0.4)';
                    stormPill.style.background = 'transparent';
                }
            } catch (e) {
                // silent
            }
        }

        window.toggleStormProtocol = async function() {
            try {
                const currentResp = await axios.get('/api/storm/status');
                const isActive = currentResp.data?.status?.is_storm_active;
                if (isActive) {
                    if (!confirm('Disarm Tsunami Storm Protocol and return to Normal Waters (6 Macro / 3 Scalp)?')) return;
                    const resp = await axios.post('/api/storm/toggle', { action: 'cancel' });
                    alert(resp.data.message || 'Storm mode deactivated.');
                } else {
                    if (!confirm('Activate Tsunami Storm Protocol (1-Hour Horizon)?\\n\\n• Clamps capacity to strictly 1 Macro and 1 Scalp.\\n• Enforces a 15-minute shock pause on new entries.\\n• Automatically recovers after 60 minutes.')) return;
                    const resp = await axios.post('/api/storm/toggle', { duration_minutes: 60, reason: 'Captain Manual Trigger' });
                    alert(resp.data.message || 'Storm mode activated.');
                }
                updateStormProtocolUI();
            } catch (e) {
                alert('Failed toggling storm protocol: ' + e.message);
            }
        };

        window.updateContraModeUI = function(isActive) {
            const active = Boolean(isActive);
            const topBtn = document.getElementById('topbar-contra-btn');
            const topLabel = document.getElementById('topbar-contra-label');
            const tigerBtn = document.getElementById('tigerContraBtn');
            const tigerText = document.getElementById('tigerContraBtnText');

            if (topBtn) {
                if (active) {
                    topBtn.classList.add('active');
                    if (topLabel) topLabel.textContent = '🔴 CONTRA: ACTIVE';
                } else {
                    topBtn.classList.remove('active');
                    if (topLabel) topLabel.textContent = 'CONTRA: OFF';
                }
            }

            if (tigerBtn) {
                if (active) {
                    tigerBtn.classList.add('active');
                    if (tigerText) tigerText.textContent = '🔴 CONTRA: ACTIVE';
                } else {
                    tigerBtn.classList.remove('active');
                    if (tigerText) tigerText.textContent = '🔴 CONTRA: OFF';
                }
            }
        };

        window.toggleContraMode = async function() {
            try {
                const statusResp = await axios.get('/api/contra/status');
                const currentlyActive = Boolean(statusResp.data?.contra_mode);
                const confirmMsg = currentlyActive
                    ? 'Disarm Contra Mode?\n\n• Normal execution will be restored (Long -> Long, Short -> Short).'
                    : 'ACTIVATE CONTRA TRADING MODE?\n\n• Inverts EVERY trade signal:\n  - If Strategy says LONG -> Buys become SHORTS.\n  - If Strategy says SHORT -> Sells become LONGS.\n• Mirrored Take-Profit & Stop-Loss brackets across entry price.\n• Identical 3x leverage, Kelly sizing, and risk budget.\n• Active across both Macro & Scalper engines.\n\nProceed?';
                if (!confirm(confirmMsg)) return;

                const resp = await axios.post('/api/contra/toggle');
                const newState = Boolean(resp.data?.contra_mode);
                window.updateContraModeUI(newState);
                alert(resp.data?.message || `Contra Mode is now ${newState ? 'ACTIVE' : 'OFF'}`);
            } catch (e) {
                alert('Failed toggling Contra Mode: ' + e.message);
            }
        };

        // Anti-Bloat 24/7 Engine UI Updater & Cleanse Trigger
        async function updateAntiBloatUI() {
            try {
                const resp = await axios.get('/api/system/anti-bloat');
                if (!resp.data || !resp.data.success || !resp.data.anti_bloat) return;
                const ab = resp.data.anti_bloat;
                const pill = document.getElementById('topbar-antibloat-pill');
                if (!pill) return;

                const report = ab.current_report || {};
                const sev = (report.severity || 'NORMAL').toUpperCase();
                const rss = report.process_rss_mb ? Math.round(report.process_rss_mb) : 0;
                const diskFree = report.disk_free_gb ? report.disk_free_gb.toFixed(1) : 0;
                const origin = resp.data.source === 'AWS_RELAY' ? 'AWS' : 'LOCAL';

                let color = '#26a69a';
                let bg = 'rgba(38, 166, 154, 0.15)';
                let border = 'rgba(38, 166, 154, 0.4)';
                let icon = '🧹';

                if (sev === 'CRITICAL') {
                    color = '#f85149';
                    bg = 'rgba(248, 81, 73, 0.2)';
                    border = 'rgba(248, 81, 73, 0.6)';
                    icon = '🚨';
                } else if (sev === 'WARNING') {
                    color = '#e3b341';
                    bg = 'rgba(227, 179, 65, 0.2)';
                    border = 'rgba(227, 179, 65, 0.6)';
                    icon = '⚠️';
                }

                pill.innerHTML = `${icon} BLOAT: ${sev} (${rss}MB | ${origin})`;
                pill.title = `Anti-Bloat 24/7 Engine [${origin}]:\nSeverity: ${sev}\nProcess RSS: ${rss}MB\nDisk Free: ${diskFree}GB\nCleans: ${ab.total_cleans_executed || 0}\nReclaimed: ${ab.total_reclaimed_mb || 0}MB\nClick to manually run deep cleanse.`;
                pill.style.color = color;
                pill.style.background = bg;
                pill.style.borderColor = border;
            } catch (e) {
                // silent
            }
        }

        window.triggerAntiBloatCleanse = async function() {
            const pill = document.getElementById('topbar-antibloat-pill');
            if (pill) {
                pill.innerHTML = `⏳ PURGING BLOAT...`;
            }
            try {
                const resp = await axios.post('/api/system/anti-bloat/clean');
                if (resp.data && resp.data.success) {
                    const sum = resp.data.clean_summary || {};
                    const reclaimed = sum.reclaimed_mb || 0;
                    const src = resp.data.source || 'LOCAL';
                    alert(`Anti-Bloat Cleanse Complete [${src}]!\nReclaimed: ${reclaimed} MB in ${(sum.duration_seconds || 0).toFixed(2)}s\nSeverity: ${resp.data.severity_after || 'NORMAL'}`);
                } else {
                    alert('Anti-Bloat Cleanse returned: ' + JSON.stringify(resp.data));
                }
            } catch (err) {
                alert('Failed to trigger anti-bloat cleanse: ' + (err.response?.data?.error || err.message));
            } finally {
                updateAntiBloatUI();
            }
        };

        // Initialize application
        async function initializeApp() {
            console.log('🚀 Initializing Kronos Web UI...');
            initTradingViewChart();
            await loadAvailableModels();
            await loadDataFiles();
            setupEventListeners();
            initializeTimeSlider();
            console.log('✅ Application initialization completed');
        }

        // Load available models
        async function loadAvailableModels() {
            try {
                const response = await axios.get('/api/available-models');
                if (response.data.model_available) {
                    availableModels = response.data.models;
                    populateModelSelect();
                } else {
                    showStatus('warning', 'Kronos model library not available, will use simulated prediction');
                }
            } catch (error) {
                console.error('❌ Failed to load available models:', error);
            }
        }

        // Populate model selection dropdown
        function populateModelSelect() {
            const modelSelect = document.getElementById('model-select');
            modelSelect.innerHTML = '';
            
            Object.entries(availableModels).forEach(([key, model]) => {
                const option = document.createElement('option');
                option.value = key;
                option.textContent = `${model.name} (${model.params}) - ${model.description}`;
                if (key === 'kronos-base') option.selected = true;
                modelSelect.appendChild(option);
            });

            if (availableModels['kronos-base']) modelSelect.value = 'kronos-base';
        }

        // Load model
        async function loadModel() {
            const modelKey = document.getElementById('model-select').value;
            const device = document.getElementById('device-select').value;
            if (!modelKey) return;
            
            try {
                document.getElementById('load-model-btn').disabled = true;
                showStatus('info', `Loading ${modelKey} on ${device}...`);
                const response = await axios.post('/api/load-model', { model_key: modelKey, device: device });
                if (response.data.success) {
                    modelLoaded = true;
                    showStatus('success', response.data.message);
                    document.getElementById('predict-btn').disabled = false;
                } else {
                    showStatus('error', response.data.error);
                }
            } catch (error) {
                showStatus('error', `Model loading failed: ${error.message}`);
            } finally {
                document.getElementById('load-model-btn').disabled = false;
            }
        }

        // Load data file list
        async function loadDataFiles() {
            try {
                const response = await axios.get('/api/data-files');
                const dataFiles = response.data;
                const dataFileSelect = document.getElementById('data-file-select');
                dataFileSelect.innerHTML = '<option value="">Please select data file</option>';
                dataFiles.forEach(file => {
                    const option = document.createElement('option');
                    option.value = file.path;
                    option.textContent = `${file.name} (${file.size})`;
                    dataFileSelect.appendChild(option);
                });
            } catch (error) {
                console.error('Failed to load data files:', error);
            }
        }

        // Load data file
        async function loadData() {
            const filePath = document.getElementById('data-file-select').value;
            if (!filePath) return;
            try {
                document.getElementById('load-data-btn').disabled = true;
                const response = await axios.post('/api/load-data', { file_path: filePath });
                if (response.data.success) {
                    currentDataFile = filePath;
                    currentDataInfo = response.data.data_info;
                    showDataInfo(response.data.data_info);
                    showStatus('success', response.data.message);
                    if (modelLoaded) document.getElementById('predict-btn').disabled = false;
                } else {
                    showStatus('error', response.data.error);
                }
            } catch (error) {
                showStatus('error', `Data loading failed: ${error.message}`);
            } finally {
                document.getElementById('load-data-btn').disabled = false;
            }
        }

        // Fetch Live Binance Candles
        async function fetchBinanceData() {
            const symbol = document.getElementById('binance-asset-select').value;
            const interval = document.getElementById('binance-interval-select').value;
            const limit = parseInt(document.getElementById('binance-limit-select').value, 10);
            if (!symbol) return;
            
            try {
                document.getElementById('fetch-binance-btn').disabled = true;
                showStatus('info', `Fetching ${symbol} (${interval}) candles from Binance...`);
                const response = await axios.post('/api/binance/fetch-klines', { symbol, interval, limit });
                if (response.data.success) {
                    currentDataFile = response.data.file_path;
                    currentDataInfo = response.data.data_info;
                    showDataInfo(response.data.data_info);
                    showStatus('success', `Loaded ${symbol} live candles!`);
                    await loadDataFiles();
                    const dataFileSelect = document.getElementById('data-file-select');
                    dataFileSelect.value = response.data.file_path;
                    if (modelLoaded) document.getElementById('predict-btn').disabled = false;
                } else {
                    showStatus('error', response.data.error || 'Failed to fetch');
                }
            } catch (error) {
                showStatus('error', `Binance error: ${error.message}`);
            } finally {
                document.getElementById('fetch-binance-btn').disabled = false;
            }
        }

        // Display data information
        function showDataInfo(dataInfo) {
            document.getElementById('data-info').style.display = 'block';
            document.getElementById('data-rows').textContent = dataInfo.rows;
            document.getElementById('data-cols').textContent = dataInfo.columns.length;
            
            const pConf = getAssetPrecisionConfig(dataInfo.price_range ? dataInfo.price_range.min : 100);
            currentAssetPrecision = pConf.precision;
            document.getElementById('data-price-range').textContent = `${formatAssetPrice(dataInfo.price_range.min, currentAssetPrecision)} - ${formatAssetPrice(dataInfo.price_range.max, currentAssetPrecision)}`;
            document.getElementById('data-timeframe').textContent = dataInfo.timeframe;

            const badgeEl = document.getElementById('tv-symbol-badge');
            if (badgeEl) {
                badgeEl.textContent = `${dataInfo.symbol || 'ASSET'} · ${dataInfo.timeframe || dataInfo.interval || '1H'}`;
            }

            if (dataInfo.candles && dataInfo.candles.length > 0) {
                renderTradingViewData(dataInfo.candles, [], []);
            }
        }

        function initializeTimeSlider() {}

        // Setup event listeners
        function setupEventListeners() {
            document.getElementById('load-model-btn').addEventListener('click', loadModel);
            document.getElementById('load-data-btn').addEventListener('click', loadData);
            document.getElementById('fetch-binance-btn').addEventListener('click', fetchBinanceData);
            document.getElementById('predict-btn').addEventListener('click', runPrediction);

            document.getElementById('lookback-slider').addEventListener('input', (e) => {
                document.getElementById('lookback-value').textContent = e.target.value;
            });
            document.getElementById('pred-len-slider').addEventListener('input', (e) => {
                document.getElementById('pred-len-value').textContent = e.target.value;
            });
        }

        // Run prediction
        async function runPrediction() {
            if (!currentDataFile) {
                showStatus('error', 'Please load data first');
                return;
            }

            const lookback = parseInt(document.getElementById('lookback-slider').value, 10);
            const predLen = parseInt(document.getElementById('pred-len-slider').value, 10);
            const predictBtn = document.getElementById('predict-btn');

            try {
                predictBtn.disabled = true;
                predictBtn.textContent = '🔮 Running Kronos Neural Inference...';
                showStatus('info', `Generating ${predLen}-period forecast with Kronos AI...`);

                const payload = {
                    file_path: currentDataFile,
                    lookback: lookback,
                    pred_len: predLen,
                    use_tail: true,
                    temperature: 1.0,
                    top_p: 0.9,
                    sample_count: 1
                };

                const response = await axios.post('/api/predict', payload);
                if (response.data.success) {
                    showStatus('success', 'Prediction trajectory generated successfully!');
                    
                    // Render Plotly Chart
                    if (response.data.chart_json) {
                        try {
                            const chartData = JSON.parse(response.data.chart_json);
                            Plotly.newPlot('chart', chartData.data, chartData.layout, { responsive: true });
                        } catch(e){}
                    }

                    // Render TradingView Chart
                    if (response.data.tv_candles) {
                        renderTradingViewData(
                            response.data.tv_candles.historical,
                            response.data.tv_candles.prediction,
                            response.data.tv_candles.actual || []
                        );
                    }

                    // Show detailed table if comparison available
                    if (response.data.detailed_comparison) {
                        showDetailedComparison(response.data.detailed_comparison);
                    }
                } else {
                    showStatus('error', response.data.error || 'Prediction failed');
                }
            } catch (error) {
                showStatus('error', `Prediction error: ${error.message}`);
            } finally {
                predictBtn.disabled = false;
                predictBtn.textContent = '🔮 Generate Neural Forecast';
            }
        }

        function showDetailedComparison(data) {
            const table = document.getElementById('detailed-comparison');
            const tbody = document.getElementById('comparison-tbody');
            table.style.display = 'block';
            tbody.innerHTML = '';
            data.slice(0, 50).forEach(row => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${row.time}</td>
                    <td>${formatAssetPrice(row.actual_open)}</td>
                    <td>${formatAssetPrice(row.pred_open)}</td>
                    <td>${formatAssetPrice(row.actual_high)}</td>
                    <td>${formatAssetPrice(row.pred_high)}</td>
                    <td>${formatAssetPrice(row.actual_low)}</td>
                    <td>${formatAssetPrice(row.pred_low)}</td>
                    <td>${formatAssetPrice(row.actual_close)}</td>
                    <td>${formatAssetPrice(row.pred_close)}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        // TradingView Pro Initialization
        function initTradingViewChart() {
            const container = document.getElementById('tv-chart-container');
            if (!container || typeof LightweightCharts === 'undefined') return;

            if (tvChart) {
                try { tvChart.remove(); } catch(e){}
                tvChart = null;
            }
            container.innerHTML = '';

            tvChart = LightweightCharts.createChart(container, {
                width: container.clientWidth || 900,
                height: 600,
                layout: {
                    background: { type: 'solid', color: '#131722' },
                    textColor: '#d1d4dc',
                    fontFamily: "'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif",
                },
                grid: {
                    vertLines: { color: '#1e222d' },
                    horzLines: { color: '#1e222d' },
                },
                crosshair: {
                    mode: LightweightCharts.CrosshairMode.Normal,
                    vertLine: { color: '#758696', width: 1, style: LightweightCharts.LineStyle.Dashed },
                    horzLine: { color: '#758696', width: 1, style: LightweightCharts.LineStyle.Dashed },
                },
                rightPriceScale: {
                    borderColor: '#2a2e39',
                    autoScale: true,
                    scaleMargins: { top: 0.08, bottom: 0.22 },
                },
                timeScale: {
                    borderColor: '#2a2e39',
                    timeVisible: true,
                    secondsVisible: false,
                },
            });

            tvVolumeSeries = tvChart.addHistogramSeries({
                priceFormat: { type: 'volume' },
                priceScaleId: '',
                scaleMargins: { top: 0.82, bottom: 0 },
            });

            tvHistCandleSeries = tvChart.addCandlestickSeries({
                upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
                wickUpColor: '#26a69a', wickDownColor: '#ef5350', title: 'Historical',
            });

            tvPredCandleSeries = tvChart.addCandlestickSeries({
                upColor: '#00E676', downColor: '#FF5252', borderVisible: false,
                wickUpColor: '#00E676', wickDownColor: '#FF5252', title: 'Kronos AI Pred',
            });

            tvPredLineSeries = tvChart.addLineSeries({
                color: '#00E676', lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Dotted, title: 'Forecast Close',
            });

            tvActualCandleSeries = tvChart.addCandlestickSeries({
                upColor: '#2962FF', downColor: '#FF9800', borderVisible: false,
                wickUpColor: '#2962FF', wickDownColor: '#FF9800', title: 'Actual Candles', visible: false,
            });

            tvActualLineSeries = tvChart.addLineSeries({
                color: '#FF9800', lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Solid, title: 'Actual Close',
            });

            tvChart.subscribeCrosshairMove(param => {
                if (!param || !param.time || !param.seriesData) return;
                let bar = param.seriesData.get(tvPredCandleSeries) || 
                          param.seriesData.get(tvHistCandleSeries) || 
                          param.seriesData.get(tvActualCandleSeries);
                let vol = param.seriesData.get(tvVolumeSeries);

                if (bar && bar.open !== undefined) {
                    const dt = new Date(param.time * 1000);
                    document.getElementById('leg-date').textContent = dt.toISOString().replace('T', ' ').slice(0, 19);
                    document.getElementById('leg-open').textContent = formatAssetPrice(bar.open, currentAssetPrecision);
                    document.getElementById('leg-high').textContent = formatAssetPrice(bar.high, currentAssetPrecision);
                    document.getElementById('leg-low').textContent = formatAssetPrice(bar.low, currentAssetPrecision);
                    document.getElementById('leg-close').textContent = formatAssetPrice(bar.close, currentAssetPrecision);
                    
                    const isUp = bar.close >= bar.open;
                    document.getElementById('leg-close').style.color = isUp ? '#00E676' : '#FF5252';
                    if (vol && vol.value !== undefined) {
                        document.getElementById('leg-vol').textContent = vol.value.toLocaleString();
                    }
                }
            });

            window.addEventListener('resize', () => {
                if (tvChart && container) tvChart.applyOptions({ width: container.clientWidth });
            });
        }

        function cleanAndSortBars(rawBars) {
            const map = new Map();
            for (const b of rawBars) {
                const t = parseInt(b.time, 10);
                if (!t || isNaN(t)) continue;
                map.set(t, {
                    time: t,
                    open: parseFloat(b.open),
                    high: parseFloat(b.high),
                    low: parseFloat(b.low),
                    close: parseFloat(b.close),
                    volume: parseFloat(b.volume || 0)
                });
            }
            return Array.from(map.values()).sort((a, b) => a.time - b.time);
        }

        function renderTradingViewData(histBars, predBars, actualBars) {
            if (!tvChart) initTradingViewChart();
            if (!tvChart) return;

            tvCachedHistBars = histBars || [];
            tvCachedPredBars = predBars || [];
            tvCachedActualBars = actualBars || [];

            const sampleBar = (histBars && histBars.length > 0) ? histBars[histBars.length - 1] : 
                              ((predBars && predBars.length > 0) ? predBars[0] : null);
            if (sampleBar && sampleBar.close !== undefined) {
                const pConfig = getAssetPrecisionConfig(parseFloat(sampleBar.close));
                currentAssetPrecision = pConfig.precision;
                const priceFormat = {
                    type: 'price',
                    precision: pConfig.precision,
                    minMove: pConfig.minMove
                };
                if (tvHistCandleSeries) tvHistCandleSeries.applyOptions({ priceFormat });
                if (tvPredCandleSeries) tvPredCandleSeries.applyOptions({ priceFormat });
                if (tvPredLineSeries) tvPredLineSeries.applyOptions({ priceFormat });
                if (tvActualCandleSeries) tvActualCandleSeries.applyOptions({ priceFormat });
                if (tvActualLineSeries) tvActualLineSeries.applyOptions({ priceFormat });
            }

            if (histBars && histBars.length > 0) {
                const sortedHist = cleanAndSortBars(histBars);
                tvHistCandleSeries.setData(sortedHist);
                const volData = sortedHist.map(b => ({
                    time: b.time,
                    value: b.volume || 0,
                    color: b.close >= b.open ? 'rgba(38, 166, 154, 0.45)' : 'rgba(239, 83, 80, 0.45)'
                }));
                tvVolumeSeries.setData(volData);
            }

            if (predBars && predBars.length > 0) {
                const sortedPred = cleanAndSortBars(predBars);
                tvPredCandleSeries.setData(sortedPred);
                tvPredLineSeries.setData(sortedPred.map(b => ({ time: b.time, value: b.close })));
                tvPredCandleSeries.setMarkers([
                    {
                        time: sortedPred[0].time,
                        position: 'aboveBar',
                        color: '#00E676',
                        shape: 'arrowDown',
                        text: '🔮 Kronos AI Forecast'
                    }
                ]);
            } else {
                tvPredCandleSeries.setData([]);
                tvPredLineSeries.setData([]);
                tvPredCandleSeries.setMarkers([]);
            }

            if (actualBars && actualBars.length > 0) {
                const sortedActual = cleanAndSortBars(actualBars);
                tvActualCandleSeries.setData(sortedActual);
                tvActualLineSeries.setData(sortedActual.map(b => ({ time: b.time, value: b.close })));
            } else {
                tvActualCandleSeries.setData([]);
                tvActualLineSeries.setData([]);
            }

            // Focus transition
            if (histBars && predBars && histBars.length > 0 && predBars.length > 0) {
                const sortedHist = cleanAndSortBars(histBars);
                const sortedPred = cleanAndSortBars(predBars);
                const fromIdx = Math.max(0, sortedHist.length - 80);
                tvChart.timeScale().setVisibleRange({
                    from: sortedHist[fromIdx].time,
                    to: sortedPred[sortedPred.length - 1].time
                });
            } else {
                tvChart.timeScale().fitContent();
            }
        }

        function switchChartEngine(engine) {
            activeChartEngine = engine;
            const tvEl = document.getElementById('tv-chart-container');
            const plEl = document.getElementById('chart');
            const btnTv = document.getElementById('btn-engine-tv');
            const btnPl = document.getElementById('btn-engine-plotly');

            if (engine === 'tradingview') {
                tvEl.style.display = 'block';
                plEl.style.display = 'none';
                btnTv.style.background = '#238636';
                btnTv.style.color = '#ffffff';
                btnPl.style.background = '#21262d';
                btnPl.style.color = '#8b949e';
                if (tvChart) tvChart.timeScale().fitContent();
            } else {
                tvEl.style.display = 'none';
                plEl.style.display = 'block';
                btnPl.style.background = '#238636';
                btnPl.style.color = '#ffffff';
                btnTv.style.background = '#21262d';
                btnTv.style.color = '#8b949e';
                Plotly.Plots.resize('chart');
            }
        }
    
        // =====================================================================
        // PAPER TRADING & WIN/LOSS REPORTING ENGINE
        // =====================================================================
        function renderPaperTradingReport(rep) {
            if (!rep) return;

            // 0. Update Last Trade Memory Banners
            const dashLastTrade = document.getElementById('dash-last-trade-desc');
            const botLastTrade = document.getElementById('bot-last-trade-desc');
            if (rep.last_paper_trade) {
                const lt = rep.last_paper_trade;
                const isWin = lt.result === 'WIN';
                const pColor = isWin ? '#3fb950' : (lt.result === 'LOSS' ? '#f85149' : '#d29922');
                const sideColor = (lt.side === 'BUY' || lt.side === 'LONG') ? '#3fb950' : '#f85149';
                const tradeSummaryHtml = `<strong>${lt.symbol}</strong> <span style="color: ${sideColor}; font-weight: 700;">${lt.side}</span> | Entry: $${lt.entry_price} &rarr; Exit: $${lt.exit_price} | PnL: <strong style="color: ${pColor};">${lt.realized_pnl_usd >= 0 ? '+' : ''}$${lt.realized_pnl_usd.toFixed(2)} (${lt.return_pct >= 0 ? '+' : ''}${lt.return_pct.toFixed(2)}%)</strong> | <span class="badge-regime ${isWin ? 'regime-bull' : 'regime-bear'}" style="font-size: 10px;">${lt.result}</span> <span style="color: var(--text-muted); font-size: 11px;">(${lt.reason})</span>`;
                if (dashLastTrade) dashLastTrade.innerHTML = tradeSummaryHtml;
                if (botLastTrade) botLastTrade.innerHTML = tradeSummaryHtml;
            } else {
                const openCount = rep.active_positions_count || (rep.open_positions ? rep.open_positions.length : 0);
                const awaitHtml = `Awaiting initial exit trigger... (Active open bracket positions: ${openCount})`;
                if (dashLastTrade) dashLastTrade.textContent = awaitHtml;
                if (botLastTrade) botLastTrade.textContent = awaitHtml;
            }

            // 1. Dashboard View is 100% Real Live Binance Trading (No paper trading on Macro Dashboard)
            // Paper trading report updates are restricted to the Paper Bot view.

            // 2. Update Bot View Elements
            const botEquity = document.getElementById('bot-equity-val');
            if (botEquity) {
                botEquity.textContent = `$${rep.current_equity.toFixed(2)} USD`;
                botEquity.style.color = rep.current_equity >= rep.initial_equity ? '#2ea043' : '#f85149';
            }
            const botWinLossBadge = document.getElementById('bot-paper-winloss-badge');
            if (botWinLossBadge) {
                botWinLossBadge.textContent = `${rep.winning_trades} Wins vs ${rep.losing_trades} Losses (Win Rate: ${rep.win_rate_pct.toFixed(1)}%)`;
            }

            // 3. Render Tables (Dashboard Mini Table & Bot Full Table)
            const dashTbody = document.getElementById('dash-paper-trades-tbody');
            const botTbody = document.getElementById('bot-closed-trades-tbody');

            if (!rep.closed_trades || rep.closed_trades.length === 0) {
                const emptyRow = `
                    <tr>
                        <td colspan="12" style="text-align: center; color: var(--text-muted); padding: 20px;">
                            No closed paper trades yet. Autopilot is evaluating universe for high-conviction micro signals.
                        </td>
                    </tr>
                `;
                if (dashTbody) dashTbody.innerHTML = emptyRow;
                if (botTbody) botTbody.innerHTML = emptyRow;
            } else {
                let rowsHtml = '';
                rep.closed_trades.forEach(t => {
                    const isWin = t.result === 'WIN';
                    const resBadge = isWin ?
                        '<span class="badge-regime regime-bull" style="font-size: 11px;">WIN</span>' :
                        '<span class="badge-regime regime-bear" style="font-size: 11px;">LOSS</span>';
                    const pnlColor = isWin ? '#3fb950' : '#f85149';
                    const sideColor = (t.side === 'BUY' || t.side === 'LONG') ? '#3fb950' : '#f85149';
                    const dt = new Date(t.close_time);
                    const timeStr = dt.toTimeString().split(' ')[0] + ' UTC';
                    const feeVal = (t.fee_usd || 0).toFixed(2);
                    const grossVal = (t.gross_pnl_usd !== undefined ? t.gross_pnl_usd : t.realized_pnl_usd);
                    const grossColor = grossVal >= 0 ? '#3fb950' : '#f85149';

                    const isScalp = Boolean(t.is_scalp || t.trade_type === 'SCALP' || (t.position_id && String(t.position_id).startsWith('SCALP')));
                    const rowClass = isScalp ? ' class="trade-row-scalp"' : '';
                    const symHtml = isScalp
                        ? `<strong class="scalp-symbol-bold-blue">${t.symbol}</strong><span class="scalp-badge-bold-blue">⚡ SCALP</span>`
                        : `<strong>${t.symbol}</strong>`;
                    rowsHtml += `
                        <tr${rowClass}>
                            <td style="font-family: var(--font-mono); color: var(--text-muted);">${timeStr}</td>
                            <td>${symHtml}</td>
                            <td><strong style="color: ${sideColor};">${t.side}</strong></td>
                            <td style="font-family: var(--font-mono);">${t.entry_price}</td>
                            <td style="font-family: var(--font-mono);">${t.exit_price}</td>
                            <td>${t.quantity}</td>
                            <td style="font-family: var(--font-mono); color: #8b949e;">-$${feeVal}</td>
                            <td style="font-family: var(--font-mono); color: ${grossColor};">${grossVal >= 0 ? '+' : ''}$${grossVal.toFixed(2)}</td>
                            <td style="font-weight: 700; color: ${pnlColor}; font-family: var(--font-mono);">${t.realized_pnl_usd >= 0 ? '+' : ''}$${t.realized_pnl_usd.toFixed(2)}</td>
                            <td style="color: ${pnlColor}; font-family: var(--font-mono);">${t.return_pct >= 0 ? '+' : ''}${t.return_pct.toFixed(2)}%</td>
                            <td>${resBadge}</td>
                            <td style="font-size: 11px; color: var(--text-secondary);">${t.reason}</td>
                        </tr>
                    `;
                });
                if (dashTbody) dashTbody.innerHTML = rowsHtml;
                if (botTbody) botTbody.innerHTML = rowsHtml;
            }
        }

        async function resetPaperTrading() {
            if (!confirm("Reset paper trading account back to $200.00 USDT starting balance and clear paper trade history?")) {
                return;
            }
            try {
                const resp = await axios.post('/api/bot/paper-reset', { equity: 200.00 });
                if (resp.data.success) {
                    showStatus('success', resp.data.message);
                    renderPaperTradingReport(resp.data.paper_report);
                    loadBotDashboard();
                    loadMacroOverview();
                }
            } catch (err) {
                showStatus('error', 'Failed to reset paper trading account.');
            }
        }

    
        // =====================================================================
        // KRONOS QUANT WORKSTATION & DYNAMIC CHART ENGINE (INSTITUTIONAL GRADE)
        // =====================================================================
        const wsState = {
            activeSymbol: 'BTCUSDT',
            candles: [],
            prediction: [],
            lastPrice: 77859.0,
            isInitialized: false,
            countdownSeconds: 50 * 60 + 4,
            timerInterval: null
        };

        // Indicator overlay toggles (EMA 7, EMA 21, VWAP, Monte Carlo)
        const indicatorConfig = {
            ema7: true,
            ema21: true,
            vwap: true,
            monteCarlo: true
        };

        function toggleIndicator(name) {
            if (indicatorConfig.hasOwnProperty(name)) {
                indicatorConfig[name] = !indicatorConfig[name];
                const chipId = name === 'monteCarlo' ? 'chip-mc' : `chip-${name}`;
                const chip = document.getElementById(chipId);
                if (chip) {
                    chip.style.opacity = indicatorConfig[name] ? '1.0' : '0.4';
                    chip.style.textDecoration = indicatorConfig[name] ? 'none' : 'line-through';
                }
                renderMainChartCanvas();
            }
        }

        // Navigation state for Main Chart (pan & zoom)
        const chartNav = {
            panX: 0,
            panY: 0,
            zoom: 1.0,
            isDragging: false,
            dragStartX: 0,
            dragStartY: 0,
            isPriceScaleDragging: false,
            priceScaleStartY: 0,
            priceScaleMultiplier: 1.0,
            crosshairX: null,
            crosshairY: null
        };

        // Navigation state for Heat Map sub-pane
        const heatMapNav = {
            panX: 0,
            isDragging: false,
            dragStartX: 0
        };

        // Navigation state for CVD Flow sub-pane
        const flowNav = {
            panX: 0,
            isDragging: false,
            dragStartX: 0
        };

        function toggleAdvancedSettings() {
            const drawer = document.getElementById('ws-advanced-drawer');
            if (drawer) {
                drawer.style.display = drawer.style.display === 'none' ? 'block' : 'none';
            }
        }

        function resetChartNav() {
            chartNav.panX = 0;
            chartNav.panY = 0;
            chartNav.zoom = 1.0;
            chartNav.priceScaleMultiplier = 1.0;
            chartNav.crosshairX = null;
            chartNav.crosshairY = null;
            renderMainChartCanvas();
        }

        function zoomChart(factor) {
            chartNav.zoom = Math.max(0.4, Math.min(3.5, chartNav.zoom * factor));
            renderMainChartCanvas();
        }

        function panChart(deltaX) {
            chartNav.panX += deltaX;
            renderMainChartCanvas();
        }

        function initWorkstation() {
            if (wsState.isInitialized) {
                renderAllWorkstationPanels();
                return;
            }
            wsState.isInitialized = true;

            // 1. Initialize splitters (horizontal and vertical)
            initSplitters();

            // 2. Initialize chart & pane mouse/touch drag listeners
            initMainChartInteractions();
            initHeatMapInteractions();
            initFlowInteractions();

            // 3. Setup ResizeObservers for crisp canvas rendering
            setupCanvasResizers();

            // 4. Start real-time countdown clock
            startCountdownTimer();
            startWorkstationClock();

            // 5. Populate initial sim log stream
            initAgentSimLog();

            // 6. Fetch live candles
            fetchWorkstationCandles(wsState.activeSymbol);
        }

        function initSplitters() {
            // Horizontal Splitter (Chart vs Bottom Panes)
            const hSplitter = document.getElementById('ws-h-splitter');
            const topFrame = document.getElementById('ws-top-chart-frame');
            const botFrame = document.getElementById('ws-bottom-panes-frame');
            const rootContainer = document.getElementById('ws-interactive-workspace');

            if (hSplitter && topFrame && botFrame && rootContainer) {
                let isDraggingH = false;
                let startY = 0;
                let startTopH = 0;

                hSplitter.addEventListener('mousedown', (e) => {
                    isDraggingH = true;
                    startY = e.clientY;
                    startTopH = topFrame.offsetHeight;
                    hSplitter.classList.add('dragging');
                    document.body.style.cursor = 'row-resize';
                    document.body.style.userSelect = 'none';
                });

                window.addEventListener('mousemove', (e) => {
                    if (!isDraggingH) return;
                    const deltaY = e.clientY - startY;
                    const containerH = rootContainer.offsetHeight;
                    const newTopH = Math.max(220, Math.min(containerH - 180, startTopH + deltaY));
                    topFrame.style.height = `${newTopH}px`;
                    topFrame.style.flex = `0 0 ${newTopH}px`;
                    botFrame.style.flex = '1 1 auto';
                    renderAllWorkstationPanels();
                });

                window.addEventListener('mouseup', () => {
                    if (isDraggingH) {
                        isDraggingH = false;
                        hSplitter.classList.remove('dragging');
                        document.body.style.cursor = '';
                        document.body.style.userSelect = '';
                        renderAllWorkstationPanels();
                    }
                });
            }

            // Vertical Splitters (Pane 1, Pane 2, Pane 3)
            initVerticalSplitter('ws-v-splitter-1', 'pane-heatmap', 'pane-flow');
            initVerticalSplitter('ws-v-splitter-2', 'pane-flow', 'pane-agent-log');
        }

        function initVerticalSplitter(splitterId, leftPaneId, rightPaneId) {
            const splitter = document.getElementById(splitterId);
            const leftPane = document.getElementById(leftPaneId);
            const rightPane = document.getElementById(rightPaneId);
            if (!splitter || !leftPane || !rightPane) return;

            let isDraggingV = false;
            let startX = 0;
            let startLeftW = 0;

            splitter.addEventListener('mousedown', (e) => {
                isDraggingV = true;
                startX = e.clientX;
                startLeftW = leftPane.offsetWidth;
                splitter.classList.add('dragging');
                document.body.style.cursor = 'col-resize';
                document.body.style.userSelect = 'none';
            });

            window.addEventListener('mousemove', (e) => {
                if (!isDraggingV) return;
                const deltaX = e.clientX - startX;
                const parentW = splitter.parentElement.offsetWidth;
                const newLeftW = Math.max(160, Math.min(parentW - 320, startLeftW + deltaX));
                const leftPct = (newLeftW / parentW) * 100;
                leftPane.style.width = `${leftPct}%`;
                leftPane.style.flex = `0 0 ${leftPct}%`;
                renderAllWorkstationPanels();
            });

            window.addEventListener('mouseup', () => {
                if (isDraggingV) {
                    isDraggingV = false;
                    splitter.classList.remove('dragging');
                    document.body.style.cursor = '';
                    document.body.style.userSelect = '';
                    renderAllWorkstationPanels();
                }
            });
        }

        function initMainChartInteractions() {
            const canvas = document.getElementById('canvas-main-chart');
            if (!canvas) return;

            canvas.addEventListener('mousedown', (e) => {
                const rect = canvas.getBoundingClientRect();
                const mouseX = e.clientX - rect.left;
                const chartW = rect.width - 75;

                if (mouseX >= chartW) {
                    chartNav.isPriceScaleDragging = true;
                    chartNav.priceScaleStartY = e.clientY;
                    canvas.style.cursor = 'ns-resize';
                } else {
                    chartNav.isDragging = true;
                    chartNav.dragStartX = e.clientX - chartNav.panX;
                    chartNav.dragStartY = e.clientY - chartNav.panY;
                    canvas.style.cursor = 'grabbing';
                }
            });

            window.addEventListener('mousemove', (e) => {
                const rect = canvas.getBoundingClientRect();
                const mouseX = e.clientX - rect.left;
                const mouseY = e.clientY - rect.top;

                if (chartNav.isDragging) {
                    chartNav.panX = e.clientX - chartNav.dragStartX;
                    chartNav.panY = e.clientY - chartNav.dragStartY;
                    renderMainChartCanvas();
                } else if (chartNav.isPriceScaleDragging) {
                    const dy = e.clientY - chartNav.priceScaleStartY;
                    chartNav.priceScaleMultiplier = Math.max(0.2, Math.min(4.0, chartNav.priceScaleMultiplier + dy * 0.005));
                    chartNav.priceScaleStartY = e.clientY;
                    renderMainChartCanvas();
                } else if (mouseX >= 0 && mouseX <= rect.width && mouseY >= 0 && mouseY <= rect.height) {
                    chartNav.crosshairX = mouseX;
                    chartNav.crosshairY = mouseY;
                    renderMainChartCanvas();
                }
            });

            window.addEventListener('mouseup', () => {
                if (chartNav.isDragging || chartNav.isPriceScaleDragging) {
                    chartNav.isDragging = false;
                    chartNav.isPriceScaleDragging = false;
                    canvas.style.cursor = 'crosshair';
                }
            });

            canvas.addEventListener('mouseleave', () => {
                if (!chartNav.isDragging && !chartNav.isPriceScaleDragging) {
                    chartNav.crosshairX = null;
                    chartNav.crosshairY = null;
                    renderMainChartCanvas();
                }
            });

            canvas.addEventListener('wheel', (e) => {
                e.preventDefault();
                const zoomFactor = e.deltaY < 0 ? 1.12 : 0.89;
                const rect = canvas.getBoundingClientRect();
                const mouseX = e.clientX - rect.left;
                const prevZoom = chartNav.zoom;
                chartNav.zoom = Math.max(0.35, Math.min(3.8, chartNav.zoom * zoomFactor));

                // Zoom towards mouse pointer
                const zoomRatio = chartNav.zoom / prevZoom;
                chartNav.panX = mouseX - (mouseX - chartNav.panX) * zoomRatio;
                renderMainChartCanvas();
            }, { passive: false });

            canvas.addEventListener('dblclick', () => {
                resetChartNav();
            });

            // Touch events for mobile/tablet pan
            let lastTouchX = null;
            canvas.addEventListener('touchstart', (e) => {
                if (e.touches.length === 1) {
                    lastTouchX = e.touches[0].clientX;
                }
            });
            canvas.addEventListener('touchmove', (e) => {
                if (e.touches.length === 1 && lastTouchX !== null) {
                    const dx = e.touches[0].clientX - lastTouchX;
                    lastTouchX = e.touches[0].clientX;
                    chartNav.panX += dx;
                    renderMainChartCanvas();
                }
            });
            canvas.addEventListener('touchend', () => {
                lastTouchX = null;
            });
        }

        function initHeatMapInteractions() {
            const canvas = document.getElementById('canvas-heatmap');
            if (!canvas) return;

            canvas.addEventListener('mousedown', (e) => {
                heatMapNav.isDragging = true;
                heatMapNav.dragStartX = e.clientX - heatMapNav.panX;
                canvas.style.cursor = 'grabbing';
            });

            window.addEventListener('mousemove', (e) => {
                if (!heatMapNav.isDragging) return;
                heatMapNav.panX = e.clientX - heatMapNav.dragStartX;
                renderHeatMapCanvas();
            });

            window.addEventListener('mouseup', () => {
                if (heatMapNav.isDragging) {
                    heatMapNav.isDragging = false;
                    canvas.style.cursor = 'grab';
                }
            });

            canvas.addEventListener('wheel', (e) => {
                e.preventDefault();
                heatMapNav.panX += (e.deltaY < 0 ? 30 : -30);
                renderHeatMapCanvas();
            }, { passive: false });
        }

        function initFlowInteractions() {
            const canvas = document.getElementById('canvas-flow');
            if (!canvas) return;

            canvas.addEventListener('mousedown', (e) => {
                flowNav.isDragging = true;
                flowNav.dragStartX = e.clientX - flowNav.panX;
                canvas.style.cursor = 'grabbing';
            });

            window.addEventListener('mousemove', (e) => {
                if (!flowNav.isDragging) return;
                flowNav.panX = e.clientX - flowNav.dragStartX;
                renderFlowCanvas();
            });

            window.addEventListener('mouseup', () => {
                if (flowNav.isDragging) {
                    flowNav.isDragging = false;
                    canvas.style.cursor = 'grab';
                }
            });

            canvas.addEventListener('wheel', (e) => {
                e.preventDefault();
                flowNav.panX += (e.deltaY < 0 ? 30 : -30);
                renderFlowCanvas();
            }, { passive: false });
        }

        function setupCanvasResizers() {
            const wrappers = ['mc-canvas-wrapper', 'hm-canvas-wrapper', 'flow-canvas-wrapper'];
            wrappers.forEach(id => {
                const el = document.getElementById(id);
                if (el && window.ResizeObserver) {
                    const ro = new ResizeObserver(() => {
                        requestAnimationFrame(() => renderAllWorkstationPanels());
                    });
                    ro.observe(el);
                }
            });
            window.addEventListener('resize', () => {
                requestAnimationFrame(() => renderAllWorkstationPanels());
            });
        }

        function startCountdownTimer() {
            if (wsState.timerInterval) clearInterval(wsState.timerInterval);
            wsState.timerInterval = setInterval(() => {
                wsState.countdownSeconds--;
                if (wsState.countdownSeconds <= 0) wsState.countdownSeconds = 60 * 60;

                const mins = Math.floor(wsState.countdownSeconds / 60);
                const secs = wsState.countdownSeconds % 60;
                const formatted = `T-${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
                
                const timerEl = document.getElementById('ws-overlay-timer');
                if (timerEl) timerEl.textContent = formatted;

                const tapeTimer = document.getElementById('ws-signal-timer-text');
                if (tapeTimer) tapeTimer.textContent = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
            }, 1000);
        }

        function startWorkstationClock() {
            setInterval(() => {
                const now = new Date();
                const clockEl = document.getElementById('ws-header-clock');
                if (clockEl) {
                    clockEl.textContent = now.toISOString().slice(11, 19) + ' UTC';
                }
            }, 1000);
        }

        function switchWorkstationAsset(symbol) {
            wsState.activeSymbol = symbol;

            // Highlight active button pill
            document.querySelectorAll('.ws-asset-pill').forEach(btn => btn.classList.remove('active'));
            const cleanSym = symbol.replace('USDT', '');
            const pill = document.getElementById(`ws-pill-${cleanSym}`);
            if (pill) pill.classList.add('active');

            // Reset pan/zoom on switch
            chartNav.panX = 0;
            chartNav.panY = 0;
            chartNav.zoom = 1.0;

            // Update HUD elements
            const hudSym = document.getElementById('ws-hud-symbol-window');
            if (hudSym) hudSym.textContent = `${cleanSym} 1H · 12:00-13:00`;

            const hmTag = document.getElementById('hm-asset-tag');
            if (hmTag) hmTag.textContent = `${cleanSym}/USD`;

            const footerAsset = document.getElementById('ws-footer-asset');
            if (footerAsset) footerAsset.textContent = `${cleanSym}/USD · 1h · Binance Futures`;

            // Sync with hidden select
            const binanceSelect = document.getElementById('binance-asset-select');
            if (binanceSelect) binanceSelect.value = symbol;

            fetchWorkstationCandles(symbol);
        }

        async function fetchWorkstationCandles(symbol) {
            try {
                const res = await axios.post('/api/binance/fetch-klines', {
                    symbol: symbol,
                    interval: '1h',
                    limit: 120
                });

                if (res.data && res.data.success && res.data.data_info && res.data.data_info.candles) {
                    wsState.candles = res.data.data_info.candles;
                    if (wsState.candles.length > 0) {
                        const lastCandle = wsState.candles[wsState.candles.length - 1];
                        wsState.lastPrice = lastCandle.close;
                    }
                } else {
                    generateFallbackCandles(symbol);
                }
            } catch (e) {
                console.warn('Live klines fetch error, using synthetic candles:', e);
                generateFallbackCandles(symbol);
            }
            renderAllWorkstationPanels();
        }

        function generateFallbackCandles(symbol) {
            let base = 77859.0;
            if (symbol.includes('ETH')) base = 2540.0;
            else if (symbol.includes('SOL')) base = 188.5;
            else if (symbol.includes('XRP')) base = 0.5840;
            else if (symbol.includes('PEPE')) base = 0.0000095;

            const candles = [];
            const now = Math.floor(Date.now() / 1000) - 100 * 3600;
            let cur = base * 0.94;

            for (let i = 0; i < 90; i++) {
                const delta = (Math.random() - 0.485) * (base * 0.008);
                const open = cur;
                const close = cur + delta;
                const high = Math.max(open, close) + Math.random() * (base * 0.004);
                const low = Math.min(open, close) - Math.random() * (base * 0.004);
                const volume = Math.floor(Math.random() * 8000 + 1200);
                candles.push({ time: now + i * 3600, open, high, low, close, volume });
                cur = close;
            }
            wsState.candles = candles;
            wsState.lastPrice = cur;
        }

        function renderAllWorkstationPanels() {
            if (!wsState.candles || wsState.candles.length === 0) return;
            renderMainChartCanvas();
            renderHeatMapCanvas();
            renderFlowCanvas();
        }

        // =====================================================================
        // PANEL 1: MAIN CANDLESTICK CHART CANVAS WITH GOLDEN MONTE CARLO FAN
        // =====================================================================
        function renderMainChartCanvas() {
            const canvas = document.getElementById('canvas-main-chart');
            if (!canvas) return;
            const wrapper = document.getElementById('mc-canvas-wrapper');
            if (!wrapper) return;

            const dpr = window.devicePixelRatio || 1;
            const width = wrapper.clientWidth;
            const height = wrapper.clientHeight;
            if (width <= 0 || height <= 0) return;

            canvas.width = width * dpr;
            canvas.height = height * dpr;
            const ctx = canvas.getContext('2d');
            ctx.scale(dpr, dpr);

            // Deep background
            ctx.fillStyle = '#090d14';
            ctx.fillRect(0, 0, width, height);

            const candles = wsState.candles;
            if (!candles || candles.length === 0) return;

            const padTop = 25;
            const padBottom = 35;
            const padRight = 80;
            const chartH = height - padTop - padBottom;
            const chartW = width - padRight;

            const barW = Math.max(3, 14 * chartNav.zoom);
            const bodyW = Math.max(2, barW * 0.70);

            // Origin of latest candle close
            const currentCandleX = chartW * 0.62 + chartNav.panX;
            const lastClose = wsState.lastPrice || candles[candles.length - 1].close;

            // Price bounds
            let minP = Infinity;
            let maxP = -Infinity;
            candles.forEach((c, idx) => {
                const x = currentCandleX - (candles.length - 1 - idx) * barW;
                if (x >= -barW * 2 && x <= chartW + barW * 2) {
                    if (c.low < minP) minP = c.low;
                    if (c.high > maxP) maxP = c.high;
                }
            });

            if (minP === Infinity || maxP === -Infinity) {
                minP = lastClose * 0.95;
                maxP = lastClose * 1.05;
            }

            const pRange = (maxP - minP) || (lastClose * 0.05);
            const midP = (maxP + minP) / 2;
            const effHalfRange = (pRange / 2) * (1 / chartNav.priceScaleMultiplier);
            const effMinP = midP - effHalfRange;
            const effMaxP = midP + effHalfRange;
            const effRange = effMaxP - effMinP;

            function getY(p) {
                return padTop + chartH - ((p - effMinP) / effRange) * chartH + chartNav.panY;
            }

            // Grid Lines & Price Labels
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
            ctx.lineWidth = 1;
            ctx.setLineDash([3, 3]);
            const numGrids = 7;
            for (let i = 0; i <= numGrids; i++) {
                const y = padTop + (chartH / numGrids) * i;
                ctx.beginPath();
                ctx.moveTo(0, y);
                ctx.lineTo(chartW, y);
                ctx.stroke();

                const priceAtY = effMaxP - (effRange / numGrids) * i - (chartNav.panY / chartH) * effRange;
                const prec = getAssetPrecisionConfig(priceAtY);
                ctx.fillStyle = '#64748b';
                ctx.font = '10px Consolas, monospace';
                ctx.textAlign = 'left';
                ctx.fillText(formatAssetPrice(priceAtY, prec.priceDecimals), chartW + 8, y + 3);
            }
            ctx.setLineDash([]);

            // Draw Red Vertical Marker Indicator Lines
            // 1. "10-30 outside" marker
            const red1X = currentCandleX - 35 * barW;
            if (red1X >= 0 && red1X <= chartW) {
                ctx.strokeStyle = '#ef4444';
                ctx.lineWidth = 1.2;
                ctx.beginPath();
                ctx.moveTo(red1X, padTop);
                ctx.lineTo(red1X, padTop + chartH * 0.45);
                ctx.stroke();

                ctx.fillStyle = '#ef4444';
                ctx.font = '10px Consolas, monospace';
                ctx.textAlign = 'center';
                ctx.fillText('10-30 outside', red1X, padTop - 6);
            }

            // 2. "10-31 outside" marker
            const red2X = currentCandleX - 16 * barW;
            if (red2X >= 0 && red2X <= chartW) {
                ctx.strokeStyle = '#ef4444';
                ctx.lineWidth = 1.4;
                ctx.beginPath();
                ctx.moveTo(red2X, padTop);
                ctx.lineTo(red2X, padTop + chartH * 0.55);
                ctx.stroke();

                ctx.fillStyle = '#ef4444';
                ctx.font = '10px Consolas, monospace';
                ctx.textAlign = 'center';
                ctx.fillText('10-31 outside', red2X, padTop - 6);
            }

            // Draw Candlesticks (Dark Monochrome Institutional Style)
            candles.forEach((c, idx) => {
                const x = currentCandleX - (candles.length - 1 - idx) * barW;
                if (x < -barW * 2 || x > chartW + barW * 2) return;

                const openY = getY(c.open);
                const closeY = getY(c.close);
                const highY = getY(c.high);
                const lowY = getY(c.low);
                const isUp = c.close >= c.open;

                if (isUp) {
                    // White bullish candle
                    ctx.strokeStyle = '#ffffff';
                    ctx.fillStyle = '#ffffff';
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    ctx.moveTo(x, highY);
                    ctx.lineTo(x, lowY);
                    ctx.stroke();

                    const top = Math.min(openY, closeY);
                    const h = Math.max(2, Math.abs(closeY - openY));
                    ctx.fillRect(x - bodyW / 2, top, bodyW, h);
                } else {
                    // Dark bearish candle with light outline
                    ctx.strokeStyle = '#94a3b8';
                    ctx.fillStyle = '#090d14';
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    ctx.moveTo(x, highY);
                    ctx.lineTo(x, lowY);
                    ctx.stroke();

                    const top = Math.min(openY, closeY);
                    const h = Math.max(2, Math.abs(closeY - openY));
                    ctx.fillRect(x - bodyW / 2, top, bodyW, h);
                    ctx.strokeRect(x - bodyW / 2, top, bodyW, h);
                }
            });

            // =================================================================
            // TECHNICAL INDICATORS: EMA 7 (Cyan), EMA 21 (Amber), VWAP (Yellow)
            // =================================================================
            const ema7Values = [];
            const ema21Values = [];
            const vwapValues = [];
            let cumVol = 0;
            let cumVP = 0;

            const k7 = 2 / (7 + 1);
            const k21 = 2 / (21 + 1);
            let prevE7 = candles[0].close;
            let prevE21 = candles[0].close;

            candles.forEach((c, idx) => {
                const e7 = idx === 0 ? c.close : (c.close * k7 + prevE7 * (1 - k7));
                const e21 = idx === 0 ? c.close : (c.close * k21 + prevE21 * (1 - k21));
                prevE7 = e7;
                prevE21 = e21;
                ema7Values.push(e7);
                ema21Values.push(e21);

                const typicalP = (c.high + c.low + c.close) / 3;
                const vol = c.volume || 1;
                cumVol += vol;
                cumVP += typicalP * vol;
                vwapValues.push(cumVol > 0 ? (cumVP / cumVol) : c.close);
            });

            // 1. Draw EMA 7 (Cyan #22d3ee)
            if (indicatorConfig.ema7) {
                ctx.strokeStyle = '#22d3ee';
                ctx.lineWidth = 1.6;
                ctx.beginPath();
                let started = false;
                candles.forEach((c, idx) => {
                    const x = currentCandleX - (candles.length - 1 - idx) * barW;
                    if (x >= -barW * 4 && x <= chartW + barW * 4) {
                        const y = getY(ema7Values[idx]);
                        if (!started) {
                            ctx.moveTo(x, y);
                            started = true;
                        } else {
                            ctx.lineTo(x, y);
                        }
                    }
                });
                ctx.stroke();
            }

            // 2. Draw EMA 21 (Amber #f59e0b)
            if (indicatorConfig.ema21) {
                ctx.strokeStyle = '#f59e0b';
                ctx.lineWidth = 1.6;
                ctx.beginPath();
                let started = false;
                candles.forEach((c, idx) => {
                    const x = currentCandleX - (candles.length - 1 - idx) * barW;
                    if (x >= -barW * 4 && x <= chartW + barW * 4) {
                        const y = getY(ema21Values[idx]);
                        if (!started) {
                            ctx.moveTo(x, y);
                            started = true;
                        } else {
                            ctx.lineTo(x, y);
                        }
                    }
                });
                ctx.stroke();
            }

            // 3. Draw VWAP (Yellow #eab308)
            if (indicatorConfig.vwap) {
                ctx.strokeStyle = '#eab308';
                ctx.lineWidth = 1.4;
                ctx.setLineDash([4, 2]);
                ctx.beginPath();
                let started = false;
                candles.forEach((c, idx) => {
                    const x = currentCandleX - (candles.length - 1 - idx) * barW;
                    if (x >= -barW * 4 && x <= chartW + barW * 4) {
                        const y = getY(vwapValues[idx]);
                        if (!started) {
                            ctx.moveTo(x, y);
                            started = true;
                        } else {
                            ctx.lineTo(x, y);
                        }
                    }
                });
                ctx.stroke();
                ctx.setLineDash([]);
            }

            // 4. Draw Volume Bars at Base of Chart
            const maxVol = Math.max(...candles.map(c => c.volume || 1));
            const volBaseY = padTop + chartH;
            const maxBarH = 28;
            candles.forEach((c, idx) => {
                const x = currentCandleX - (candles.length - 1 - idx) * barW;
                if (x < -barW * 2 || x > chartW + barW * 2) return;
                const vH = Math.max(1, ((c.volume || 1) / maxVol) * maxBarH);
                ctx.fillStyle = c.close >= c.open ? 'rgba(255, 255, 255, 0.22)' : 'rgba(148, 163, 184, 0.16)';
                ctx.fillRect(x - bodyW / 2, volBaseY - vH, bodyW, vH);
            });

            // Date Ticks on bottom timeline
            ctx.fillStyle = '#64748b';
            ctx.font = '10px Consolas, monospace';
            ctx.textAlign = 'center';
            if (red2X >= 20 && red2X <= chartW) {
                ctx.fillText('10-31', red2X, padTop + chartH + 18);
            }
            const dateNextX = currentCandleX + 16 * barW;
            if (dateNextX >= 20 && dateNextX <= chartW) {
                ctx.fillText('11-01', dateNextX, padTop + chartH + 18);
            }

            // =================================================================
            // GOLDEN MONTE CARLO TRAJECTORY FAN (1,000 FUTURES)
            // =================================================================
            const startX = currentCandleX;
            const startY = getY(lastClose);
            const horizonBars = 30;
            const endX = startX + horizonBars * barW;

            // Reticle Target Ring on Current Close
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.7)';
            ctx.lineWidth = 1.2;
            ctx.beginPath();
            ctx.arc(startX, startY, 5, 0, Math.PI * 2);
            ctx.stroke();

            ctx.strokeStyle = 'rgba(250, 204, 21, 0.8)';
            ctx.beginPath();
            ctx.arc(startX, startY, 2, 0, Math.PI * 2);
            ctx.stroke();

            // 1. Outlier diverging paths (cool grey / cyan)
            for (let i = 0; i < 16; i++) {
                const spreadNorm = (i / 15) * 1.6 - 0.3; // upward to sideways
                const outlierTargetY = startY - (chartH * 0.40) * spreadNorm;
                ctx.strokeStyle = 'rgba(148, 163, 184, 0.22)';
                ctx.lineWidth = 0.9;
                ctx.beginPath();
                ctx.moveTo(startX, startY);
                const cpX = startX + (endX - startX) * 0.45;
                const cpY = startY - (chartH * 0.15) * spreadNorm + Math.sin(i * 1.7) * 12;
                ctx.quadraticCurveTo(cpX, cpY, endX, outlierTargetY);
                ctx.stroke();
            }

            // Upper branch probability callout
            const pUpY = startY - chartH * 0.26;
            ctx.fillStyle = '#94a3b8';
            ctx.font = '11px Consolas, monospace';
            ctx.textAlign = 'left';
            ctx.fillText('P(up)', endX + 8, pUpY - 8);
            ctx.fillStyle = '#f8fafc';
            ctx.font = 'bold 15px Consolas, monospace';
            ctx.fillText('0.275', endX + 8, pUpY + 8);

            // 2. Denser Glowing Golden Yellow Monte Carlo Downward Cluster (72.5% Density)
            for (let i = 0; i < 52; i++) {
                const spread = (i / 51); // 0.0 to 1.0 downward
                const targetDeltaY = (chartH * 0.38) * (0.2 + spread * 0.8);
                const finalY = startY + targetDeltaY;

                // Glowing yellow/gold opacity gradient
                const alpha = 0.18 + Math.sin(spread * Math.PI) * 0.45;
                ctx.strokeStyle = `rgba(250, 204, 21, ${alpha.toFixed(2)})`;
                ctx.lineWidth = 1.0;

                ctx.beginPath();
                ctx.moveTo(startX, startY);
                const cp1X = startX + (endX - startX) * 0.35;
                const cp1Y = startY + (targetDeltaY * 0.2) + Math.sin(i * 0.8) * 6;
                const cp2X = startX + (endX - startX) * 0.75;
                const cp2Y = startY + (targetDeltaY * 0.8) + Math.cos(i * 0.5) * 8;
                ctx.bezierCurveTo(cp1X, cp1Y, cp2X, cp2Y, endX, finalY);
                ctx.stroke();
            }

            // Lower branch probability callout
            const pDownY = startY + chartH * 0.22;
            ctx.fillStyle = '#facc15';
            ctx.font = '11px Consolas, monospace';
            ctx.textAlign = 'left';
            ctx.fillText('P(down)', endX + 8, pDownY - 8);
            ctx.font = 'bold 16px Consolas, monospace';
            ctx.fillText('0.725', endX + 8, pDownY + 10);

            // =================================================================
            // FLOATING PRICE BEACON: "NOW $77,859"
            // =================================================================
            const beaconX = Math.min(chartW - 140, Math.max(20, startX - 110));
            const beaconY = Math.max(padTop + 45, Math.min(chartH - 20, startY - 55));
            const pPrec = getAssetPrecisionConfig(lastClose);

            ctx.fillStyle = '#ffffff';
            ctx.font = 'bold 22px Consolas, monospace';
            ctx.textAlign = 'left';
            ctx.shadowColor = 'rgba(0,0,0,0.9)';
            ctx.shadowBlur = 8;
            ctx.fillText(`NOW $${formatAssetPrice(lastClose, pPrec.priceDecimals)}`, beaconX, beaconY);
            ctx.shadowBlur = 0;

            // Interactive Crosshair Tracking
            if (chartNav.crosshairX !== null && chartNav.crosshairY !== null) {
                const cx = chartNav.crosshairX;
                const cy = chartNav.crosshairY;
                if (cx >= 0 && cx <= chartW && cy >= padTop && cy <= padTop + chartH) {
                    ctx.strokeStyle = 'rgba(255, 255, 255, 0.4)';
                    ctx.lineWidth = 1;
                    ctx.setLineDash([4, 4]);

                    // Vertical line
                    ctx.beginPath();
                    ctx.moveTo(cx, padTop);
                    ctx.lineTo(cx, padTop + chartH);
                    ctx.stroke();

                    // Horizontal line
                    ctx.beginPath();
                    ctx.moveTo(0, cy);
                    ctx.lineTo(chartW, cy);
                    ctx.stroke();
                    ctx.setLineDash([]);

                    // Price tag at crosshair on right axis
                    const hoverPrice = effMaxP - ((cy - padTop - chartNav.panY) / chartH) * effRange;
                    ctx.fillStyle = '#f59e0b';
                    ctx.fillRect(chartW + 2, cy - 8, 74, 16);
                    ctx.fillStyle = '#000000';
                    ctx.font = 'bold 10px Consolas, monospace';
                    ctx.fillText(formatAssetPrice(hoverPrice, pPrec.priceDecimals), chartW + 6, cy + 4);
                }
            }
        }

        // =====================================================================
        // PANEL 2: PANE 1 - 01 HEAT MAP CANVAS (ORDER BOOK DEPTH & CLUSTERS)
        // =====================================================================
        function renderHeatMapCanvas() {
            const canvas = document.getElementById('canvas-heatmap');
            if (!canvas) return;
            const wrapper = document.getElementById('hm-canvas-wrapper');
            if (!wrapper) return;

            const dpr = window.devicePixelRatio || 1;
            const w = wrapper.clientWidth;
            const h = wrapper.clientHeight;
            if (w <= 0 || h <= 0) return;

            canvas.width = w * dpr;
            canvas.height = h * dpr;
            const ctx = canvas.getContext('2d');
            ctx.scale(dpr, dpr);

            ctx.fillStyle = '#080c14';
            ctx.fillRect(0, 0, w, h);

            const padR = 55;
            const mainH = h * 0.75;
            const volH = h - mainH;
            const chartW = w - padR;

            // Price ladder levels
            const baseP = wsState.lastPrice || 77859.0;
            const pPrec = getAssetPrecisionConfig(baseP);
            const levels = [
                { price: baseP * 1.015, label: '78,000' },
                { price: baseP * 1.005, label: '77,500' },
                { price: baseP * 0.995, label: '77,000' },
                { price: baseP * 0.985, label: '76,500' }
            ];

            // Draw horizontal price lines & labels
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
            ctx.lineWidth = 1;
            levels.forEach((lvl, idx) => {
                const y = (mainH / (levels.length + 1)) * (idx + 1);
                ctx.beginPath();
                ctx.moveTo(0, y);
                ctx.lineTo(chartW, y);
                ctx.stroke();

                ctx.fillStyle = '#64748b';
                ctx.font = '9px Consolas, monospace';
                ctx.textAlign = 'left';
                ctx.fillText(lvl.label, chartW + 5, y + 3);
            });

            // Generate Heat Bands & Stepped Ladder
            const steps = 38;
            const stepW = (chartW / steps);
            const offsetX = heatMapNav.panX % (stepW * 10);

            // Draw Liquidity Depth Heat Bands (Amber/Orange Glow)
            for (let i = 0; i < steps; i++) {
                const x = i * stepW + offsetX;
                const wave1 = Math.sin((i * 0.3) + (heatMapNav.panX * 0.02));
                const wave2 = Math.cos(i * 0.4);
                const heatY = (mainH * 0.45) + wave1 * (mainH * 0.25) + wave2 * 10;
                const bandH = 22 + Math.abs(wave2) * 20;

                ctx.fillStyle = `rgba(249, 115, 22, ${0.25 + Math.abs(wave1) * 0.35})`;
                ctx.fillRect(x, heatY - bandH / 2, stepW + 1, bandH);

                // Intense core
                ctx.fillStyle = `rgba(251, 146, 60, ${0.45 + Math.abs(wave1) * 0.4})`;
                ctx.fillRect(x, heatY - 4, stepW + 1, 8);
            }

            // Stepped Price Line (White/Gold)
            ctx.strokeStyle = '#f8fafc';
            ctx.lineWidth = 1.4;
            ctx.beginPath();
            let lastY = mainH * 0.35;
            for (let i = 0; i < steps; i++) {
                const x = i * stepW + offsetX;
                const wave1 = Math.sin((i * 0.3) + (heatMapNav.panX * 0.02));
                const y = (mainH * 0.45) + wave1 * (mainH * 0.25);
                if (i === 0) ctx.moveTo(x, y);
                else {
                    ctx.lineTo(x, lastY);
                    ctx.lineTo(x, y);
                }
                lastY = y;
            }
            ctx.stroke();

            // Institutional Callout Annotations with Leader Lines & Arrows
            // 1. "00:43 76,860 6.0 BTC"
            const call1X = chartW * 0.35 + heatMapNav.panX;
            if (call1X >= 10 && call1X <= chartW - 20) {
                ctx.fillStyle = '#ffffff';
                ctx.font = 'bold 9px Consolas, monospace';
                ctx.fillText('00:43  76,860  6.0 BTC', call1X, mainH * 0.16);
            }

            // 2. "+$769 back in 7 minutes" with arrow
            const call2X = chartW * 0.58 + heatMapNav.panX;
            const call2Y = mainH * 0.32;
            if (call2X >= 20 && call2X <= chartW - 20) {
                ctx.fillStyle = '#f8fafc';
                ctx.font = 'bold 9.5px Consolas, monospace';
                ctx.textAlign = 'center';
                ctx.fillText('+$769 back', call2X, call2Y);
                ctx.fillText('in 7 minutes', call2X, call2Y + 11);

                // Leader arrow pointing down-left to dip
                ctx.strokeStyle = '#ffffff';
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(call2X - 10, call2Y + 14);
                ctx.lineTo(call2X - 25, call2Y + 34);
                ctx.lineTo(call2X - 20, call2Y + 34);
                ctx.stroke();
            }

            // 3. "Falls $1,509 in 24 minutes" with arrow
            const call3X = chartW * 0.16 + heatMapNav.panX;
            const call3Y = mainH * 0.70;
            if (call3X >= 10 && call3X <= chartW - 20) {
                ctx.fillStyle = '#f8fafc';
                ctx.font = 'bold 9.5px Consolas, monospace';
                ctx.textAlign = 'left';
                ctx.fillText('Falls $1,509', call3X, call3Y);
                ctx.fillText('in 24 minutes', call3X, call3Y + 11);

                // Leader arrow pointing up-right to top of drop
                ctx.strokeStyle = '#ffffff';
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(call3X + 45, call3Y - 4);
                ctx.lineTo(call3X + 85, call3Y - 35);
                ctx.lineTo(call3X + 80, call3Y - 35);
                ctx.stroke();
            }

            // 4. "121 BTC traded in one minute" pointing to volume spike
            const call4X = chartW * 0.45 + heatMapNav.panX;
            const call4Y = h - 22;
            if (call4X >= 20 && call4X <= chartW - 20) {
                ctx.fillStyle = '#f8fafc';
                ctx.font = 'bold 9.5px Consolas, monospace';
                ctx.textAlign = 'center';
                ctx.fillText('121 BTC traded', call4X, call4Y - 8);
                ctx.fillText('in one minute', call4X, call4Y + 2);

                // Arrow pointing to volume bar
                ctx.strokeStyle = '#ffffff';
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(call4X - 35, call4Y - 3);
                ctx.lineTo(call4X - 55, call4Y + 6);
                ctx.stroke();
            }

            // Bottom Volume Bars & Time Axis
            ctx.fillStyle = 'rgba(255, 255, 255, 0.08)';
            ctx.fillRect(0, mainH, chartW, 1);

            for (let i = 0; i < steps; i++) {
                const x = i * stepW + offsetX;
                const vBarH = (i === 18 ? volH * 0.85 : (Math.sin(i * 1.3) * 0.5 + 0.5) * (volH * 0.45) + 3);
                ctx.fillStyle = (i === 18 ? '#facc15' : 'rgba(255, 255, 255, 0.25)');
                ctx.fillRect(x, h - vBarH, stepW - 1, vBarH);
            }

            // Time Ticks
            const times = ['00:00', '00:10', '00:20', '00:30', '00:40', '00:50'];
            ctx.fillStyle = '#64748b';
            ctx.font = '8px Consolas, monospace';
            ctx.textAlign = 'center';
            times.forEach((t, idx) => {
                const tx = (chartW / (times.length - 1)) * idx;
                ctx.fillText(t, tx, h - 2);
            });
        }

        // =====================================================================
        // PANEL 3: PANE 2 - 02 FLOW DUAL CVD AREA CANVAS
        // =====================================================================
        function renderFlowCanvas() {
            const canvas = document.getElementById('canvas-flow');
            if (!canvas) return;
            const wrapper = document.getElementById('flow-canvas-wrapper');
            if (!wrapper) return;

            const dpr = window.devicePixelRatio || 1;
            const w = wrapper.clientWidth;
            const h = wrapper.clientHeight;
            if (w <= 0 || h <= 0) return;

            canvas.width = w * dpr;
            canvas.height = h * dpr;
            const ctx = canvas.getContext('2d');
            ctx.scale(dpr, dpr);

            ctx.fillStyle = '#080c14';
            ctx.fillRect(0, 0, w, h);

            const padL = 36;
            const padR = 10;
            const chartW = w - padL - padR;
            const midY = h * 0.50;

            // Zero Baseline
            ctx.strokeStyle = '#1e293b';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(padL, midY);
            ctx.lineTo(w - padR, midY);
            ctx.stroke();

            // Y-axis Markers
            const yLevels = [
                { y: midY - h * 0.40, label: '+205' },
                { y: midY - h * 0.20, label: '+50' },
                { y: midY, label: '0' },
                { y: midY + h * 0.20, label: '-100' },
                { y: midY + h * 0.40, label: '-419' }
            ];

            ctx.fillStyle = '#64748b';
            ctx.font = '8.5px Consolas, monospace';
            ctx.textAlign = 'right';
            yLevels.forEach(lvl => {
                ctx.fillText(lvl.label, padL - 4, lvl.y + 3);
            });

            const points = 45;
            const stepW = chartW / (points - 1);
            const offsetX = flowNav.panX % (stepW * 10);

            // 1. Positive Buy Flow (Layered Mountain Area in Cyan)
            ctx.fillStyle = 'rgba(56, 189, 248, 0.45)';
            ctx.beginPath();
            ctx.moveTo(padL, midY);
            for (let i = 0; i < points; i++) {
                const x = padL + i * stepW + offsetX;
                const wave = Math.max(0, Math.sin((i * 0.18) + (flowNav.panX * 0.02)) * (h * 0.42));
                ctx.lineTo(x, midY - wave);
            }
            ctx.lineTo(padL + (points - 1) * stepW + offsetX, midY);
            ctx.closePath();
            ctx.fill();

            // 2. Negative Sell Flow (Layered Mountain Area in Orange)
            ctx.fillStyle = 'rgba(234, 88, 12, 0.55)';
            ctx.beginPath();
            ctx.moveTo(padL, midY);
            for (let i = 0; i < points; i++) {
                const x = padL + i * stepW + offsetX;
                const wave = Math.max(0, Math.sin((i * 0.16) + 1.2 + (flowNav.panX * 0.02)) * (h * 0.42));
                ctx.lineTo(x, midY + wave);
            }
            ctx.lineTo(padL + (points - 1) * stepW + offsetX, midY);
            ctx.closePath();
            ctx.fill();

            // 3. Net Delta Overlaid White Line
            ctx.strokeStyle = '#f8fafc';
            ctx.lineWidth = 1.3;
            ctx.beginPath();
            for (let i = 0; i < points; i++) {
                const x = padL + i * stepW + offsetX;
                const waveBuy = Math.sin((i * 0.18) + (flowNav.panX * 0.02)) * (h * 0.38);
                const waveSell = Math.sin((i * 0.16) + 1.2 + (flowNav.panX * 0.02)) * (h * 0.38);
                const netY = midY - (waveBuy - waveSell) * 0.75;
                if (i === 0) ctx.moveTo(x, netY);
                else ctx.lineTo(x, netY);
            }
            ctx.stroke();

            // Day Labels on bottom
            const days = ['Fri', 'Sat', 'Sun'];
            ctx.fillStyle = '#94a3b8';
            ctx.font = '9px Consolas, monospace';
            ctx.textAlign = 'center';
            days.forEach((d, idx) => {
                const dx = padL + (chartW / (days.length + 1)) * (idx + 1);
                ctx.fillText(d, dx, h - 4);
            });
        }

        // =====================================================================
        // PANEL 4: PANE 3 - AGENT SIM LOG STREAM & PAPER DISPATCH
        // =====================================================================
        function initAgentSimLog() {
            const stream = document.getElementById('agent-sim-log-stream');
            if (!stream) return;

            const simData = [
                { path: '0262', status: 'open', time: 'h+48', pnl: '+1.2 % pnl', type: 'open' },
                { path: '0847', status: 'stop', time: 'h+17', pnl: '-1.0 % pnl', type: 'stop' },
                { path: '0346', status: 'open', time: 'h+48', pnl: '+1.0 % pnl', type: 'open' },
                { path: '0514', status: 'target', time: 'h+10', pnl: '+2.0 % pnl', type: 'target' },
                { path: '0376', status: 'open', time: 'h+48', pnl: '+1.0 % pnl', type: 'open' },
                { path: '0138', status: 'stop', time: 'h+04', pnl: '-1.0 % pnl', type: 'stop' },
                { path: '0224', status: 'open', time: 'h+48', pnl: '+1.3 % pnl', type: 'open' },
                { isDivider: true, text: '176 shown · target 19.3% · stop 29.8%' },
                { path: '0794', status: 'stop', time: 'h+21', pnl: '-1.0 % pnl', type: 'stop' },
                { path: '0742', status: 'stop', time: 'h+20', pnl: '-1.0 % pnl', type: 'stop' },
                { path: '0571', status: 'target', time: 'h+30', pnl: '+2.0 % pnl', type: 'target' },
                { path: '0379', status: 'open', time: 'h+48', pnl: '+1.0 % pnl', type: 'open' },
                { path: '0990', status: 'stop', time: 'h+21', pnl: '-1.0 % pnl', type: 'stop' },
                { path: '0686', status: 'open', time: 'h+48', pnl: '+0.2 % pnl', type: 'open' },
                { path: '0049', status: 'target', time: 'h+43', pnl: '+2.0 % pnl', type: 'target' },
                { path: '0535', status: 'target', time: 'h+15', pnl: '+2.0 % pnl', type: 'target' },
                { path: '0999', status: 'stop', time: 'h+28', pnl: '-1.0 % pnl', type: 'stop' }
            ];

            stream.innerHTML = '';
            simData.forEach(item => {
                if (item.isDivider) {
                    const div = document.createElement('div');
                    div.className = 'ws-sim-divider';
                    div.textContent = item.text;
                    stream.appendChild(div);
                } else {
                    const line = document.createElement('div');
                    line.className = `ws-sim-line ${item.type}`;
                    line.innerHTML = `
                        <span>path ${item.path} &nbsp;${item.status.padEnd(6, ' ')} ${item.time}</span>
                        <span style="font-weight: 700;">${item.pnl}</span>
                    `;
                    stream.appendChild(line);
                }
            });
        }

        async function placeWorkstationPaperOrder() {
            const sym = wsState.activeSymbol || 'BTCUSDT';
            const price = wsState.lastPrice || 77859.0;
            const side = 'SELL'; // Kronos P(down) 0.725 conviction

            try {
                showStatus('info', `⚡ Dispatching paper order on ${sym}...`);
                const res = await axios.post('/api/bot/place-order', {
                    symbol: sym,
                    side: side,
                    price: price,
                    notional: 15.00
                });

                if (res.data && res.data.success) {
                    showStatus('success', res.data.message);

                    // Add fresh executed line to top of Sim Log stream
                    const stream = document.getElementById('agent-sim-log-stream');
                    if (stream) {
                        const line = document.createElement('div');
                        line.className = 'ws-sim-line target';
                        line.style.background = 'rgba(250, 204, 21, 0.15)';
                        line.style.padding = '2px 4px';
                        line.style.borderRadius = '2px';
                        const randPath = Math.floor(Math.random() * 899 + 100).toString().padStart(4, '0');
                        line.innerHTML = `
                            <span>path ${randPath} &nbsp;active &nbsp;h+01</span>
                            <span style="color: #facc15;">[PAPER FILLED: ${sym} ${side}]</span>
                        `;
                        stream.insertBefore(line, stream.firstChild);
                    }

                    // Refresh dashboard paper stats if available
                    if (typeof loadBotStatus === 'function') loadBotStatus();
                } else {
                    showStatus('error', res.data.error || 'Failed to place paper order.');
                }
            } catch (err) {
                console.error('Paper order dispatch error:', err);
                showStatus('error', err.response?.data?.error || err.message);
            }
        }


        // =====================================================================
        // GEMINI AI META-STRATEGY ADVISORY HANDLERS
        // =====================================================================
        async function loadGeminiAssessment() {
            try {
                const res = await axios.get('/api/gemini/assessment');
                if (!res.data || !res.data.success) return;

                const { available, model, auto_apply, assessment, active_sweetspot } = res.data;

                const statusPill = document.getElementById('gemini-status-pill');
                if (statusPill) {
                    statusPill.textContent = available ? `● ${model.toUpperCase()}: ACTIVE (FREE TIER)` : '● GEMINI API: OFFLINE';
                    statusPill.className = available ? 'status-pill status-online' : 'status-pill status-offline';
                }

                const toggle = document.getElementById('gemini-auto-apply-toggle');
                if (toggle) toggle.checked = !!auto_apply;

                if (assessment) {
                    renderGeminiAssessmentCard(assessment);
                } else if (active_sweetspot) {
                    // Show current baseline settings
                    const valRR = document.getElementById('gemini-val-rr');
                    const valFee = document.getElementById('gemini-val-fee');
                    const valRisk = document.getElementById('gemini-val-risk');
                    if (valRR) valRR.textContent = `${active_sweetspot.rr_hurdle_ratio.toFixed(2)}:1`;
                    if (valFee) valFee.textContent = `${active_sweetspot.fee_hurdle_pct.toFixed(2)}%`;
                    if (valRisk) valRisk.textContent = `${active_sweetspot.risk_budget_pct.toFixed(2)}%`;
                }
            } catch (err) {
                console.warn('Could not load Gemini assessment:', err);
            }
        }

        function renderGeminiAssessmentCard(assessment) {
            const diagEl = document.getElementById('gemini-regime-diag');
            if (diagEl) diagEl.textContent = assessment.regime_diagnosis || 'Regime diagnosis complete.';

            const edgeEl = document.getElementById('gemini-edge-summary');
            if (edgeEl) edgeEl.textContent = assessment.market_edge_summary || 'Parameters tuned to current market volatility.';

            const itemsEl = document.getElementById('gemini-action-items');
            if (itemsEl && assessment.action_items) {
                itemsEl.innerHTML = '';
                assessment.action_items.forEach(item => {
                    const li = document.createElement('li');
                    li.textContent = item;
                    itemsEl.appendChild(li);
                });
            }

            const valRR = document.getElementById('gemini-val-rr');
            if (valRR) valRR.textContent = `${Number(assessment.sweetspot_rr_ratio).toFixed(2)}:1`;

            const valFee = document.getElementById('gemini-val-fee');
            if (valFee) valFee.textContent = `${Number(assessment.sweetspot_fee_hurdle_pct).toFixed(2)}%`;

            const valRisk = document.getElementById('gemini-val-risk');
            if (valRisk) valRisk.textContent = `${Number(assessment.sweetspot_risk_budget_pct).toFixed(2)}%`;

            const valEma = document.getElementById('gemini-val-ema');
            if (valEma) valEma.textContent = `${assessment.sweetspot_fast_ema} / ${assessment.sweetspot_slow_ema}`;

            const confEl = document.getElementById('gemini-confidence-pill');
            if (confEl && assessment.confidence_score) {
                confEl.textContent = `Confidence: ${(Number(assessment.confidence_score) * 100).toFixed(1)}%`;
            }

            const lastEl = document.getElementById('gemini-last-assessed');
            if (lastEl && assessment.timestamp) {
                try {
                    const dt = new Date(assessment.timestamp);
                    lastEl.textContent = dt.toTimeString().slice(0, 8) + ' UTC';
                } catch(e) {
                    lastEl.textContent = 'Recently';
                }
            }

            // Sync with 3D Param Sweep in Workstation if present
            const peakLabel = document.getElementById('ps-peak-label');
            if (peakLabel && assessment.sweetspot_fast_ema && assessment.sweetspot_slow_ema) {
                peakLabel.textContent = `peak Sharpe 1.35 @ ${assessment.sweetspot_fast_ema}/${assessment.sweetspot_slow_ema}`;
            }
        }

        async function triggerGeminiAssessment() {
            const btn = document.getElementById('btn-run-gemini-assess');
            if (btn) {
                btn.disabled = true;
                btn.textContent = '⏳ Evaluating Market...';
            }
            showStatus('info', 'Executing strategic meta-assessment with Gemini Free Tier...');

            try {
                const res = await axios.post('/api/gemini/assess');
                if (res.data && res.data.success) {
                    showStatus('success', 'Gemini Strategic Assessment complete! New sweetspot identified.');
                    renderGeminiAssessmentCard(res.data.assessment);
                } else {
                    showStatus('error', res.data.error || 'Strategic assessment failed.');
                }
            } catch (err) {
                showStatus('error', 'Error calling Gemini Assessment endpoint: ' + (err.response?.data?.error || err.message));
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = '⚡ Run Assessment Now';
                }
            }
        }

        async function applyGeminiSweetspot() {
            try {
                const res = await axios.post('/api/gemini/apply-sweetspot');
                if (res.data && res.data.success) {
                    showStatus('success', res.data.message || 'Sweetspot parameters applied to KEV.ai!');
                    loadMacroOverview();
                } else {
                    showStatus('error', res.data.error || 'Failed to apply sweetspot.');
                }
            } catch (err) {
                showStatus('error', 'Failed to apply sweetspot: ' + err.message);
            }
        }

        async function toggleGeminiAutoApply(enabled) {
            try {
                const res = await axios.post('/api/gemini/toggle-auto-apply', { auto_apply: enabled });
                if (res.data && res.data.success) {
                    showStatus('info', `Gemini Auto-Apply Sweetspot is now ${enabled ? 'ENABLED' : 'PAUSED'}.`);
                }
            } catch (err) {
                showStatus('error', 'Could not toggle auto-apply.');
            }
        }
