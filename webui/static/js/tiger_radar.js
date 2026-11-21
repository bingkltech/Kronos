/**
 * ============================================================================
 * STALKING TIGER — MICROSTRUCTURAL PREY RADAR (CANVAS & AUDIO ENGINE)
 * Author: Kronos Lead Trade Quant Designer
 * Purpose: 60 FPS real-time radar with Bézier tentacles, lightning discharges,
 *          dynamic 30s Binance sonar sweep, and pop-in/pop-out hysteresis.
 * ============================================================================
 */

(function () {
    'use strict';

    // ------------------------------------------------------------------------
    // 1. PURE WEB AUDIO SYNTHESIZER (Zero external audio files)
    // ------------------------------------------------------------------------
    class TigerAudioSynthesizer {
        constructor() {
            this.ctx = null;
            this.isMuted = true; // Muted by default per quant cockpit standard
        }

        initContext() {
            if (!this.ctx) {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                if (AudioCtx) {
                    this.ctx = new AudioCtx();
                }
            }
            if (this.ctx && this.ctx.state === 'suspended') {
                this.ctx.resume();
            }
        }

        toggleMute() {
            this.initContext();
            this.isMuted = !this.isMuted;
            return !this.isMuted;
        }

        playSonarPing() {
            if (this.isMuted || !this.ctx) return;
            try {
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                osc.type = 'sine';
                const now = this.ctx.currentTime;
                osc.frequency.setValueAtTime(520, now);
                osc.frequency.exponentialRampToValueAtTime(1040, now + 0.12);
                gain.gain.setValueAtTime(0.06, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
                osc.connect(gain);
                gain.connect(this.ctx.destination);
                osc.start(now);
                osc.stop(now + 0.36);
            } catch (e) { }
        }

        playLightningCrack() {
            if (this.isMuted || !this.ctx) return;
            try {
                const now = this.ctx.currentTime;
                const bufferSize = this.ctx.sampleRate * 0.12;
                const buffer = this.ctx.createBuffer(1, bufferSize, this.ctx.sampleRate);
                const data = buffer.getChannelData(0);
                for (let i = 0; i < bufferSize; i++) {
                    data[i] = (Math.random() * 2 - 1) * Math.exp(-i / (bufferSize * 0.25));
                }
                const noise = this.ctx.createBufferSource();
                noise.buffer = buffer;
                const filter = this.ctx.createBiquadFilter();
                filter.type = 'bandpass';
                filter.frequency.setValueAtTime(1800, now);
                filter.Q.setValueAtTime(3.0, now);
                const gain = this.ctx.createGain();
                gain.gain.setValueAtTime(0.09, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.12);
                noise.connect(filter);
                filter.connect(gain);
                gain.connect(this.ctx.destination);
                noise.start(now);
            } catch (e) { }
        }

        playPopIn() {
            if (this.isMuted || !this.ctx) return;
            try {
                const now = this.ctx.currentTime;
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                osc.type = 'triangle';
                osc.frequency.setValueAtTime(380, now);
                osc.frequency.exponentialRampToValueAtTime(840, now + 0.18);
                gain.gain.setValueAtTime(0.08, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);
                osc.connect(gain);
                gain.connect(this.ctx.destination);
                osc.start(now);
                osc.stop(now + 0.26);
            } catch (e) { }
        }

        playPopOut() {
            if (this.isMuted || !this.ctx) return;
            try {
                const now = this.ctx.currentTime;
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                osc.type = 'sine';
                osc.frequency.setValueAtTime(600, now);
                osc.frequency.exponentialRampToValueAtTime(180, now + 0.22);
                gain.gain.setValueAtTime(0.05, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.28);
                osc.connect(gain);
                gain.connect(this.ctx.destination);
                osc.start(now);
                osc.stop(now + 0.29);
            } catch (e) { }
        }
    }

    // ------------------------------------------------------------------------
    // 2. RADAR GRAPHICS & PHYSICS ENGINE
    // ------------------------------------------------------------------------
    class TigerRadarEngine {
        constructor(canvasId, audioSynth) {
            this.canvas = document.getElementById(canvasId);
            if (!this.canvas) return;
            this.ctx = this.canvas.getContext('2d');
            this.audio = audioSynth;

            this.width = 0;
            this.height = 0;
            this.centerX = 0;
            this.centerY = 0;
            this.maxRadius = 0;

            // Telemetry state
            this.activePrey = [];
            this.quarantinedSymbols = ['ETHUSDT', 'SOLUSDT'];
            this.selectedPrey = null;
            this.hoveredNode = null;
            this.lastKnownSymbols = new Set();
            this.lastKnownPreyMap = new Map();
            this.lastStagnationState = new Map();

            // Dynamic animations
            this.sonarAngle = 0; // 0 to 2*PI, 30s cycle
            this.sweepDurationSec = 30.0;
            this.particles = [];
            this.lightningBolts = [];
            this.shimmerEffects = [];
            this.despawningNodes = []; // Nodes fading out

            // Core state
            this.wsTicks = 0;
            this.lastWsTicks = 0;
            this.corePulse = 0;
            this.coreState = 'STALKING'; // 'STALKING', 'POUNCE_READY', 'POUNCING'

            // Interactive Pan & Zoom Camera
            this.camX = 0;
            this.camY = 0;
            this.camZoom = 1.0;
            this.minZoom = 0.65;
            this.maxZoom = 2.4;
            this.isPanning = false;
            this.didPanDrag = false;
            this.panStartX = 0;
            this.panStartY = 0;
            this.camStartX = 0;
            this.camStartY = 0;

            this.animFrameId = null;
            this.lastTimestamp = performance.now();

            this.initCanvasSize();
            this.bindEvents();
            this.startLoop();
        }

        initCanvasSize() {
            if (!this.canvas || !this.canvas.parentElement) return;
            const rect = this.canvas.parentElement.getBoundingClientRect();
            const dpr = window.devicePixelRatio || 1;
            const nextW = rect.width > 40 ? rect.width : 700;
            const nextH = rect.height > 40 ? rect.height : 560;
            this.width = nextW;
            this.height = nextH;
            this.canvas.width = Math.round(this.width * dpr);
            this.canvas.height = Math.round(this.height * dpr);
            this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

            this.centerX = this.width / 2;
            this.centerY = this.height / 2;
            this.maxRadius = Math.min(this.centerX, this.centerY) * 0.80;
        }

        screenToWorld(sx, sy) {
            return {
                x: (sx - this.centerX - this.camX) / this.camZoom + this.centerX,
                y: (sy - this.centerY - this.camY) / this.camZoom + this.centerY
            };
        }

        updateZoomReadout() {
            const el = document.getElementById('tigerZoomReadout');
            if (el) el.textContent = `${Math.round(this.camZoom * 100)}%`;
        }

        setZoom(newZoom, pivotX, pivotY) {
            const clamped = Math.max(this.minZoom, Math.min(this.maxZoom, newZoom));
            const px = (pivotX !== undefined) ? pivotX : this.centerX;
            const py = (pivotY !== undefined) ? pivotY : this.centerY;

            const before = this.screenToWorld(px, py);
            this.camZoom = clamped;
            const afterX = (before.x - this.centerX) * this.camZoom + this.centerX + this.camX;
            const afterY = (before.y - this.centerY) * this.camZoom + this.centerY + this.camY;
            this.camX += px - afterX;
            this.camY += py - afterY;
            this.updateZoomReadout();
        }

        resetCamera() {
            this.camX = 0;
            this.camY = 0;
            this.camZoom = 1.0;
            this.updateZoomReadout();
        }

        bindEvents() {
            window.addEventListener('resize', () => {
                this.initCanvasSize();
            });

            this.canvas.addEventListener('mousedown', (e) => {
                if (e.button !== 0) return;
                this.isPanning = true;
                this.didPanDrag = false;
                this.panStartX = e.clientX;
                this.panStartY = e.clientY;
                this.camStartX = this.camX;
                this.camStartY = this.camY;
            });

            window.addEventListener('mousemove', (e) => {
                if (!this.isPanning) return;
                const dx = e.clientX - this.panStartX;
                const dy = e.clientY - this.panStartY;
                if (Math.abs(dx) > 4 || Math.abs(dy) > 4) {
                    this.didPanDrag = true;
                }
                if (this.didPanDrag) {
                    this.camX = this.camStartX + dx;
                    this.camY = this.camStartY + dy;
                    const tooltip = document.getElementById('tigerTooltip');
                    if (tooltip) tooltip.style.display = 'none';
                }
            });

            window.addEventListener('mouseup', () => {
                this.isPanning = false;
            });

            this.canvas.addEventListener('wheel', (e) => {
                e.preventDefault();
                const rect = this.canvas.getBoundingClientRect();
                const mx = e.clientX - rect.left;
                const my = e.clientY - rect.top;
                const factor = e.deltaY < 0 ? 1.12 : 0.89;
                this.setZoom(this.camZoom * factor, mx, my);
            }, { passive: false });

            this.canvas.addEventListener('dblclick', () => {
                this.resetCamera();
            });

            this.canvas.addEventListener('mousemove', (e) => {
                if (this.isPanning && this.didPanDrag) return;
                const rect = this.canvas.getBoundingClientRect();
                const mouseX = e.clientX - rect.left;
                const mouseY = e.clientY - rect.top;
                this.handleMouseMove(mouseX, mouseY, e.clientX, e.clientY);
            });

            this.canvas.addEventListener('mouseleave', () => {
                this.hoveredNode = null;
                const tooltip = document.getElementById('tigerTooltip');
                if (tooltip) tooltip.style.display = 'none';
            });

            this.canvas.addEventListener('click', (e) => {
                if (this.didPanDrag) {
                    this.didPanDrag = false;
                    return;
                }
                if (this.hoveredNode) {
                    this.selectedPrey = this.hoveredNode.symbol;
                    this.triggerLightningDischarge(this.hoveredNode);
                    if (window.onTigerPreySelected) {
                        window.onTigerPreySelected(this.hoveredNode);
                    }
                }
            });
        }

        handleMouseMove(mx, my, clientX, clientY) {
            const tooltip = document.getElementById('tigerTooltip');
            const world = this.screenToWorld(mx, my);
            const wx = world.x;
            const wy = world.y;
            let found = null;

            // Check prey nodes in world space
            for (const prey of this.activePrey) {
                if (!prey._x || !prey._y) continue;
                const dx = wx - prey._x;
                const dy = wy - prey._y;
                const hitRadius = (prey._radius || 18) + 8;
                if (dx * dx + dy * dy <= hitRadius * hitRadius) {
                    found = prey;
                    break;
                }
            }

            // Check quarantined nodes in world space
            if (!found) {
                for (const q of (this.quarantineNodes || [])) {
                    const dx = wx - q.x;
                    const dy = wy - q.y;
                    if (dx * dx + dy * dy <= 18 * 18) {
                        found = {
                            symbol: q.symbol,
                            is_quarantined: true,
                            reason: 'Negative Expectancy Quarantine (Rule #49)'
                        };
                        break;
                    }
                }
            }

            this.hoveredNode = found;

            if (found && tooltip) {
                tooltip.style.display = 'block';
                tooltip.style.left = `${clientX + 14}px`;
                tooltip.style.top = `${clientY + 14}px`;

                if (found.is_quarantined) {
                    tooltip.innerHTML = `
                        <div style="color: #ff2255; font-weight: 900; font-size: 13px;">⛔ ${found.symbol} [QUARANTINED]</div>
                        <div style="font-size: 10px; color: #8b949e; margin-top: 4px;">Disqualified from Top-5 Hunting</div>
                        <div style="color: #ffd700; font-size: 10px; margin-top: 2px;">${found.reason || 'Capital Recycler Veto'}</div>
                    `;
                } else {
                    const chg = parseFloat(found.price_change_pct || 0);
                    const chgColor = chg >= 0 ? '#00ff88' : '#ff2255';
                    const turnover = parseFloat(found.turnover_24h_usd || 0);
                    const turnoverStr = turnover >= 1e6 ? `$${(turnover / 1e6).toFixed(1)}M` : `$${turnover.toLocaleString()}`;
                    const doi = parseFloat(found.delta_oi_pct || 0);

                    const strPct = found.dynamic_strength_pct !== undefined ? Math.round(found.dynamic_strength_pct) : 100;
                    let strColor = '#00f0ff';
                    if (strPct < 45) strColor = '#ff3366';
                    else if (strPct < 75) strColor = '#ffd700';

                    const stagStatus = found.stagnation_status || 'ACTIVE';
                    const dwellSec = Math.round(found.elapsed_seconds || 0);
                    const retPct = Math.round(parseFloat(found.retention_ratio_pct || (found.retention_ratio ? found.retention_ratio * 100 : 100)));

                    const isScouted = (found.rank <= 2 && turnover >= 50000000 && !found.is_quarantined);
                    const cvdZ = found.cvd_zscore !== undefined ? found.cvd_zscore : '0.0';
                    const microSkew = found.micro_skew_bps !== undefined ? found.micro_skew_bps : '0.0';
                    const ofiScore = found.ofi_score !== undefined ? found.ofi_score : '0.0';
                    const absSig = (found.absorption_signal && found.absorption_signal !== 'NONE') ? found.absorption_signal : 'NONE';
                    const absSigColor = absSig === 'BUY' ? '#00ff88' : (absSig === 'SELL' ? '#ff2255' : '#8b949e');

                    tooltip.innerHTML = `
                        <div style="display: flex; justify-content: space-between; gap: 10px;">
                            <span style="font-weight: 900; font-size: 13px; color: #00f0ff;">#${found.rank} ${found.symbol}</span>
                            <span style="color: ${chgColor}; font-weight: 800;">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</span>
                        </div>
                        <div style="margin-top: 6px; font-size: 11px; line-height: 1.5;">
                            <div>Price: <b style="color: #fff;">$${found.last_price}</b></div>
                            <div>Turnover: <b style="color: #ffd700;">${turnoverStr}</b></div>
                            <div>Vol Score: <b style="color: #bd00ff;">${parseFloat(found.volatility_score || 0).toFixed(4)}</b></div>
                            <div>ΔOI: <b style="color: ${doi >= 0 ? '#00ff88' : '#ff2255'};">${doi.toFixed(2)}%</b></div>
                            <div>CVD Z-Score: <b style="color: #00e5ff;">${cvdZ}σ</b> · Skew: <b style="color: #ffd700;">${microSkew} bps</b></div>
                            <div>Absorption Climax: <b style="color: ${absSigColor};">${absSig}</b> · OFI: <b>${ofiScore}</b></div>
                            <div style="color: ${strColor}; margin-top: 3px;">Dynamic Str: <b>${strPct}%</b> (${stagStatus})</div>
                            <div style="color: #8b949e; font-size: 10px;">Dwell: <b>${dwellSec}s</b> · Retention: <b>${retPct}%</b></div>
                            <div>Stalk Score: <b style="color: #00f0ff;">${(found._stalkScore || 0.85).toFixed(2)}</b></div>
                            ${isScouted ? '<div style="color: #ff9800; font-weight: 800; margin-top: 5px; font-size: 10px; border-top: 1px dashed rgba(255,152,0,0.4); padding-top: 3px;">⚡ RELAYED TO MACRO RECONNAISSANCE BRIDGE</div>' : ''}
                        </div>
                    `;
                }
            } else if (tooltip) {
                tooltip.style.display = 'none';
            }
        }

        // --------------------------------------------------------------------
        // DATA INGESTION & HYSTERESIS DETECTOR
        // --------------------------------------------------------------------
        updateTelemetry(radarData) {
            if (!radarData) return;

            const newPreyList = radarData.active_prey || [];
            const newSymbols = new Set(newPreyList.map(p => p.symbol));

            // Detect Pop-Ins (Newly qualified assets)
            for (const p of newPreyList) {
                if (!this.lastKnownSymbols.has(p.symbol)) {
                    this.onPreyPopIn(p);
                } else {
                    // Check for Stagnation status changes
                    const prevStatus = this.lastStagnationState.get(p.symbol) || 'ACTIVE';
                    const currStatus = p.stagnation_status || 'ACTIVE';
                    if (currStatus !== prevStatus && (currStatus === 'STAGNANT_1' || currStatus === 'STAGNANT_2')) {
                        const strPct = p.dynamic_strength_pct !== undefined ? Math.round(p.dynamic_strength_pct) : 100;
                        this.addTapeLog('STAGNANT', `${p.symbol} waning: strength fell to ${strPct}% (${currStatus})`);
                    }
                }
                this.lastStagnationState.set(p.symbol, p.stagnation_status || 'ACTIVE');
                this.lastKnownPreyMap.set(p.symbol, { ...p });
            }

            // Detect Pop-Outs (Disqualified or Evicted assets decaying)
            for (const sym of this.lastKnownSymbols) {
                if (!newSymbols.has(sym)) {
                    this.onPreyPopOut(sym);
                }
            }

            this.lastKnownSymbols = newSymbols;
            this.wsTicks = radarData.ws_ticks || 0;
            if (radarData.quarantined_symbols) {
                this.quarantinedSymbols = radarData.quarantined_symbols;
            }

            // Map Prey onto polar radar coordinates
            const count = newPreyList.length;
            const updated = [];

            newPreyList.forEach((p, idx) => {
                // Stalk Score S derived from Volatility & Rank (0.50 to 0.95)
                const vol = Math.min(1.0, parseFloat(p.volatility_score || 0.5));
                const rankWeight = 1.0 - (p.rank - 1) * 0.12;
                const stalkScore = Math.max(0.3, Math.min(0.95, (vol * 0.5 + rankWeight * 0.5)));

                // Inverted Radius: Higher stalk score = tighter to center
                // r = Rmax * (1 - S * 0.85)
                const targetR = this.maxRadius * (1.0 - stalkScore * 0.78);

                // Fixed angular sector with slight offset
                const angle = (idx / Math.max(count, 1)) * Math.PI * 2 - Math.PI / 2 + 0.2;

                const existing = this.activePrey.find(item => item.symbol === p.symbol);
                const currentScale = existing ? existing._scale : 0.0;
                const spawnTimer = existing ? existing._spawnTimer : 1.0;

                updated.push({
                    ...p,
                    _targetR: targetR,
                    _r: existing ? existing._r + (targetR - existing._r) * 0.15 : targetR,
                    _angle: angle,
                    _stalkScore: stalkScore,
                    _scale: Math.min(1.0, currentScale + 0.08),
                    _spawnTimer: Math.max(0, spawnTimer - 0.05),
                    _tentaclePhase: (idx * 1.618),
                    _lastCvdZ: parseFloat(radarData.btc_cvd_zscore || 0)
                });
            });

            this.activePrey = updated;

            // Trigger spontaneous lightning discharge on high CVD / OFI activity
            const cvdZ = Math.abs(parseFloat(radarData.btc_cvd_zscore || 0));
            if (cvdZ >= 1.5 && Math.random() < 0.6 && this.activePrey.length > 0) {
                const target = this.activePrey[Math.floor(Math.random() * this.activePrey.length)];
                this.triggerLightningDischarge(target);
            }
        }

        onPreyPopIn(prey) {
            this.audio.playPopIn();
            this.addTapeLog('POPIN', `${prey.symbol} qualified ($${(parseFloat(prey.turnover_24h_usd) / 1e6).toFixed(1)}M turnover)`);
            // Flash expanding plasma ring
            this.shimmerEffects.push({
                symbol: prey.symbol,
                x: this.centerX,
                y: this.centerY,
                radius: 10,
                maxRadius: this.maxRadius * 0.8,
                alpha: 1.0,
                color: '#00f0ff'
            });
        }

        onPreyPopOut(symbol) {
            this.audio.playPopOut();
            const prev = this.lastKnownPreyMap.get(symbol);
            if (prev && (prev.stagnation_status === 'STAGNANT_2' || (prev.dynamic_strength_pct !== undefined && prev.dynamic_strength_pct < 45))) {
                const strPct = prev.dynamic_strength_pct !== undefined ? Math.round(prev.dynamic_strength_pct) : 0;
                this.addTapeLog('EVICT', `${symbol} evicted (stagnant/exhausted: ${strPct}% STR)`);
            } else if (prev) {
                this.addTapeLog('SWAP', `${symbol} swapped out for higher-opportunity asset`);
            } else {
                this.addTapeLog('POPOUT', `${symbol} dropped from Top-5 (momentum decay)`);
            }

            // Find dying prey coordinates to shatter into embers
            const dead = this.activePrey.find(p => p.symbol === symbol);
            if (dead && dead._x && dead._y) {
                for (let i = 0; i < 16; i++) {
                    const angle = Math.random() * Math.PI * 2;
                    const speed = 1.0 + Math.random() * 3.5;
                    this.particles.push({
                        x: dead._x,
                        y: dead._y,
                        vx: Math.cos(angle) * speed,
                        vy: Math.sin(angle) * speed,
                        alpha: 1.0,
                        decay: 0.025 + Math.random() * 0.03,
                        color: Math.random() > 0.5 ? '#ff2255' : '#ffd700',
                        size: 2.5 + Math.random() * 2.5
                    });
                }
            }
        }

        addTapeLog(tag, msg) {
            const feed = document.getElementById('tigerTapeFeed');
            if (!feed) return;
            const now = new Date();
            const timeStr = now.toISOString().slice(11, 19);
            const entry = document.createElement('div');
            entry.className = 'tiger-tape-entry';
            let tagClass = 'tiger-tape-tag-ws';
            if (tag === 'POPIN') tagClass = 'tiger-tape-tag-popin';
            if (tag === 'POPOUT') tagClass = 'tiger-tape-tag-popout';
            if (tag === 'CVD') tagClass = 'tiger-tape-tag-cvd';
            if (tag === 'SCAN') tagClass = 'tiger-tape-tag-scan';
            if (tag === 'STAGNANT') tagClass = 'tiger-tape-tag-stagnant';
            if (tag === 'EVICT') tagClass = 'tiger-tape-tag-evict';
            if (tag === 'SWAP') tagClass = 'tiger-tape-tag-swap';

            entry.innerHTML = `
                <span class="tiger-tape-time">${timeStr}</span>
                <span class="tiger-tape-tag ${tagClass}">[${tag}]</span>
                <span class="tiger-tape-msg">${msg}</span>
            `;
            feed.insertBefore(entry, feed.firstChild);
            // Cap to 40 items
            while (feed.children.length > 40) {
                feed.removeChild(feed.lastChild);
            }
        }

        triggerLightningDischarge(targetPrey) {
            if (!targetPrey || !targetPrey._x || !targetPrey._y) return;
            this.audio.playLightningCrack();

            const bolt = {
                startX: this.centerX,
                startY: this.centerY,
                endX: targetPrey._x,
                endY: targetPrey._y,
                segments: [],
                alpha: 1.0,
                color: Math.random() > 0.3 ? '#ffd700' : '#00f0ff',
                width: 2.5 + Math.random() * 1.5
            };

            // Generate fractal jagged path
            this.generateFractalBolt(bolt.startX, bolt.startY, bolt.endX, bolt.endY, 5, 24, bolt.segments);
            this.lightningBolts.push(bolt);

            // Emit electron sparks along the tentacle
            for (let i = 0; i < 8; i++) {
                const t = Math.random();
                this.particles.push({
                    x: this.centerX + (targetPrey._x - this.centerX) * t + (Math.random() - 0.5) * 20,
                    y: this.centerY + (targetPrey._y - this.centerY) * t + (Math.random() - 0.5) * 20,
                    vx: (Math.random() - 0.5) * 2.0,
                    vy: (Math.random() - 0.5) * 2.0,
                    alpha: 1.0,
                    decay: 0.04 + Math.random() * 0.04,
                    color: bolt.color,
                    size: 2.0 + Math.random() * 2.0
                });
            }
        }

        generateFractalBolt(x1, y1, x2, y2, depth, displace, outSegments) {
            if (depth <= 0) {
                outSegments.push({ x1, y1, x2, y2 });
                return;
            }
            const midX = (x1 + x2) / 2;
            const midY = (y1 + y2) / 2;
            const dx = x2 - x1;
            const dy = y2 - y1;
            const len = Math.sqrt(dx * dx + dy * dy);
            const nx = -dy / (len || 1);
            const ny = dx / (len || 1);

            const offset = (Math.random() - 0.5) * displace;
            const cx = midX + nx * offset;
            const cy = midY + ny * offset;

            this.generateFractalBolt(x1, y1, cx, cy, depth - 1, displace * 0.6, outSegments);
            this.generateFractalBolt(cx, cy, x2, y2, depth - 1, displace * 0.6, outSegments);
        }

        // --------------------------------------------------------------------
        // 60 FPS MAIN RENDER LOOP
        // --------------------------------------------------------------------
        startLoop() {
            const frame = (timestamp) => {
                const dt = (timestamp - this.lastTimestamp) / 1000.0;
                this.lastTimestamp = timestamp;
                this.updatePhysics(dt, timestamp);
                this.render(timestamp);
                this.animFrameId = requestAnimationFrame(frame);
            };
            this.animFrameId = requestAnimationFrame(frame);
        }

        updatePhysics(dt, timestamp) {
            // 30s Sonar sweep rotation
            const prevAngle = this.sonarAngle;
            this.sonarAngle = (this.sonarAngle + (Math.PI * 2 / this.sweepDurationSec) * dt) % (Math.PI * 2);

            // Periodic 30s scan chirp & log
            if (prevAngle > this.sonarAngle) {
                this.audio.playSonarPing();
                this.addTapeLog('SCAN', `30s Binance sweep cycle complete. Universe re-sieved.`);
            }

            // Core breathing pulse
            this.corePulse = Math.sin(timestamp * 0.003) * 0.5 + 0.5;

            // Fade lightning bolts
            for (let i = this.lightningBolts.length - 1; i >= 0; i--) {
                const b = this.lightningBolts[i];
                b.alpha -= dt * 3.5;
                if (b.alpha <= 0) {
                    this.lightningBolts.splice(i, 1);
                }
            }

            // Update particles
            for (let i = this.particles.length - 1; i >= 0; i--) {
                const p = this.particles[i];
                p.x += p.vx;
                p.y += p.vy;
                p.alpha -= p.decay;
                if (p.alpha <= 0) {
                    this.particles.splice(i, 1);
                }
            }

            // Update shimmer plasma rings
            for (let i = this.shimmerEffects.length - 1; i >= 0; i--) {
                const s = this.shimmerEffects[i];
                s.radius += dt * 250;
                s.alpha -= dt * 1.8;
                if (s.alpha <= 0 || s.radius >= s.maxRadius) {
                    this.shimmerEffects.splice(i, 1);
                }
            }
        }

        render(timestamp) {
            const ctx = this.ctx;
            ctx.clearRect(0, 0, this.width, this.height);

            ctx.save();
            ctx.translate(this.centerX + this.camX, this.centerY + this.camY);
            ctx.scale(this.camZoom, this.camZoom);
            ctx.translate(-this.centerX, -this.centerY);

            // 1. Polar Background Grid Rings
            this.renderPolarGrid(ctx);

            // 2. 30-Second Sonar Sweep Beam
            this.renderSonarSweep(ctx);

            // 3. Quarantined Outer Red Electric Fence
            this.renderQuarantinePerimeter(ctx, timestamp);

            // 4. Electric Bézier Tentacles
            this.renderTentacles(ctx, timestamp);

            // 5. High-Voltage Lightning Discharges
            this.renderLightning(ctx);

            // 6. Active Hot Prey Nodes
            this.renderPreyNodes(ctx, timestamp);

            // 7. Dispersing Particle Sparks
            this.renderParticles(ctx);

            // 8. Core Predator Tiger Node
            this.renderCoreNode(ctx, timestamp);

            // 9. Shimmer Plasma Waves
            this.renderShimmers(ctx);

            ctx.restore();
        }

        // --------------------------------------------------------------------
        // RENDER PASSES
        // --------------------------------------------------------------------
        renderPolarGrid(ctx) {
            ctx.save();
            ctx.strokeStyle = 'rgba(0, 240, 255, 0.08)';
            ctx.lineWidth = 1;

            // Concentric rings
            const rings = [0.25, 0.55, 0.85];
            rings.forEach((ratio, idx) => {
                const r = this.maxRadius * ratio;
                ctx.beginPath();
                ctx.arc(this.centerX, this.centerY, r, 0, Math.PI * 2);
                ctx.stroke();

                // Ring Labels
                ctx.fillStyle = 'rgba(0, 240, 255, 0.28)';
                ctx.font = '9px monospace';
                const label = idx === 0 ? 'STRIKE ZONE (S >= 0.75)' : (idx === 1 ? 'STALKING ORBIT (S >= 0.45)' : 'DETECTION HORIZON');
                ctx.fillText(label, this.centerX + 8, this.centerY - r + 12);
            });

            // Crosshair axes
            ctx.beginPath();
            ctx.moveTo(this.centerX - this.maxRadius * 1.15, this.centerY);
            ctx.lineTo(this.centerX + this.maxRadius * 1.15, this.centerY);
            ctx.moveTo(this.centerX, this.centerY - this.maxRadius * 1.15);
            ctx.lineTo(this.centerX, this.centerY + this.maxRadius * 1.15);
            ctx.stroke();

            ctx.restore();
        }

        renderSonarSweep(ctx) {
            ctx.save();
            const sweepRadius = this.maxRadius * 1.05;

            // Radial gradient wedge trailing the sweep line
            const wedgeAngle = Math.PI / 7; // ~25 deg
            const grad = ctx.createRadialGradient(
                this.centerX, this.centerY, 10,
                this.centerX, this.centerY, sweepRadius
            );
            grad.addColorStop(0, 'rgba(0, 240, 255, 0.25)');
            grad.addColorStop(1, 'rgba(0, 240, 255, 0.0)');

            ctx.beginPath();
            ctx.moveTo(this.centerX, this.centerY);
            ctx.arc(this.centerX, this.centerY, sweepRadius, this.sonarAngle - wedgeAngle, this.sonarAngle, false);
            ctx.closePath();
            ctx.fillStyle = grad;
            ctx.fill();

            // Leading bright sweep line
            const lx = this.centerX + Math.cos(this.sonarAngle) * sweepRadius;
            const ly = this.centerY + Math.sin(this.sonarAngle) * sweepRadius;
            ctx.beginPath();
            ctx.moveTo(this.centerX, this.centerY);
            ctx.lineTo(lx, ly);
            ctx.strokeStyle = '#00f0ff';
            ctx.lineWidth = 1.8;
            ctx.shadowColor = '#00f0ff';
            ctx.shadowBlur = 10;
            ctx.stroke();

            ctx.restore();
        }

        renderQuarantinePerimeter(ctx, timestamp) {
            ctx.save();
            const qRadius = this.maxRadius * 1.12;

            // Concentric dashed red perimeter
            ctx.strokeStyle = 'rgba(255, 34, 85, 0.45)';
            ctx.lineWidth = 1.5;
            ctx.setLineDash([6, 6]);
            ctx.lineDashOffset = -timestamp * 0.02;
            ctx.beginPath();
            ctx.arc(this.centerX, this.centerY, qRadius, 0, Math.PI * 2);
            ctx.stroke();
            ctx.setLineDash([]);

            // Barbed electric micro-sparks on wire
            ctx.strokeStyle = '#ff2255';
            ctx.lineWidth = 1.2;
            ctx.shadowColor = '#ff2255';
            ctx.shadowBlur = 8;
            for (let i = 0; i < 16; i++) {
                const angle = (i / 16) * Math.PI * 2 + Math.sin(timestamp * 0.002 + i) * 0.05;
                const px = this.centerX + Math.cos(angle) * qRadius;
                const py = this.centerY + Math.sin(angle) * qRadius;
                const sparkLen = 4 + Math.sin(timestamp * 0.01 + i) * 3;
                ctx.beginPath();
                ctx.moveTo(px - sparkLen, py - sparkLen);
                ctx.lineTo(px + sparkLen, py + sparkLen);
                ctx.stroke();
            }

            // Render Quarantined Assets orbiting outside fence
            const qSymbols = this.quarantinedSymbols || ['ETHUSDT', 'SOLUSDT'];
            this.quarantineNodes = [];

            qSymbols.forEach((sym, idx) => {
                const angle = (idx / Math.max(qSymbols.length, 1)) * Math.PI + Math.PI * 0.2 + timestamp * 0.00015;
                const r = qRadius + 18 + (idx % 2) * 12;
                const qx = this.centerX + Math.cos(angle) * r;
                const qy = this.centerY + Math.sin(angle) * r;
                this.quarantineNodes.push({ symbol: sym, x: qx, y: qy });

                // Node marker
                ctx.fillStyle = 'rgba(255, 34, 85, 0.25)';
                ctx.strokeStyle = '#ff2255';
                ctx.lineWidth = 1.2;
                ctx.beginPath();
                ctx.arc(qx, qy, 8, 0, Math.PI * 2);
                ctx.fill();
                ctx.stroke();

                // Symbol text
                ctx.fillStyle = '#ff6b8b';
                ctx.font = 'bold 9px monospace';
                ctx.fillText(sym, qx + 11, qy + 3);
            });

            ctx.restore();
        }

        renderTentacles(ctx, timestamp) {
            ctx.save();

            this.activePrey.forEach((p, idx) => {
                // Compute node position
                const px = this.centerX + Math.cos(p._angle) * p._r;
                const py = this.centerY + Math.sin(p._angle) * p._r;
                p._x = px;
                p._y = py;

                // Cubic Bézier Spline with sine wave transverse modulation
                const dx = px - this.centerX;
                const dy = py - this.centerY;
                const dist = Math.sqrt(dx * dx + dy * dy);
                const nx = -dy / (dist || 1);
                const ny = dx / (dist || 1);

                const phase = p._tentaclePhase || 0;
                const wave1 = Math.sin(timestamp * 0.0025 + phase) * 22;
                const wave2 = Math.cos(timestamp * 0.0032 + phase * 1.5) * 18;

                const cp1x = this.centerX + dx * 0.33 + nx * wave1;
                const cp1y = this.centerY + dy * 0.33 + ny * wave1;
                const cp2x = this.centerX + dx * 0.66 - nx * wave2;
                const cp2y = this.centerY + dy * 0.66 - ny * wave2;

                const isSelected = (this.selectedPrey === p.symbol);
                const strPct = (p.dynamic_strength_pct !== undefined) ? p.dynamic_strength_pct : 100;

                // Color-code Bézier tentacles based on dynamic strength percentage
                let tentacleStroke = 'rgba(0, 240, 255, 0.35)';
                let filamentStroke = '#e0ffff';
                let tentacleGlow = '#00f0ff';
                let glowBlur = 10;

                if (isSelected) {
                    tentacleStroke = 'rgba(255, 215, 0, 0.55)';
                    filamentStroke = '#ffffff';
                    tentacleGlow = '#ffd700';
                    glowBlur = 16;
                } else if (strPct >= 75) {
                    // Prime Opportunity (Neon Cyan)
                    tentacleStroke = 'rgba(0, 240, 255, 0.38)';
                    filamentStroke = '#c8f9ff';
                    tentacleGlow = '#00f0ff';
                } else if (strPct >= 45) {
                    // Waning / Degrading (Amber / Gold)
                    tentacleStroke = 'rgba(255, 215, 0, 0.38)';
                    filamentStroke = '#fff2a8';
                    tentacleGlow = '#ffd700';
                } else {
                    // Stagnant / Near-Eviction (Neon Red / Magenta)
                    tentacleStroke = 'rgba(255, 34, 85, 0.45)';
                    filamentStroke = '#ff99aa';
                    tentacleGlow = '#ff2255';
                    glowBlur = 14;
                }

                // Outer Neon Glow Pass
                ctx.beginPath();
                ctx.moveTo(this.centerX, this.centerY);
                ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, px, py);
                ctx.strokeStyle = tentacleStroke;
                ctx.lineWidth = isSelected ? 4.0 : 2.5;
                ctx.shadowColor = tentacleGlow;
                ctx.shadowBlur = glowBlur;
                ctx.stroke();

                // Core Bright Filament Line
                ctx.beginPath();
                ctx.moveTo(this.centerX, this.centerY);
                ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, px, py);
                ctx.strokeStyle = filamentStroke;
                ctx.lineWidth = isSelected ? 1.8 : 1.2;
                ctx.shadowBlur = 0;
                ctx.stroke();
            });

            ctx.restore();
        }

        renderLightning(ctx) {
            if (this.lightningBolts.length === 0) return;
            ctx.save();

            this.lightningBolts.forEach(bolt => {
                ctx.strokeStyle = bolt.color;
                ctx.lineWidth = bolt.width;
                ctx.shadowColor = bolt.color;
                ctx.shadowBlur = 14;
                ctx.globalAlpha = Math.max(0, bolt.alpha);

                ctx.beginPath();
                bolt.segments.forEach((seg, i) => {
                    if (i === 0) ctx.moveTo(seg.x1, seg.y1);
                    ctx.lineTo(seg.x2, seg.y2);
                });
                ctx.stroke();
            });

            ctx.restore();
        }

        renderPreyNodes(ctx, timestamp) {
            ctx.save();

            this.activePrey.forEach(p => {
                const px = p._x;
                const py = p._y;
                if (!px || !py) return;

                const scale = p._scale || 1.0;
                const baseRadius = 14 + Math.min(10, Math.sqrt(parseFloat(p.turnover_24h_usd || 0) / 1e7));
                const radius = baseRadius * scale;
                p._radius = radius;

                const chg = parseFloat(p.price_change_pct || 0);
                const isBull = chg >= 0;
                const nodeColor = isBull ? '#00ff88' : '#ff2255';
                const isHovered = (this.hoveredNode && this.hoveredNode.symbol === p.symbol);
                const isSelected = (this.selectedPrey === p.symbol);

                // Outer Halo
                ctx.beginPath();
                ctx.arc(px, py, radius + (isHovered ? 6 : 3), 0, Math.PI * 2);
                ctx.fillStyle = isSelected ? 'rgba(255, 215, 0, 0.25)' : (isBull ? 'rgba(0, 255, 136, 0.18)' : 'rgba(255, 34, 85, 0.18)');
                ctx.fill();

                // Core Plasma Node
                ctx.beginPath();
                ctx.arc(px, py, radius, 0, Math.PI * 2);
                ctx.fillStyle = '#0a101a';
                ctx.strokeStyle = isSelected ? '#ffd700' : (isHovered ? '#00f0ff' : nodeColor);
                ctx.lineWidth = isSelected ? 2.5 : 1.8;
                ctx.shadowColor = ctx.strokeStyle;
                ctx.shadowBlur = isHovered ? 14 : 8;
                ctx.fill();
                ctx.stroke();

                // Rank Badge in Center
                ctx.fillStyle = '#ffffff';
                ctx.font = 'bold 10px monospace';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.shadowBlur = 0;
                ctx.fillText(`#${p.rank}`, px, py - 1);

                // Symbol Tag Above Node
                const isScoutedPrey = (p.rank <= 2 && parseFloat(p.turnover_24h_usd || 0) >= 50000000 && !p.is_quarantined);
                if (isScoutedPrey) {
                    ctx.fillStyle = '#ff9800';
                    ctx.font = 'bold 8px monospace';
                    ctx.fillText('⚡ MACRO SCOUT', px, py - radius - 16);
                }

                ctx.fillStyle = isSelected ? '#ffd700' : '#ffffff';
                ctx.font = 'bold 11px monospace';
                ctx.fillText(p.symbol, px, py - radius - 6);

                // Price & Turnover Tag Below Node
                ctx.fillStyle = nodeColor;
                ctx.font = '9px monospace';
                const turnoverM = (parseFloat(p.turnover_24h_usd || 0) / 1e6).toFixed(0);
                ctx.fillText(`$${p.last_price} · $${turnoverM}M`, px, py + radius + 11);

                // Dynamic Strength Tag Below Node
                const strPct = (p.dynamic_strength_pct !== undefined) ? Math.round(p.dynamic_strength_pct) : 100;
                let strColor = '#00f0ff';
                if (strPct < 45) strColor = '#ff3366';
                else if (strPct < 75) strColor = '#ffd700';

                const stagStatus = p.stagnation_status || 'ACTIVE';
                const stagIcon = stagStatus === 'STAGNANT_2' ? '🛑' : (stagStatus === 'STAGNANT_1' ? '⚠️' : '⚡');

                ctx.fillStyle = strColor;
                ctx.font = 'bold 9px monospace';
                ctx.fillText(`${stagIcon} ${strPct}% STR`, px, py + radius + 22);
            });

            ctx.restore();
        }

        renderCoreNode(ctx, timestamp) {
            ctx.save();
            const cx = this.centerX;
            const cy = this.centerY;
            const coreR = 26 + this.corePulse * 4;

            // Outer Radiant Nebula Aura
            const auraGrad = ctx.createRadialGradient(cx, cy, 10, cx, cy, 75);
            auraGrad.addColorStop(0, 'rgba(0, 240, 255, 0.35)');
            auraGrad.addColorStop(0.6, 'rgba(189, 0, 255, 0.15)');
            auraGrad.addColorStop(1, 'rgba(0, 240, 255, 0.0)');
            ctx.fillStyle = auraGrad;
            ctx.beginPath();
            ctx.arc(cx, cy, 75, 0, Math.PI * 2);
            ctx.fill();

            // Rotating Reticle Rings
            ctx.strokeStyle = 'rgba(0, 240, 255, 0.5)';
            ctx.lineWidth = 1.2;
            ctx.setLineDash([8, 8]);
            ctx.lineDashOffset = timestamp * 0.03;
            ctx.beginPath();
            ctx.arc(cx, cy, coreR + 10, 0, Math.PI * 2);
            ctx.stroke();

            ctx.lineDashOffset = -timestamp * 0.04;
            ctx.strokeStyle = 'rgba(255, 215, 0, 0.4)';
            ctx.beginPath();
            ctx.arc(cx, cy, coreR + 18, 0, Math.PI * 2);
            ctx.stroke();
            ctx.setLineDash([]);

            // Hexagonal Core
            ctx.beginPath();
            for (let i = 0; i < 6; i++) {
                const angle = (i / 6) * Math.PI * 2 - Math.PI / 6;
                const hx = cx + Math.cos(angle) * coreR;
                const hy = cy + Math.sin(angle) * coreR;
                if (i === 0) ctx.moveTo(hx, hy);
                else ctx.lineTo(hx, hy);
            }
            ctx.closePath();
            ctx.fillStyle = '#060c18';
            ctx.strokeStyle = '#00f0ff';
            ctx.lineWidth = 2.0;
            ctx.shadowColor = '#00f0ff';
            ctx.shadowBlur = 16;
            ctx.fill();
            ctx.stroke();

            // Tiger Core Emblem Icon
            ctx.fillStyle = '#00f0ff';
            ctx.font = '16px monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.shadowBlur = 0;
            ctx.fillText('🐅', cx, cy - 2);

            // Core Status Text
            ctx.fillStyle = '#ffd700';
            ctx.font = 'bold 8px monospace';
            ctx.fillText('TIGER CORE', cx, cy + coreR + 30);

            ctx.restore();
        }

        renderParticles(ctx) {
            if (this.particles.length === 0) return;
            ctx.save();
            this.particles.forEach(p => {
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.size || 2, 0, Math.PI * 2);
                ctx.fillStyle = p.color;
                ctx.globalAlpha = Math.max(0, p.alpha);
                ctx.shadowColor = p.color;
                ctx.shadowBlur = 6;
                ctx.fill();
            });
            ctx.restore();
        }

        renderShimmers(ctx) {
            if (this.shimmerEffects.length === 0) return;
            ctx.save();
            this.shimmerEffects.forEach(s => {
                ctx.beginPath();
                ctx.arc(s.x, s.y, s.radius, 0, Math.PI * 2);
                ctx.strokeStyle = s.color;
                ctx.lineWidth = 2.0;
                ctx.globalAlpha = Math.max(0, s.alpha);
                ctx.shadowColor = s.color;
                ctx.shadowBlur = 12;
                ctx.stroke();
            });
            ctx.restore();
        }
    }

    // ------------------------------------------------------------------------
    // 3. GLOBAL ENGINE CONTROLLER & DATA BINDINGS
    // ------------------------------------------------------------------------
    let tigerRadarEngine = null;
    let tigerAudioSynth = null;
    let tigerPollInterval = null;

    function initTigerRadar() {
        if (!tigerAudioSynth) {
            tigerAudioSynth = new TigerAudioSynthesizer();
        }

        if (!tigerRadarEngine) {
            tigerRadarEngine = new TigerRadarEngine('tigerRadarCanvas', tigerAudioSynth);
        } else {
            setTimeout(() => tigerRadarEngine.initCanvasSize(), 40);
        }

        // Bind Audio Toggle
        const audioBtn = document.getElementById('tigerAudioToggleBtn');
        if (audioBtn) {
            audioBtn.onclick = function () {
                const unmuted = tigerAudioSynth.toggleMute();
                if (unmuted) {
                    audioBtn.classList.add('active');
                    audioBtn.innerHTML = '<span>🔊</span> AUDIO SFX: ON';
                } else {
                    audioBtn.classList.remove('active');
                    audioBtn.innerHTML = '<span>🔈</span> AUDIO SFX: MUTED';
                }
            };
        }

        // Initial Data Fetch
        fetchTigerRadarData();

        // Recurring 2s polling
        if (!tigerPollInterval) {
            tigerPollInterval = setInterval(() => {
                if (typeof currentActiveView !== 'undefined' && (currentActiveView === 'tiger' || currentActiveView === 'scalper')) {
                    fetchTigerRadarData();
                }
            }, 2000);
        }
    }

    async function fetchTigerRadarData() {
        try {
            const resp = await axios.get('/api/tiger/radar');
            if (!resp.data || !resp.data.success) return;

            const d = resp.data;
            const radar = d.radar || {};

            // 1. Update Canvas Radar
            if (tigerRadarEngine) {
                tigerRadarEngine.updateTelemetry(radar);
            }

            // 2. Update Header Metrics
            if (d.contra_mode !== undefined && window.updateContraModeUI) {
                window.updateContraModeUI(d.contra_mode);
            }

            const elBal = document.getElementById('tiger-bal-val');
            if (elBal && d.wallet_balance) {
                elBal.textContent = `$${parseFloat(d.wallet_balance).toFixed(2)} USDT`;
            }

            const awsPill = document.getElementById('topbar-aws-tap-pill');
            if (awsPill) {
                if (d.aws_tap_active) {
                    awsPill.innerHTML = '<span class="pulse-dot" style="background: #00f0ff;"></span> 🔒 AWS TAP: ACTIVE (13.63.158.94)';
                    awsPill.style.color = '#00f0ff';
                    awsPill.style.borderColor = 'rgba(0, 240, 255, 0.4)';
                }
            }

            const elTicks = document.getElementById('tiger-ticks-val');
            if (elTicks && radar.ws_ticks !== undefined) {
                elTicks.textContent = Number(radar.ws_ticks).toLocaleString();
            }

            const elWeight = document.getElementById('tiger-weight-val');
            if (elWeight && radar.used_weight !== undefined) {
                elWeight.textContent = `${radar.used_weight} / 1200`;
            }

            const elBtc = document.getElementById('tiger-btc-val');
            if (elBtc && radar.btc_1m_return_pct !== undefined) {
                const ret = parseFloat(radar.btc_1m_return_pct);
                const cvd = parseFloat(radar.btc_cvd_zscore || 0);
                elBtc.textContent = `${ret >= 0 ? '+' : ''}${ret.toFixed(2)}% · CVD ${cvd.toFixed(1)}σ`;
                elBtc.style.color = (ret <= -0.35 || cvd <= -2.5) ? '#ff2255' : '#00ff88';
            }

            // 3. Update 5 Hot Prey Card List
            renderHotPreyList(radar.active_prey || []);

            // 4. Update Quarantine List
            renderQuarantineList(radar.quarantined_symbols || ['ETHUSDT', 'SOLUSDT']);

            // 5. Update Advisory Values
            if (d.advisory) {
                const elZeroMfe = document.getElementById('tiger-adv-zero-mfe');
                if (elZeroMfe) elZeroMfe.textContent = `${d.advisory.zero_mfe_abort_seconds}s - ${d.advisory.zero_mfe_max_window_seconds}s ARMED`;

                const elWicks = document.getElementById('tiger-adv-wicks');
                if (elWicks) elWicks.textContent = `BUY ≥ ${d.advisory.min_buy_wick_ratio} | SELL ≥ ${d.advisory.min_sell_wick_ratio}`;

                const elFloor = document.getElementById('tiger-adv-turnover-floor');
                if (elFloor) elFloor.textContent = `$${(d.advisory.min_24h_turnover_usd / 1e6).toFixed(0)}M USD`;

                const elBridge = document.getElementById('tiger-bridge-val');
                if (elBridge && d.advisory.reconnaissance_bridge) {
                    elBridge.textContent = `⚡ ${d.advisory.reconnaissance_bridge.status} (Rank 1-2)`;
                    elBridge.style.color = '#ff9800';
                }

                const elAdvScout = document.getElementById('tiger-adv-scout-status');
                if (elAdvScout && d.advisory.reconnaissance_bridge) {
                    const br = d.advisory.reconnaissance_bridge;
                    elAdvScout.textContent = `RELAYING TOP PREY → MACRO STORM (${br.confluence_multiplier} / ${br.conflict_throttle})`;
                }
            }

        } catch (e) {
            console.error('[TigerRadar] Telemetry poll error:', e);
        }
    }

    function renderHotPreyList(preyList) {
        const container = document.getElementById('tigerPreyListContainer');
        if (!container) return;

        let html = '';
        preyList.forEach(p => {
            const chg = parseFloat(p.price_change_pct || 0);
            const chgColor = chg >= 0 ? '#00ff88' : '#ff2255';
            const turnover = parseFloat(p.turnover_24h_usd || 0);
            const turnoverM = (turnover / 1e6).toFixed(1);

            const strPct = p.dynamic_strength_pct !== undefined ? Math.round(p.dynamic_strength_pct) : 100;
            let barColor = '#00f0ff';
            let badgeText = 'STALKING';
            let badgeStyle = 'background: rgba(0, 240, 255, 0.15); color: #00f0ff; border: 1px solid rgba(0,240,255,0.3);';

            if (p.stagnation_status === 'STAGNANT_1') {
                barColor = '#ffd700';
                badgeText = 'WANING';
                badgeStyle = 'background: rgba(255, 215, 0, 0.15); color: #ffd700; border: 1px solid rgba(255,215,0,0.3);';
            } else if (p.stagnation_status === 'STAGNANT_2') {
                barColor = '#ff3366';
                badgeText = 'STAGNANT';
                badgeStyle = 'background: rgba(255, 34, 85, 0.2); color: #ff3366; border: 1px solid rgba(255,34,85,0.4);';
            } else if (strPct < 75) {
                barColor = '#ffd700';
            }

            const isScouted = (p.rank <= 2 && turnover >= 50000000 && !p.is_quarantined);
            let scoutBadge = isScouted ? '<span class="tiger-prey-badge" style="background: rgba(255, 152, 0, 0.25); color: #ff9800; border: 1px solid rgba(255,152,0,0.5); font-size: 9px; margin-left: 5px; font-weight: 800;" title="Scouted by TigerScoutBridge for Macro Storm Protocol validation">🐅 MACRO SCOUT</span>' : '';

            const cvdZ = p.cvd_zscore !== undefined ? p.cvd_zscore : '0.0';
            const microSkew = p.micro_skew_bps !== undefined ? p.micro_skew_bps : '0.0';
            const absSig = (p.absorption_signal && p.absorption_signal !== 'NONE') ? p.absorption_signal : '';
            let absSigBadge = '';
            if (absSig === 'BUY') {
                absSigBadge = '<span style="background: rgba(0,255,136,0.2); color: #00ff88; border: 1px solid rgba(0,255,136,0.4); border-radius: 2px; padding: 1px 4px; font-size: 8px; font-weight: 800; margin-left: 4px;">SPRING BUY</span>';
            } else if (absSig === 'SELL') {
                absSigBadge = '<span style="background: rgba(255,34,85,0.2); color: #ff2255; border: 1px solid rgba(255,34,85,0.4); border-radius: 2px; padding: 1px 4px; font-size: 8px; font-weight: 800; margin-left: 4px;">CLIMAX SELL</span>';
            }

            html += `
                <div class="tiger-prey-row" onclick="selectTigerPrey('${p.symbol}')" id="prey-row-${p.symbol}">
                    <div class="tiger-prey-rank">#${p.rank}</div>
                    <div class="tiger-prey-info">
                        <div style="display: flex; align-items: center; flex-wrap: wrap;">
                            <span class="tiger-prey-symbol">${p.symbol}</span>
                            ${scoutBadge}
                            ${absSigBadge}
                        </div>
                        <span class="tiger-prey-meta">Vol: ${parseFloat(p.volatility_score || 0).toFixed(3)} · $${turnoverM}M · CVD: ${cvdZ}σ · Skew: ${microSkew}bps</span>
                        <div class="tiger-strength-bar-wrap">
                            <div class="tiger-strength-bar">
                                <div class="tiger-strength-fill" style="width: ${strPct}%; background: ${barColor};"></div>
                            </div>
                            <span class="tiger-strength-pct-label" style="color: ${barColor};">${strPct}%</span>
                        </div>
                    </div>
                    <div class="tiger-prey-price">
                        <div>$${p.last_price}</div>
                        <div style="color: ${chgColor}; font-size: 10px;">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</div>
                    </div>
                    <div>
                        <span class="tiger-prey-badge" style="${badgeStyle}">
                            ${badgeText}
                        </span>
                    </div>
                </div>
            `;
        });
        container.innerHTML = html || '<div style="color: #6e7681; font-size: 11px; text-align: center; padding: 15px;">Scanning for Hot Prey...</div>';
    }

    function renderQuarantineList(qList) {
        const box = document.getElementById('tigerQuarantineList');
        if (!box) return;

        let html = '';
        qList.forEach(sym => {
            html += `<span class="tiger-quarantine-pill">⛔ ${sym}</span>`;
        });
        box.innerHTML = html || '<span style="color: #6e7681; font-size: 10px;">None quarantined</span>';
    }

    window.selectTigerPrey = function (symbol) {
        if (!tigerRadarEngine) return;
        tigerRadarEngine.selectedPrey = symbol;
        const prey = tigerRadarEngine.activePrey.find(p => p.symbol === symbol);
        if (prey) {
            tigerRadarEngine.triggerLightningDischarge(prey);
        }
        document.querySelectorAll('.tiger-prey-row').forEach(el => el.classList.remove('selected'));
        const row = document.getElementById(`prey-row-${symbol}`);
        if (row) row.classList.add('selected');
    };

    window.initTigerRadar = initTigerRadar;
    window.fetchTigerRadarData = fetchTigerRadarData;
    window.resizeTigerRadarCanvas = function () {
        if (tigerRadarEngine) tigerRadarEngine.initCanvasSize();
    };
    window.tigerZoomIn = function () {
        if (tigerRadarEngine) tigerRadarEngine.setZoom(tigerRadarEngine.camZoom * 1.18);
    };
    window.tigerZoomOut = function () {
        if (tigerRadarEngine) tigerRadarEngine.setZoom(tigerRadarEngine.camZoom * 0.85);
    };
    window.tigerResetView = function () {
        if (tigerRadarEngine) tigerRadarEngine.resetCamera();
    };

})();
