/**
 * webui/static/js/yearly_matrix.js
 * Renders the 1-Year Rolling Monthly Asset Activity (Bought/Sold) & Profitability Heatmap Matrix
 * at the bottom of the Kronos Dashboard (#view-dashboard).
 */

(function () {
    let ymSource = "live";
    let ymMode = "both"; // "both" | "bs" | "pnl"
    let ymLastData = null;

    function formatSignedUsd(valStr) {
        const num = parseFloat(valStr || "0");
        if (isNaN(num)) return "$0.00";
        if (num > 0) return `+$${num.toFixed(2)}`;
        if (num < 0) return `-$${Math.abs(num).toFixed(2)}`;
        return "$0.00";
    }

    /**
     * Intensity-scaled green/red heatmap pill colors matching institutional dark UI.
     * Green when net_pnl > 0 (profitable), red when net_pnl < 0 (loss).
     */
    function getHeatStyle(cell, maxAbsPnl, isYearly) {
        if (!cell || cell.status === "empty" || cell.total === 0) {
            return { cls: "ym-pill ym-pill-empty", style: "" };
        }
        if (cell.status === "flat") {
            return { cls: "ym-pill ym-pill-flat", style: "" };
        }

        const pnl = parseFloat(cell.net_pnl || "0");
        const denom = Math.max(0.5, parseFloat(maxAbsPnl || "1"));
        // Nonlinear sqrt scaling so smaller real profits/losses still show crisp gradation
        const rawRatio = Math.min(1, Math.abs(pnl) / denom);
        const intensity = Math.sqrt(rawRatio);

        if (pnl > 0) {
            // Profitable -> Emerald Green scale
            const alphaBg = isYearly
                ? (0.18 + intensity * 0.34).toFixed(2)
                : (0.16 + intensity * 0.56).toFixed(2);
            const alphaBorder = (0.35 + intensity * 0.45).toFixed(2);
            const textColor = intensity > 0.55 ? "#f0fdf4" : "#4ade80";
            return {
                cls: "ym-pill",
                style: `background: rgba(22, 163, 74, ${alphaBg}); border: 1px solid rgba(34, 197, 94, ${alphaBorder}); color: ${textColor};`
            };
        } else {
            // Unprofitable -> Crimson Red scale
            const alphaBg = isYearly
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

    function buildCellHtml(cell, maxAbsPnl, label, monthLabel, isYearly) {
        const hs = getHeatStyle(cell, maxAbsPnl, isYearly);
        if (!cell || cell.total === 0) {
            const title = `${label} · ${monthLabel}: No trades executed`;
            return `<div class="${hs.cls}" title="${title}"><span class="ym-pill-primary">—</span></div>`;
        }

        const bsText = `${cell.buys}B/${cell.sells}S`;
        const pnlText = formatSignedUsd(cell.net_pnl);
        const tooltip =
            `${label} · ${monthLabel}\n` +
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

    function renderYearlyMatrix(data) {
        const container = document.getElementById("ym-table-container");
        const rangeEl = document.getElementById("ym-range-label");
        const summaryEl = document.getElementById("ym-footer-summary");
        if (!container || !data || !data.success) return;

        if (rangeEl) {
            rangeEl.textContent = data.range_label || "12-month rolling";
        }

        const months = data.months || [];
        const maxAbs = data.max_abs_pnl || "1.00";
        const sumRow = data.summary_row;
        const rows = data.rows || [];

        let thead = `<thead><tr><th class="ym-col-asset">Asset</th>`;
        for (const m of months) {
            const thCls = m.is_current ? "ym-th-current" : "";
            thead += `<th class="${thCls}">${m.label}</th>`;
        }
        thead += `<th class="ym-col-1y">1Y</th></tr></thead>`;

        let tbody = `<tbody>`;

        // 1. Portfolio Summary Top Row (mirrors "Model" top row in reference)
        if (sumRow) {
            tbody += `<tr class="ym-row-portfolio">`;
            tbody += `<td><div class="ym-asset-cell">${sumRow.label || "Portfolio"}</div></td>`;
            for (const m of months) {
                const tdCls = m.is_current ? "ym-month-td ym-td-current" : "ym-month-td";
                const cell = (sumRow.months || {})[m.key];
                tbody += `<td class="${tdCls}">${buildCellHtml(cell, maxAbs, "Portfolio Total", `${m.label} ${m.short_year}`, false)}</td>`;
            }
            tbody += `<td class="ym-td-1y">${buildCellHtml(sumRow.yearly, maxAbs, "Portfolio 1Y Total", "1Y", true)}</td>`;
            tbody += `</tr>`;
        }

        // 2. Individual Asset Rows
        if (rows.length === 0) {
            tbody += `<tr><td colspan="${months.length + 2}" style="text-align:center;color:var(--text-muted);padding:20px;">No executed trades recorded in this source for the last 12 months.</td></tr>`;
        } else {
            for (const r of rows) {
                tbody += `<tr>`;
                tbody += `<td><div class="ym-asset-cell" title="${r.symbol}">` +
                    `<span class="ym-asset-dot" style="background:${r.color};"></span>` +
                    `<span>${r.short_name}</span></div></td>`;
                for (const m of months) {
                    const tdCls = m.is_current ? "ym-td-current" : "";
                    const cell = (r.months || {})[m.key];
                    tbody += `<td class="${tdCls}">${buildCellHtml(cell, maxAbs, r.symbol, `${m.label} ${m.short_year}`, false)}</td>`;
                }
                tbody += `<td class="ym-td-1y">${buildCellHtml(r.yearly, maxAbs, `${r.symbol} 1Y`, "1Y", true)}</td>`;
                tbody += `</tr>`;
            }
        }

        tbody += `</tbody>`;
        container.innerHTML = `<table class="ym-table">${thead}${tbody}</table>`;

        if (summaryEl && sumRow && sumRow.yearly) {
            const y = sumRow.yearly;
            const netStr = formatSignedUsd(y.net_pnl);
            const netColor = parseFloat(y.net_pnl) >= 0 ? "#4ade80" : "#fb7185";
            summaryEl.innerHTML =
                `1Y Total: <strong style="color:var(--text-primary);">${y.buys} Bought</strong> / ` +
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
            const url = `/api/analytics/yearly-matrix?source=${encodeURIComponent(ymSource)}${forceRefresh ? "&refresh=true" : ""}`;
            const resp = await fetch(url);
            const data = await resp.json();
            if (data && data.success) {
                ymLastData = data;
                renderYearlyMatrix(data);
            } else {
                container.innerHTML = `<div style="padding:18px;text-align:center;color:#fb7185;font-size:12px;">Unable to load 1-year report: ${(data && data.error) || "Unknown error"}</div>`;
            }
        } catch (err) {
            container.innerHTML = `<div style="padding:18px;text-align:center;color:var(--text-muted);font-size:12px;">Awaiting backend telemetry...</div>`;
        } finally {
            container.style.opacity = "1";
        }
    }

    window.setYearlyMatrixSource = function (src) {
        ymSource = src;
        document.querySelectorAll("[data-ym-source]").forEach((btn) => {
            btn.classList.toggle("active", btn.getAttribute("data-ym-source") === src);
        });
        loadYearlyMatrix(false);
    };

    window.setYearlyMatrixMode = function (mode) {
        ymMode = mode;
        document.querySelectorAll("[data-ym-mode]").forEach((btn) => {
            btn.classList.toggle("active", btn.getAttribute("data-ym-mode") === mode);
        });
        if (ymLastData) {
            renderYearlyMatrix(ymLastData);
        }
    };

    window.refreshYearlyMatrix = function () {
        loadYearlyMatrix(true);
    };

    document.addEventListener("DOMContentLoaded", function () {
        loadYearlyMatrix(false);
        // Auto-refresh quietly every 90 seconds
        setInterval(function () {
            const dash = document.getElementById("view-dashboard");
            if (dash && dash.style.display !== "none") {
                loadYearlyMatrix(false);
            }
        }, 90000);
    });
})();
