/**
 * webui/static/js/yearly_matrix.js
 * Renders the 1-Year Rolling Monthly AND Full-Month Daily (Nov, Dec, Jan...)
 * Asset Activity (Bought/Sold) & Profitability Heatmap Matrix at the bottom of #view-dashboard.
 */

(function () {
    let ymSource = localStorage.getItem("kronos_ym_source") || "live";
    if (ymSource === "paper") ymSource = "live";
    let ymTimeframe = localStorage.getItem("kronos_ym_timeframe") || "daily";      // "1y" | "daily" (default to daily)
    let ymSelectedMonth = localStorage.getItem("kronos_ym_month") || null;  // null -> auto current UTC month (Nov '26, Dec '26, ...)
    let ymMode = localStorage.getItem("kronos_ym_mode") || "both";         // "both" | "bs" | "pnl"
    let ymLastData = null;
    let ymIsLoading = false;

    function formatSignedUsd(valStr) {
        const num = parseFloat(valStr || "0");
        if (isNaN(num)) return "$0.00";
        if (num > 0) return `+$${num.toFixed(2)}`;
        if (num < 0) return `-$${Math.abs(num).toFixed(2)}`;
        return "$0.00";
    }

    function getHeatStyle(cell, maxAbsPnl, isSummaryCol) {
        if (!cell || cell.status === "empty" || cell.total === 0) {
            return { cls: "ym-pill ym-pill-empty", style: "" };
        }
        if (cell.status === "flat") {
            return { cls: "ym-pill ym-pill-flat", style: "" };
        }

        const pnl = parseFloat(cell.net_pnl || "0");
        const denom = Math.max(0.5, parseFloat(maxAbsPnl || "1"));
        const rawRatio = Math.min(1, Math.abs(pnl) / denom);
        const intensity = Math.sqrt(rawRatio);

        if (pnl > 0) {
            const alphaBg = isSummaryCol
                ? (0.18 + intensity * 0.34).toFixed(2)
                : (0.16 + intensity * 0.56).toFixed(2);
            const alphaBorder = (0.35 + intensity * 0.45).toFixed(2);
            const textColor = intensity > 0.55 ? "#f0fdf4" : "#4ade80";
            return {
                cls: "ym-pill",
                style: `background: rgba(22, 163, 74, ${alphaBg}); border: 1px solid rgba(34, 197, 94, ${alphaBorder}); color: ${textColor};`
            };
        } else {
            const alphaBg = isSummaryCol
                ? (0.18 + intensity * 0.34).toFixed(2)
                : (0.16 + intensity * 0.56).toFixed(2);
            const alphaBorder = (0.35 + intensity * 0.45).toFixed(2);
            const textColor = intensity > 0.55 ? "#fef2f2" : "#fb7185";
            return {
                cls: "ym-pill",
                style: `background: rgba(220, 38, 38, ${alphaBg}); border: 1px solid rgba(248, 81, 73, ${alphaBorder}); color: ${textColor};`
            };
        }
    }

    function buildCellHtml(cell, maxAbsPnl, label, bucketLabel, isSummaryCol) {
        const hs = getHeatStyle(cell, maxAbsPnl, isSummaryCol);
        if (!cell || cell.total === 0) {
            const title = `${label} · ${bucketLabel}: No trades executed`;
            return `<div class="${hs.cls}" title="${title}"><span class="ym-pill-primary">—</span></div>`;
        }

        const bsText = `${cell.buys}B/${cell.sells}S`;
        const pnlText = formatSignedUsd(cell.net_pnl);
        const tooltip =
            `${label} · ${bucketLabel}\n` +
            `Bought: ${cell.buys} | Sold: ${cell.sells} (Total: ${cell.total})\n` +
            `Gross PnL: ${formatSignedUsd(cell.gross_pnl)} | Fees: -$${Math.abs(parseFloat(cell.fees || "0")).toFixed(2)}\n` +
            `Net PnL: ${pnlText} (${cell.status === "profit" ? "PROFITABLE" : cell.status === "loss" ? "LOSS" : "FLAT"})`;

        let inner = "";
        if (ymMode === "bs") {
            inner = `<span class="ym-pill-primary">${bsText}</span>`;
        } else if (ymMode === "pnl") {
            inner = `<span class="ym-pill-primary">${pnlText}</span>`;
        } else {
            inner =
                `<span class="ym-pill-primary">${bsText}</span>` +
                `<span class="ym-pill-sub">${pnlText}</span>`;
        }

        return `<div class="${hs.cls}" style="${hs.style}" title="${tooltip.replace(/"/g, "&quot;")}">${inner}</div>`;
    }

    function syncMonthControls(data) {
        const dailyBtn = document.getElementById("ym-btn-daily");
        if (dailyBtn && data.current_month_label) {
            dailyBtn.textContent = `Daily (${data.current_month_label})`;
        }

        const sel = document.getElementById("ym-month-select");
        if (sel) {
            sel.style.display = ymTimeframe === "daily" ? "inline-block" : "none";
            const avail = data.available_months || [];
            if (avail.length > 0) {
                const activeVal = data.selected_month || data.current_month;
                const needsBuild = sel.options.length !== avail.length || (sel.options[0] && sel.options[0].value !== avail[0].key);
                if (needsBuild) {
                    sel.innerHTML = avail
                        .map((m) => `<option value="${m.key}">${m.label}${m.is_current ? " (Current)" : ""}</option>`)
                        .join("");
                }
                if (activeVal) {
                    sel.value = activeVal;
                }
            }
        }

        const titleEl = document.getElementById("ym-card-title");
        const subEl = document.getElementById("ym-card-subtitle");
        if (ymTimeframe === "daily") {
            if (titleEl) titleEl.textContent = `Daily asset returns & volume (${data.selected_month_label || data.current_month_label || ""})`;
            if (subEl) subEl.textContent = "Bought / Sold count per day · Green if profitable";
        } else {
            if (titleEl) titleEl.textContent = "Monthly asset returns & volume";
            if (subEl) subEl.textContent = "Bought / Sold count per month · Green if profitable (click any month for daily view)";
        }
    }

    function renderYearlyMatrix(data) {
        const container = document.getElementById("ym-table-container");
        const rangeEl = document.getElementById("ym-range-label");
        const summaryEl = document.getElementById("ym-footer-summary");
        if (!container || !data || !data.success) return;

        syncMonthControls(data);

        if (rangeEl) {
            const timeStr = new Date().toLocaleTimeString();
            rangeEl.innerHTML = `${data.range_label || ""} <span style="display:inline-block;margin-left:8px;padding:2px 7px;border-radius:4px;background:rgba(34,197,94,0.14);border:1px solid rgba(34,197,94,0.35);color:#4ade80;font-size:10px;font-weight:600;letter-spacing:0.4px;" title="Auto-refreshed via AWS Bridge">⚡ LIVE · ${timeStr}</span>`;
        }

        const isDaily = data.timeframe === "daily";
        const cols = data.months || [];
        const sumColLabel = data.summary_col_label || (isDaily ? "MTD" : "1Y");
        const maxAbs = data.max_abs_pnl || "1.00";
        const sumRow = data.summary_row;
        const rows = data.rows || [];

        let thead = `<thead><tr><th class="ym-col-asset">Asset</th>`;
        for (const col of cols) {
            const curCls = col.is_current ? "ym-th-current" : "";
            if (!isDaily) {
                thead += `<th class="${curCls} ym-th-clickable" onclick="openDailyMonth('${col.key}')" title="Open full daily report for ${col.label} ${col.short_year}">${col.label}</th>`;
            } else {
                thead += `<th class="${curCls}" title="${col.key}">${col.label}</th>`;
            }
        }
        thead += `<th class="ym-col-1y">${sumColLabel}</th></tr></thead>`;

        let tbody = `<tbody>`;

        // 1. Portfolio Summary Top Row
        if (sumRow) {
            tbody += `<tr class="ym-row-portfolio">`;
            tbody += `<td><div class="ym-asset-cell">${sumRow.label || "Portfolio"}</div></td>`;
            for (const col of cols) {
                const tdCls = col.is_current ? "ym-month-td ym-td-current" : "ym-month-td";
                const cell = (sumRow.months || {})[col.key];
                const bLbl = isDaily ? col.key : `${col.label} ${col.short_year}`;
                tbody += `<td class="${tdCls}">${buildCellHtml(cell, maxAbs, "Portfolio Total", bLbl, false)}</td>`;
            }
            tbody += `<td class="ym-td-1y">${buildCellHtml(sumRow.yearly, maxAbs, `Portfolio ${sumColLabel} Total`, sumColLabel, true)}</td>`;
            tbody += `</tr>`;
        }

        // 2. Individual Asset Rows
        if (rows.length === 0) {
            tbody += `<tr><td colspan="${cols.length + 2}" style="text-align:center;color:var(--text-muted);padding:20px;">No executed trades recorded in this period.</td></tr>`;
        } else {
            for (const r of rows) {
                tbody += `<tr>`;
                tbody += `<td><div class="ym-asset-cell" title="${r.symbol}">` +
                    `<span class="ym-asset-dot" style="background:${r.color};"></span>` +
                    `<span>${r.short_name}</span></div></td>`;
                for (const col of cols) {
                    const tdCls = col.is_current ? "ym-td-current" : "";
                    const cell = (r.months || {})[col.key];
                    const bLbl = isDaily ? col.key : `${col.label} ${col.short_year}`;
                    tbody += `<td class="${tdCls}">${buildCellHtml(cell, maxAbs, r.symbol, bLbl, false)}</td>`;
                }
                tbody += `<td class="ym-td-1y">${buildCellHtml(r.yearly, maxAbs, `${r.symbol} ${sumColLabel}`, sumColLabel, true)}</td>`;
                tbody += `</tr>`;
            }
        }

        tbody += `</tbody>`;
        const tableCls = isDaily ? "ym-table ym-table-daily" : "ym-table";
        container.innerHTML = `<table class="${tableCls}">${thead}${tbody}</table>`;

        // In daily view, smoothly scroll active/today column into clear view if needed
        if (isDaily) {
            const curTh = container.querySelector("th.ym-th-current");
            if (curTh && container.scrollWidth > container.clientWidth) {
                const targetScroll = Math.max(0, curTh.offsetLeft - container.clientWidth * 0.55);
                container.scrollLeft = targetScroll;
            }
        }

        if (summaryEl && sumRow && sumRow.yearly) {
            const y = sumRow.yearly;
            const netStr = formatSignedUsd(y.net_pnl);
            const netColor = parseFloat(y.net_pnl) >= 0 ? "#4ade80" : "#fb7185";
            summaryEl.innerHTML =
                `${sumColLabel} Total: <strong style="color:var(--text-primary);">${y.buys} Bought</strong> / ` +
                `<strong style="color:var(--text-primary);">${y.sells} Sold</strong> ` +
                `(${y.total} executions) · Net PnL: <strong style="color:${netColor};">${netStr}</strong>`;
        }
    }

    async function loadYearlyMatrix(forceRefresh) {
        const container = document.getElementById("ym-table-container");
        if (!container) return;
        if (forceRefresh) {
            container.style.opacity = "0.6";
        }
        try {
            let url = `/api/analytics/yearly-matrix?source=${encodeURIComponent(ymSource)}&timeframe=${encodeURIComponent(ymTimeframe)}`;
            if (ymTimeframe === "daily" && ymSelectedMonth) {
                url += `&month=${encodeURIComponent(ymSelectedMonth)}`;
            }
            if (forceRefresh) {
                url += "&refresh=true";
            }
            const resp = await fetch(url);
            const data = await resp.json();
            if (data && data.success) {
                ymLastData = data;
                renderYearlyMatrix(data);
            } else {
                container.innerHTML = `<div style="padding:18px;text-align:center;color:#fb7185;font-size:12px;">Unable to load asset report: ${(data && data.error) || "Unknown error"}</div>`;
            }
        } catch (err) {
            container.innerHTML = `<div style="padding:18px;text-align:center;color:var(--text-muted);font-size:12px;">Awaiting backend telemetry...</div>`;
        } finally {
            container.style.opacity = "1";
        }
    }

    window.setYearlyMatrixSource = function (src) {
        ymSource = src;
        try { localStorage.setItem("kronos_ym_source", src); } catch (e) {}
        document.querySelectorAll("[data-ym-source]").forEach((btn) => {
            btn.classList.toggle("active", btn.getAttribute("data-ym-source") === src);
        });
        loadYearlyMatrix(false);
    };

    window.setYearlyMatrixTimeframe = function (tf) {
        ymTimeframe = tf;
        try { localStorage.setItem("kronos_ym_timeframe", tf); } catch (e) {}
        if (tf === "daily" && !ymSelectedMonth && ymLastData && ymLastData.current_month) {
            ymSelectedMonth = ymLastData.current_month;
        }
        document.querySelectorAll("[data-ym-tf]").forEach((btn) => {
            btn.classList.toggle("active", btn.getAttribute("data-ym-tf") === tf);
        });
        loadYearlyMatrix(false);
    };

    window.setYearlyMatrixMonth = function (monthKey) {
        ymSelectedMonth = monthKey;
        ymTimeframe = "daily";
        try {
            localStorage.setItem("kronos_ym_month", monthKey);
            localStorage.setItem("kronos_ym_timeframe", "daily");
        } catch (e) {}
        document.querySelectorAll("[data-ym-tf]").forEach((btn) => {
            btn.classList.toggle("active", btn.getAttribute("data-ym-tf") === "daily");
        });
        loadYearlyMatrix(false);
    };

    window.openDailyMonth = function (monthKey) {
        window.setYearlyMatrixMonth(monthKey);
    };

    window.setYearlyMatrixMode = function (mode) {
        ymMode = mode;
        try { localStorage.setItem("kronos_ym_mode", mode); } catch (e) {}
        document.querySelectorAll("[data-ym-mode]").forEach((btn) => {
            btn.classList.toggle("active", btn.getAttribute("data-ym-mode") === mode);
        });
        if (ymLastData) {
            renderYearlyMatrix(ymLastData);
        }
    };

    window.refreshYearlyMatrix = function (force = true) {
        return loadYearlyMatrix(force);
    };

    document.addEventListener("DOMContentLoaded", function () {
        // Sync button states on load
        document.querySelectorAll("[data-ym-tf]").forEach((btn) => {
            btn.classList.toggle("active", btn.getAttribute("data-ym-tf") === ymTimeframe);
        });
        document.querySelectorAll("[data-ym-source]").forEach((btn) => {
            btn.classList.toggle("active", btn.getAttribute("data-ym-source") === ymSource);
        });
        document.querySelectorAll("[data-ym-mode]").forEach((btn) => {
            btn.classList.toggle("active", btn.getAttribute("data-ym-mode") === ymMode);
        });

        loadYearlyMatrix(false);

        // Auto-refresh every 12 seconds
        setInterval(function () {
            const dash = document.getElementById("view-dashboard");
            if (dash && dash.style.display !== "none") {
                loadYearlyMatrix(false);
            }
        }, 12000);

        // Instant refresh on tab/window focus
        document.addEventListener("visibilitychange", function () {
            if (!document.hidden) {
                loadYearlyMatrix(false);
            }
        });
        window.addEventListener("focus", function () {
            loadYearlyMatrix(false);
        });
    });
})();
