/**
 * webui/static/js/swarm_deck.js — Interactive 6-Bot Neural Swarm Canvas & BotSwarmBridge
 *
 * Features:
 * - 6-Bot Default Fleet (36 Agent Workers) including BOT-05 (NEON-5 Trend Hunter) & BOT-06 (NEON-6 Maker Arbiter).
 * - Segmented 6 | 4 | 3 fleet topology switching with balanced 3x2 / 2x2 / 1+2 spatial geometry.
 * - Upgraded Canvas HUD Nodes with 6-segment radial gate status rings, hex core geometry, and unboxed tabular PnL tags.
 * - Live NEON Telemetry Sync from /api/neon/overview & /api/neon/equity-curve for BOT-05 and BOT-06.
 * - Click-to-Inspect (<5px movement) Slide-Over Bot Inspector Drawer with 6-gate matrix & bracket blueprints.
 * - Docked Bottom Fleet Roster bar with per-bot smooth Camera Focus lerp and individual Pause/Resume controls.
 * - Preserves drag-to-relocate bots/beacons, viewport pan/zoom, double-click reset, and WebSocket /swarm bridge.
 */

(function () {
  'use strict';

  // --- 1. CONFIGURATION & 6-BOT FLEET DEFINITIONS ---
  const WORKER_STAGES = [
    { id: 'SCAN', label: 'SCAN', color: '#f43f5e', name: 'Market Scanner' },
    { id: 'FLOW', label: 'FLOW', color: '#fb7185', name: 'Orderflow CVD' },
    { id: 'RISK', label: 'RISK', color: '#2dd4bf', name: 'Risk Arbiter' },
    { id: 'VALID', label: 'VALID', color: '#fbbf24', name: 'Trajectory Check' },
    { id: 'EXEC', label: 'EXEC', color: '#a855f7', name: 'Execution Engine' },
    { id: 'LEDGER', label: 'LEDGER', color: '#34d399', name: 'Decimal Ledger' }
  ];

  const DEFAULT_BOTS_6 = [
    {
      id: 'BOT-01',
      name: 'LIGHTNING',
      role: 'Scalp Velocity',
      strategyKey: 'lightning',
      accent: '#f5c869',
      pair: 'SOL/USDT',
      pnlText: '+$4.85',
      pnlPositive: true,
      winRateText: '61.2% WR'
    },
    {
      id: 'BOT-02',
      name: 'TIGER',
      role: 'Prey Radar',
      strategyKey: 'tiger',
      accent: '#38bdf8',
      pair: 'BTC/USDT',
      pnlText: '+$6.12',
      pnlPositive: true,
      winRateText: '63.4% WR'
    },
    {
      id: 'BOT-03',
      name: 'MACRO',
      role: 'Regime Forecast',
      strategyKey: 'macro',
      accent: '#c084fc',
      pair: 'ETH/USDT',
      pnlText: '+$3.40',
      pnlPositive: true,
      winRateText: '58.5% WR'
    },
    {
      id: 'BOT-04',
      name: 'STORM',
      role: 'Trend Momentum',
      strategyKey: 'storm',
      accent: '#34d399',
      pair: 'BNB/USDT',
      pnlText: '+$5.18',
      pnlPositive: true,
      winRateText: '59.8% WR'
    },
    {
      id: 'BOT-05',
      name: 'NEON-5',
      role: 'Trend Hunter',
      strategyKey: 'neon-trend',
      accent: '#22d3ee',
      pair: 'BTC/USDT',
      pnlText: '+$9.40',
      pnlPositive: true,
      winRateText: '56.7% WR'
    },
    {
      id: 'BOT-06',
      name: 'NEON-6',
      role: 'Maker Arbiter',
      strategyKey: 'neon-maker',
      accent: '#2dd4bf',
      pair: 'LINK/USDT',
      pnlText: '+$25.20',
      pnlPositive: true,
      winRateText: '67.8% WR'
    }
  ];

  const DEFAULT_BOTS_4 = DEFAULT_BOTS_6.slice(0, 4);
  const DEFAULT_BOTS_3 = DEFAULT_BOTS_6.slice(0, 3);

  const CANDIDATE_ASSETS = ['BTC', 'ETH', 'SOL', 'BNB', 'LINK', 'AVAX', 'SUI', 'NEAR', 'RENDER', 'APT'];

  // --- 2. ENGINE & INTERACTION STATE ---
  let canvas, ctx;
  let animFrameId = null;
  let isRunning = true;
  let botsCount = 6;
  let simulationPace = 1.0;
  let isLiveWS = false;
  let wsSocket = null;
  let wsUrl = (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + (window.location.host || 'localhost:3000') + '/swarm';

  let bots = [];
  let beacons = new Map();
  let particles = [];
  let lightningStrikes = [];

  // Selection, Camera & Telemetry State
  let selectedBotId = null;
  let cameraTarget = null; // { panX, panY, zoom }
  let cachedNeonOverview = null;
  let cachedNeonEquity = null;
  let neonSyncTimer = null;

  // Pan, Zoom & Dragging state
  let panX = 0;
  let panY = 0;
  let zoom = 1.0;
  let isPanning = false;
  let panStart = { x: 0, y: 0 };
  let draggedBot = null;
  let draggedBeacon = null;
  let dragOffset = { x: 0, y: 0 };
  let pointerDownScreen = { x: 0, y: 0 };
  let pointerDragMoved = false;
  let hoveredBot = null;
  let hoveredBeacon = null;

  let lastTime = performance.now();
  let demoTimer = 0;

  // --- 3. FORMATTING HELPERS ---
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

  function fmtPair(sym) {
    const s = String(sym || 'BTCUSDT');
    if (s.includes('/')) return s;
    if (s.endsWith('USDT')) return `${s.slice(0, -4)}/USDT`;
    return s;
  }

  function fmtUtcClock() {
    const d = new Date();
    const hh = String(d.getUTCHours()).padStart(2, '0');
    const mm = String(d.getUTCMinutes()).padStart(2, '0');
    const ss = String(d.getUTCSeconds()).padStart(2, '0');
    return `${hh}:${mm}:${ss} UTC`;
  }

  // --- 4. BOT & WORKER CLASSES ---
  class BotNode {
    constructor(cfg, targetX, targetY) {
      this.id = cfg.id;
      this.name = cfg.name;
      this.role = cfg.role || 'Autonomous Agent';
      this.strategyKey = cfg.strategyKey || 'standard';
      this.isNeon = this.strategyKey === 'neon-trend' || this.strategyKey === 'neon-maker';
      this.accent = cfg.accent || '#38bdf8';
      this.pair = cfg.pair || 'BTC/USDT';
      this.x = targetX;
      this.y = targetY;
      this.isCustomPosition = false;
      this.isDragged = false;
      this.paused = false;
      this.radius = 23;
      this.angle = Math.random() * Math.PI * 2;
      this.stateText = this.isNeon ? 'SYNCING' : 'HUNTING';
      this.stateTime = 0;
      this.lockedBeaconId = null;

      // Live Telemetry Fields
      this.pnlText = cfg.pnlText || '+$0.00';
      this.pnlPositive = cfg.pnlPositive !== false;
      this.winRateText = cfg.winRateText || '--';
      this.convictionPct = this.isNeon ? 0 : 72;
      this.vetoReason = '';
      this.bracket = null;
      this.gates = WORKER_STAGES.map((st) => ({
        key: st.id,
        label: st.name,
        passed: !this.isNeon,
        detail: this.isNeon ? 'Awaiting live NEON sync...' : 'Stage nominal'
      }));

      // Initialize 6 satellite workers orbiting this bot
      this.workers = WORKER_STAGES.map((st, i) => ({
        id: st.id,
        label: st.label,
        color: st.color,
        angleOffset: (i * (Math.PI * 2)) / 6,
        orbitRadius: 58,
        x: targetX,
        y: targetY,
        currentPill: null,
        pillTime: 0,
        activePulse: 0
      }));

      this.updateWorkers(0);
    }

    getPassedGateCount() {
      return this.gates.filter((g) => g.passed).length;
    }

    update(dt, defaultX, defaultY) {
      if (!this.isCustomPosition && !this.isDragged) {
        this.x = defaultX;
        this.y = defaultY;
      }

      if (!this.paused) {
        this.angle += dt * 0.38 * simulationPace;
      }

      if (this.stateTime > 0 && !this.paused) {
        this.stateTime -= dt;
        if (this.stateTime <= 0) {
          this.stateText = this.isNeon ? this.getNeonIdleLabel() : 'HUNTING';
          this.lockedBeaconId = null;
        }
      }

      this.updateWorkers(this.paused ? 0 : dt);
    }

    getNeonIdleLabel() {
      const passed = this.getPassedGateCount();
      if (passed === 6) return `APPROVED · ${this.pair.split('/')[0]}`;
      return `${passed}/6 GATES · ${this.pair.split('/')[0]}`;
    }

    updateWorkers(dt = 0) {
      this.workers.forEach((w) => {
        const theta = this.angle + w.angleOffset;
        w.x = this.x + Math.cos(theta) * w.orbitRadius;
        w.y = this.y + Math.sin(theta) * w.orbitRadius;

        if (dt > 0) {
          if (w.pillTime > 0) {
            w.pillTime -= dt;
            if (w.pillTime <= 0) w.currentPill = null;
          }
          if (w.activePulse > 0) {
            w.activePulse = Math.max(0, w.activePulse - dt * 2.2);
          }
        }
      });
    }

    drawHexagon(ctx, cx, cy, r) {
      ctx.beginPath();
      for (let i = 0; i < 6; i++) {
        const a = (Math.PI / 3) * i - Math.PI / 2;
        const px = cx + Math.cos(a) * r;
        const py = cy + Math.sin(a) * r;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.closePath();
    }

    draw(ctx) {
      const isSelected = selectedBotId === this.id;
      const isHovered = this === hoveredBot;
      const dimAlpha = this.paused ? 0.48 : 1.0;

      ctx.save();
      ctx.globalAlpha = dimAlpha;

      // 1. Satellite workers & curved filaments
      this.workers.forEach((w, idx) => {
        const gateInfo = this.gates[idx];
        const gateActive = this.isNeon ? Boolean(gateInfo && gateInfo.passed) : w.activePulse > 0;
        const nodeColor = this.paused
          ? '#64748b'
          : this.isNeon
          ? gateActive
            ? '#22c55e'
            : '#f87171'
          : w.color;

        ctx.beginPath();
        ctx.moveTo(this.x, this.y);
        const midX = (this.x + w.x) / 2 + Math.cos(this.angle) * 6;
        const midY = (this.y + w.y) / 2 + Math.sin(this.angle) * 6;
        ctx.quadraticCurveTo(midX, midY, w.x, w.y);
        ctx.strokeStyle =
          w.activePulse > 0
            ? nodeColor
            : this.isNeon && gateActive
            ? 'rgba(34, 197, 94, 0.24)'
            : 'rgba(148, 163, 184, 0.13)';
        ctx.lineWidth = w.activePulse > 0 ? 1.8 : 1;
        ctx.stroke();

        // Worker node circle
        ctx.beginPath();
        ctx.arc(w.x, w.y, 4 + w.activePulse * 2.5, 0, Math.PI * 2);
        ctx.fillStyle = nodeColor;
        ctx.shadowColor = nodeColor;
        ctx.shadowBlur = w.activePulse > 0 ? 12 : 4;
        ctx.fill();
        ctx.shadowBlur = 0;

        // Worker micro-label
        ctx.font = '600 7.5px "JetBrains Mono", monospace';
        ctx.fillStyle = '#94a3b8';
        ctx.textAlign = 'center';
        ctx.fillText(w.label, w.x, w.y - 7);

        // Live worker signal pill
        if (w.currentPill && !this.paused) {
          ctx.font = '500 8px "JetBrains Mono", monospace';
          const pWidth = ctx.measureText(w.currentPill).width + 10;
          ctx.fillStyle = 'rgba(10, 14, 22, 0.92)';
          ctx.strokeStyle = nodeColor;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.roundRect(w.x - pWidth / 2, w.y + 6, pWidth, 14, 4);
          ctx.fill();
          ctx.stroke();

          ctx.fillStyle = '#f8fafc';
          ctx.fillText(w.currentPill, w.x, w.y + 15.5);
        }
      });

      // 2. Selection / Hover / Drag Precision Halo
      if (isSelected || this.isDragged || isHovered) {
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.radius + 16, 0, Math.PI * 2);
        ctx.strokeStyle = isSelected ? '#22d3ee' : this.accent;
        ctx.lineWidth = isSelected || this.isDragged ? 1.8 : 1.1;
        ctx.setLineDash([4, 4]);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // 3. Radial 6-Gate Segmented Status Ring around Bot Hub
      const ringRadius = this.radius + 8;
      const segSpan = (Math.PI * 2) / 6;
      const gap = 0.14;
      for (let i = 0; i < 6; i++) {
        const startA = -Math.PI / 2 + i * segSpan + gap / 2;
        const endA = -Math.PI / 2 + (i + 1) * segSpan - gap / 2;
        const g = this.gates[i];
        const w = this.workers[i];

        let segColor = 'rgba(148, 163, 184, 0.22)';
        if (this.paused) {
          segColor = 'rgba(100, 116, 139, 0.35)';
        } else if (this.isNeon) {
          segColor = g && g.passed ? '#22c55e' : 'rgba(248, 113, 113, 0.55)';
        } else {
          segColor = w && w.activePulse > 0 ? this.accent : 'rgba(52, 211, 153, 0.55)';
        }

        ctx.beginPath();
        ctx.arc(this.x, this.y, ringRadius, startA, endA);
        ctx.strokeStyle = segColor;
        ctx.lineWidth = 3;
        ctx.lineCap = 'round';
        ctx.stroke();
      }
      ctx.lineCap = 'butt';

      // 4. Central Bot Hub Core (Precision Hex for NEON-5/6, Circle for Bots 1-4)
      ctx.fillStyle = 'rgba(10, 15, 25, 0.96)';
      ctx.strokeStyle = this.paused ? '#64748b' : this.accent;
      ctx.lineWidth = isSelected ? 2.4 : 1.9;
      ctx.shadowColor = this.paused ? 'transparent' : this.accent;
      ctx.shadowBlur = this.isDragged || isSelected ? 18 : 10;

      if (this.isNeon) {
        this.drawHexagon(ctx, this.x, this.y, this.radius);
      } else {
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
      }
      ctx.fill();
      ctx.stroke();
      ctx.shadowBlur = 0;

      // Inner Bot ID + Pair Ticker
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = this.paused ? '#94a3b8' : this.accent;
      ctx.font = '700 9.5px "JetBrains Mono", monospace';
      ctx.fillText(this.id, this.x, this.y - 4);

      ctx.fillStyle = '#cbd5e1';
      ctx.font = '600 7.5px "JetBrains Mono", monospace';
      ctx.fillText(this.pair.split('/')[0], this.x, this.y + 7);

      ctx.restore();

      // 5. Crisp Unboxed Name, State & Tabular PnL Readout Beneath Hub (Always Full Contrast)
      ctx.save();
      ctx.textAlign = 'center';
      ctx.textBaseline = 'alphabetic';

      ctx.font = '700 9.5px "Plus Jakarta Sans", sans-serif';
      ctx.fillStyle = this.paused ? '#94a3b8' : '#f1f5f9';
      ctx.fillText(this.name, this.x, this.y + 42);

      // State Line
      const displayState = this.paused ? 'PAUSED' : this.stateText;
      ctx.font = '600 8px "JetBrains Mono", monospace';
      if (this.paused) {
        ctx.fillStyle = '#f87171';
      } else if (displayState.startsWith('FILL') || displayState.startsWith('APPROVED')) {
        ctx.fillStyle = '#22c55e';
      } else if (displayState.startsWith('LOCK')) {
        ctx.fillStyle = '#f5c869';
      } else if (this.isNeon) {
        ctx.fillStyle = '#22d3ee';
      } else {
        ctx.fillStyle = '#94a3b8';
      }
      ctx.fillText(displayState, this.x, this.y + 53);

      // Tabular PnL + Gate/WR Readout Tag (Unboxed)
      const subTag = this.isNeon
        ? `${this.pnlText} · ${this.getPassedGateCount()}/6G`
        : `${this.pnlText} · ${this.winRateText}`;
      ctx.font = '600 8px "JetBrains Mono", monospace';
      ctx.fillStyle = this.paused ? '#64748b' : this.pnlPositive ? '#34d399' : '#f87171';
      ctx.fillText(subTag, this.x, this.y + 64);

      ctx.restore();
    }
  }

  // --- 5. BEACON (BINANCE ASSET CANDIDATE) ---
  class Beacon {
    constructor(data) {
      this.id = data.id || 'sig-' + Math.floor(Math.random() * 1000);
      this.symbol = data.symbol || 'SOL/USDT';
      this.score = typeof data.score === 'number' ? data.score : 0.75;
      this.xNorm = data.xNorm ?? 0.5;
      this.yNorm = data.yNorm ?? 0.5;
      this.worldX = 0;
      this.worldY = 0;
      this.isDragged = false;
      this.status = data.status || (this.score >= 0.62 ? 'LOCKED' : 'PEEKING');
      this.life = 1.0;
      this.ttl = 8.0;
      this.pulse = 0;
      this.strikeAnim = 0;
    }

    update(dt, w, h) {
      if (!this.isDragged) {
        this.worldX = this.xNorm * w;
        this.worldY = this.yNorm * h;
      }
      this.pulse += dt * 3.5;
      this.ttl -= dt * simulationPace;
      if (this.status === 'SKIPPED') {
        this.life = Math.max(0, this.life - dt * 1.5);
      } else if (this.status === 'CAPTURED') {
        this.strikeAnim = Math.min(1.0, this.strikeAnim + dt * 3);
        this.life = Math.max(0, this.life - dt * 2.0);
      } else {
        this.life = Math.min(1.0, this.ttl / 2.0);
      }
    }

    draw(ctx) {
      const px = this.worldX;
      const py = this.worldY;
      const alpha = Math.max(0, Math.min(1, this.life));

      ctx.save();
      ctx.globalAlpha = alpha;

      let col = '#38bdf8';
      if (this.status === 'LOCKED') col = '#f5c869';
      if (this.status === 'SKIPPED') col = '#ef4444';
      if (this.status === 'CAPTURED') col = '#34d399';

      if (this.status === 'LOCKED' || this.status === 'CAPTURED') {
        const ringR = 11 + (Math.sin(this.pulse) + 1) * 3.5;
        ctx.beginPath();
        ctx.arc(px, py, ringR, 0, Math.PI * 2);
        ctx.strokeStyle = col;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      const sz = 7.5;
      ctx.beginPath();
      ctx.moveTo(px, py - sz);
      ctx.lineTo(px + sz, py);
      ctx.lineTo(px, py + sz);
      ctx.lineTo(px - sz, py);
      ctx.closePath();
      ctx.fillStyle = 'rgba(11, 15, 24, 0.92)';
      ctx.strokeStyle = col;
      ctx.lineWidth = 1.5;
      ctx.shadowColor = col;
      ctx.shadowBlur = 8;
      ctx.fill();
      ctx.stroke();
      ctx.shadowBlur = 0;

      ctx.font = '600 8px "JetBrains Mono", monospace';
      ctx.fillStyle = col;
      ctx.textAlign = 'center';
      ctx.fillText(this.symbol, px, py - 11);

      ctx.font = '500 7.5px "JetBrains Mono", monospace';
      ctx.fillStyle = '#cbd5e1';
      ctx.fillText((this.score * 100).toFixed(0) + '%', px, py + 15);

      ctx.restore();
    }
  }

  // --- 6. TOPOLOGY, CONSTELLATION GEOMETRY & FLEET ROSTER ---
  function initBots(count) {
    const validCount = count === 3 || count === 4 ? count : 6;
    botsCount = validCount;
    const prevPaused = new Map(bots.map((b) => [b.id, b.paused]));

    const cfgList = validCount === 3 ? DEFAULT_BOTS_3 : validCount === 4 ? DEFAULT_BOTS_4 : DEFAULT_BOTS_6;
    bots = cfgList.map((cfg) => {
      const node = new BotNode(cfg, 0, 0);
      if (prevPaused.has(node.id)) {
        node.paused = Boolean(prevPaused.get(node.id));
      }
      return node;
    });

    // Re-apply cached live NEON telemetry immediately if available
    if (cachedNeonOverview || cachedNeonEquity) {
      applyNeonTelemetryToBots(cachedNeonOverview, cachedNeonEquity);
    }

    // If selected bot was removed by shrinking fleet, close inspector
    if (selectedBotId && !bots.some((b) => b.id === selectedBotId)) {
      closeInspector();
    }

    updateFleetControlsUI();
    updateSwarmSummary();
    renderFleetRoster();
    renderInspector();
  }

  function updateFleetControlsUI() {
    [6, 4, 3].forEach((n) => {
      const btn = document.getElementById(`btnFleet${n}`);
      if (btn) btn.classList.toggle('active', botsCount === n);
    });
  }

  function updateSwarmSummary() {
    const activeCount = bots.filter((b) => !b.paused).length;
    const workersCount = bots.length * 6;
    const summaryEl = document.getElementById('swarmSummary');
    if (summaryEl) {
      const pausedSuffix = activeCount < bots.length ? ` · ${bots.length - activeCount} paused` : '';
      summaryEl.textContent = `${bots.length} bots · ${workersCount} agent workers${pausedSuffix}`;
    }

    const topbarText = document.getElementById('topbar-swarm-pill-text');
    if (topbarText) {
      topbarText.textContent = `${bots.length} BOTS · ${workersCount} WORKERS`;
    }
    const topbarPill = document.getElementById('topbar-swarm-pill');
    if (topbarPill) {
      topbarPill.title = `Click to focus Neural Swarm Deck (${bots.length} Bots · ${workersCount} Agent Workers)`;
    }
  }

  function getConstellationCoords(w, h, count) {
    if (count === 3) {
      return [
        { x: w * 0.50, y: h * 0.30 },
        { x: w * 0.27, y: h * 0.68 },
        { x: w * 0.73, y: h * 0.68 }
      ];
    }
    if (count === 4) {
      return [
        { x: w * 0.28, y: h * 0.31 },
        { x: w * 0.72, y: h * 0.31 },
        { x: w * 0.28, y: h * 0.69 },
        { x: w * 0.72, y: h * 0.69 }
      ];
    }
    // Balanced 3x2 Constellation for 6 Bots (with unobstructed breathing room for 36 workers)
    return [
      { x: w * 0.19, y: h * 0.29 },
      { x: w * 0.50, y: h * 0.29 },
      { x: w * 0.81, y: h * 0.29 },
      { x: w * 0.19, y: h * 0.70 },
      { x: w * 0.50, y: h * 0.70 },
      { x: w * 0.81, y: h * 0.70 }
    ];
  }

  function renderFleetRoster() {
    const bar = document.getElementById('swarmRosterBar');
    if (!bar) return;

    bar.className = `swarm-roster-bar fleet-${bots.length}`;
    bar.innerHTML = bots
      .map((bot) => {
        const isSelected = selectedBotId === bot.id;
        const stateLabel = bot.paused
          ? 'PAUSED'
          : bot.stateText.startsWith('APPROVED') || bot.stateText.startsWith('FILL')
          ? 'ACTIVE'
          : bot.stateText.startsWith('LOCK')
          ? 'LOCKED'
          : bot.isNeon
          ? `${bot.getPassedGateCount()}/6G`
          : 'HUNTING';

        const stateCls = bot.paused
          ? 'state-paused'
          : stateLabel === 'ACTIVE'
          ? 'state-live'
          : stateLabel === 'LOCKED'
          ? 'state-lock'
          : '';

        const metricColor = bot.paused ? '' : bot.pnlPositive ? 'text-pos' : 'text-neg';

        return `<div class="swarm-roster-cell ${isSelected ? 'selected' : ''} ${bot.paused ? 'paused' : ''}" role="listitem" data-bot-id="${bot.id}" style="--bot-accent: ${bot.accent};">
          <div class="roster-top">
            <span class="roster-name-wrap">
              <span class="roster-swatch"></span>
              <span class="roster-name">${bot.id} · ${bot.name}</span>
            </span>
            <span class="roster-state ${stateCls}">${stateLabel}</span>
          </div>
          <div class="roster-mid">
            <span class="roster-role">${bot.role}</span>
            <span class="roster-metric ${metricColor}">${bot.pnlText}</span>
          </div>
          <div class="roster-actions">
            <button type="button" class="roster-btn" data-action="focus" data-bot-id="${bot.id}">Focus</button>
            <button type="button" class="roster-btn ${bot.paused ? 'is-paused' : ''}" data-action="pause" data-bot-id="${bot.id}">${bot.paused ? 'Resume' : 'Pause'}</button>
          </div>
        </div>`;
      })
      .join('');
  }

  // --- 7. BOT INSPECTOR DRAWER & CAMERA FOCUS ---
  function selectBot(botId) {
    const bot = bots.find((b) => b.id === botId);
    if (!bot) {
      closeInspector();
      return;
    }
    selectedBotId = bot.id;
    const drawer = document.getElementById('swarmInspector');
    if (drawer) {
      drawer.classList.add('open');
      drawer.setAttribute('aria-hidden', 'false');
    }
    renderInspector();
    renderFleetRoster();
  }

  function closeInspector() {
    selectedBotId = null;
    const drawer = document.getElementById('swarmInspector');
    if (drawer) {
      drawer.classList.remove('open');
      drawer.setAttribute('aria-hidden', 'true');
    }
    renderFleetRoster();
  }

  function renderInspector() {
    const drawer = document.getElementById('swarmInspector');
    if (!drawer || !selectedBotId) return;
    const bot = bots.find((b) => b.id === selectedBotId);
    if (!bot) {
      closeInspector();
      return;
    }

    const setEl = (id, text) => {
      const el = document.getElementById(id);
      if (el) el.textContent = text;
    };

    setEl('inspectorKicker', `${bot.id} · ${bot.name}${bot.paused ? ' (PAUSED)' : ''}`);
    const kicker = document.getElementById('inspectorKicker');
    if (kicker) kicker.style.color = bot.paused ? '#94a3b8' : bot.accent;

    setEl('inspectorRole', `${bot.role} · ${bot.stateText}`);
    setEl('inspectorPair', bot.pair);

    const pnlEl = document.getElementById('inspectorPnl');
    if (pnlEl) {
      pnlEl.textContent = bot.pnlText;
      pnlEl.className = `inspector-metric-val ${bot.pnlPositive ? 'text-pos' : 'text-neg'}`;
    }

    setEl(
      'inspectorWinRate',
      bot.isNeon && bot.convictionPct > 0 ? `${bot.winRateText} · ${bot.convictionPct}%` : bot.winRateText
    );

    const gatesTitle = document.getElementById('inspectorGatesTitle');
    const gatesSummary = document.getElementById('inspectorGatesSummary');
    const gatesList = document.getElementById('inspectorGatesList');

    if (gatesTitle) {
      gatesTitle.textContent = bot.isNeon ? '6 Institutional NEON Gates' : '6 Satellite Worker Stages';
    }
    if (gatesSummary) {
      gatesSummary.textContent = bot.isNeon ? `${bot.getPassedGateCount()} / 6 Passed` : bot.paused ? 'Paused' : '6 / 6 Active';
    }

    if (gatesList) {
      gatesList.innerHTML = bot.gates
        .map((g) => {
          const stCls = bot.paused ? 'idle' : g.passed ? 'pass' : 'fail';
          const stTxt = bot.paused ? 'PAUSED' : bot.isNeon ? (g.passed ? 'PASS' : 'GATED') : 'ACTIVE';
          return `<div class="inspector-gate-row">
            <div class="inspector-gate-left">
              <span class="inspector-gate-name">${g.label}</span>
              <span class="inspector-gate-detail" title="${g.detail}">${g.detail}</span>
            </div>
            <span class="inspector-gate-state ${stCls}">${stTxt}</span>
          </div>`;
        })
        .join('');
    }

    // Active Exact-Decimal Bracket Blueprint (when present on NEON-5 / NEON-6)
    const bracketBox = document.getElementById('inspectorBracketBox');
    const bracketSide = document.getElementById('inspectorBracketSide');
    const bracketGrid = document.getElementById('inspectorBracketGrid');
    if (bracketBox && bracketGrid) {
      if (bot.bracket) {
        const t = bot.bracket;
        bracketBox.style.display = 'flex';
        if (bracketSide) {
          bracketSide.textContent = `${t.side} · ${t.notional_usd ? `$${Number(t.notional_usd).toFixed(0)}` : '2.0R'}`;
          bracketSide.style.color = t.side === 'LONG' ? '#22c55e' : '#f87171';
        }
        bracketGrid.innerHTML = `
          <div class="inspector-bracket-cell"><span>Entry</span><strong>${fmtPrice(t.entry_price)}</strong></div>
          <div class="inspector-bracket-cell"><span>BE Lock</span><strong>${fmtPrice(t.be_lock_price)}</strong></div>
          <div class="inspector-bracket-cell"><span>Stop Loss</span><strong class="text-neg">${fmtPrice(t.stop_loss)}</strong></div>
          <div class="inspector-bracket-cell"><span>Take Profit</span><strong class="text-pos">${fmtPrice(t.take_profit)}</strong></div>
        `;
      } else {
        bracketBox.style.display = 'none';
      }
    }

    const pauseBtn = document.getElementById('btnInspectorPause');
    if (pauseBtn) {
      pauseBtn.textContent = bot.paused ? 'Resume Bot' : 'Pause Bot';
      pauseBtn.classList.toggle('accent-alpha', bot.paused);
    }

    const openNeonBtn = document.getElementById('btnInspectorOpenNeon');
    const syncNeonBtn = document.getElementById('btnInspectorSyncNeon');
    if (openNeonBtn) openNeonBtn.style.display = bot.isNeon ? 'inline-flex' : 'none';
    if (syncNeonBtn) syncNeonBtn.style.display = bot.isNeon ? 'inline-flex' : 'none';
  }

  function focusBot(botId) {
    const bot = bots.find((b) => b.id === botId);
    if (!bot || !canvas) return;
    selectBot(bot.id);

    const rect = canvas.getBoundingClientRect();
    const cssW = rect.width || 900;
    const cssH = rect.height || 430;
    // Offset horizontal center slightly left when inspector drawer is open on desktop
    const drawerOffset = cssW > 760 ? 160 : 0;
    const targetZoom = 1.38;
    const centerX = (cssW - drawerOffset) * 0.5;
    const centerY = cssH * 0.5;

    cameraTarget = {
      zoom: targetZoom,
      panX: centerX - bot.x * targetZoom,
      panY: centerY - bot.y * targetZoom
    };
  }

  function toggleBotPaused(botId, forcedState) {
    const bot = bots.find((b) => b.id === botId);
    if (!bot) return;
    bot.paused = typeof forcedState === 'boolean' ? forcedState : !bot.paused;
    updateSwarmSummary();
    renderFleetRoster();
    if (selectedBotId === bot.id) {
      renderInspector();
    }
  }

  // --- 8. LIVE NEON TELEMETRY SYNC FOR BOT-05 & BOT-06 ---
  function applyNeonTelemetryToBots(overview, equityPayload) {
    const bot5 = bots.find((b) => b.id === 'BOT-05');
    const bot6 = bots.find((b) => b.id === 'BOT-06');
    if (!bot5 && !bot6) return;

    const evals = (overview && overview.live_scanner && Array.isArray(overview.live_scanner.evaluations))
      ? overview.live_scanner.evaluations
      : [];
    const sortedEvals = [...evals].sort((a, b) => {
      if (Boolean(b.approved) !== Boolean(a.approved)) return b.approved ? 1 : -1;
      return (b.conviction_pct || 0) - (a.conviction_pct || 0);
    });

    const topEval = sortedEvals[0] || null;
    const makerEval =
      sortedEvals.find((ev) => ev.ticket && (!topEval || ev.symbol !== topEval.symbol)) ||
      sortedEvals[1] ||
      topEval;

    const eqSummary = equityPayload && equityPayload.summary ? equityPayload.summary : null;
    const auditNeon = overview && overview.forensic_audit && overview.forensic_audit.neon_counterfactual
      ? overview.forensic_audit.neon_counterfactual
      : null;

    if (bot5) {
      if (topEval) {
        bot5.pair = fmtPair(topEval.symbol);
        bot5.convictionPct = Number(topEval.conviction_pct || 0);
        bot5.vetoReason = topEval.veto_reason || '';
        bot5.bracket = topEval.ticket || null;
        if (Array.isArray(topEval.gates) && topEval.gates.length === 6) {
          bot5.gates = topEval.gates.map((g) => ({
            key: g.gate,
            label: g.gate,
            passed: Boolean(g.passed),
            detail: g.detail || ''
          }));
        }
        bot5.stateText = topEval.approved
          ? `APPROVED · ${topEval.side}`
          : `${bot5.getPassedGateCount()}/6 GATES · ${bot5.pair.split('/')[0]}`;
      }
      if (eqSummary) {
        bot5.pnlText = fmtUsd(eqSummary.neon_final_pnl_usd, true);
        bot5.pnlPositive = Number(eqSummary.neon_final_pnl_usd) >= 0;
        bot5.winRateText = `${eqSummary.win_rate_pct}% WR`;
      }
    }

    if (bot6) {
      if (makerEval) {
        bot6.pair = fmtPair(makerEval.symbol);
        bot6.convictionPct = Number(makerEval.conviction_pct || 0);
        bot6.vetoReason = makerEval.veto_reason || '';
        bot6.bracket = makerEval.ticket || null;
        if (Array.isArray(makerEval.gates) && makerEval.gates.length === 6) {
          bot6.gates = makerEval.gates.map((g) => ({
            key: g.gate,
            label: g.gate,
            passed: Boolean(g.passed),
            detail: g.detail || ''
          }));
        }
        bot6.stateText = makerEval.approved
          ? `MAKER 2bps · READY`
          : `ARBITER · ${bot6.getPassedGateCount()}/6G`;
      }
      if (auditNeon) {
        bot6.pnlText = fmtUsd(auditNeon.net_pnl_usd, true);
        bot6.pnlPositive = Number(auditNeon.net_pnl_usd) >= 0;
        bot6.winRateText = `${auditNeon.win_rate_pct}% WR`;
      }
    }

    renderFleetRoster();
    renderInspector();
  }

  async function syncNeonTelemetry() {
    const labelEl = document.getElementById('swarmNeonSyncLabel');
    if (typeof window.axios === 'undefined') return;

    try {
      const [ovRes, eqRes] = await Promise.all([
        window.axios.get('/api/neon/overview', { timeout: 9000 }),
        window.axios.get('/api/neon/equity-curve', {
          params: { scope: 'CORE_BASKET', mirror_bull: 'false', initial_equity: 200 },
          timeout: 9000
        })
      ]);

      const overview = ovRes && ovRes.data && ovRes.data.success ? ovRes.data : null;
      const equityPayload = eqRes && eqRes.data && eqRes.data.success ? eqRes.data.equity_curve : null;

      if (!overview && !equityPayload) {
        throw new Error('Empty NEON telemetry payload');
      }

      cachedNeonOverview = overview;
      cachedNeonEquity = equityPayload;
      applyNeonTelemetryToBots(overview, equityPayload);

      // Subtle worker pulse on NEON bots when live sync succeeds
      ['BOT-05', 'BOT-06'].forEach((id) => {
        const b = bots.find((x) => x.id === id);
        if (b && !b.paused) {
          b.workers.forEach((w, idx) => {
            if (b.gates[idx] && b.gates[idx].passed) {
              w.activePulse = 0.75;
            }
          });
        }
      });

      if (labelEl) {
        labelEl.classList.remove('standby');
        labelEl.textContent = `NEON Live · ${fmtUtcClock()}`;
      }
    } catch (err) {
      if (labelEl) {
        labelEl.classList.add('standby');
        labelEl.textContent = 'NEON Telemetry: Standby';
      }
    }
  }

  // --- 9. COORDINATE TRANSFORMATIONS & HIT TESTING ---
  function screenToWorld(sx, sy) {
    return {
      x: (sx - panX) / zoom,
      y: (sy - panY) / zoom
    };
  }

  function findHitBot(wx, wy) {
    for (let i = bots.length - 1; i >= 0; i--) {
      const b = bots[i];
      const dist = Math.hypot(wx - b.x, wy - b.y);
      if (dist <= b.radius + 16) {
        return b;
      }
    }
    return null;
  }

  function findHitBeacon(wx, wy) {
    for (const b of beacons.values()) {
      const dist = Math.hypot(wx - b.worldX, wy - b.worldY);
      if (dist <= 18) {
        return b;
      }
    }
    return null;
  }

  function resetView() {
    cameraTarget = { panX: 0, panY: 0, zoom: 1.0 };
    bots.forEach((b) => {
      b.isCustomPosition = false;
      b.isDragged = false;
    });
    if (canvas) {
      canvas.classList.remove('is-dragging', 'is-panning');
      canvas.style.cursor = 'grab';
    }
  }

  // --- 10. LIGHTNING EXECUTION STRIKE EFFECT ---
  function triggerLightningStrike(bot, beacon) {
    if (!canvas || bot.paused) return;
    const bx = beacon.worldX;
    const by = beacon.worldY;

    lightningStrikes.push({
      startX: bot.x,
      startY: bot.y,
      endX: bx,
      endY: by,
      color: bot.accent,
      life: 1.0,
      segments: createJaggedLine(bot.x, bot.y, bx, by)
    });

    for (let i = 0; i < 14; i++) {
      const ang = Math.random() * Math.PI * 2;
      const spd = 20 + Math.random() * 75;
      particles.push({
        x: bx,
        y: by,
        vx: Math.cos(ang) * spd,
        vy: Math.sin(ang) * spd,
        color: bot.accent,
        life: 0.75
      });
    }
  }

  function createJaggedLine(x1, y1, x2, y2) {
    const pts = [{ x: x1, y: y1 }];
    const steps = 6;
    for (let i = 1; i < steps; i++) {
      const t = i / steps;
      const lx = x1 + (x2 - x1) * t;
      const ly = y1 + (y2 - y1) * t;
      const offset = (Math.random() - 0.5) * 22;
      pts.push({ x: lx + offset, y: ly + offset });
    }
    pts.push({ x: x2, y: y2 });
    return pts;
  }

  // --- 11. BOTSWARM BRIDGE API ---
  window.BotSwarmBridge = {
    setTopology: function (data) {
      if (!data || !data.bots || !Array.isArray(data.bots)) return;
      bots = data.bots.map((b) => new BotNode(b, 0, 0));
      botsCount = bots.length;
      updateFleetControlsUI();
      updateSwarmSummary();
      renderFleetRoster();
      renderInspector();
    },

    setFleetSize: function (count) {
      initBots(Number(count));
    },

    focusBot: focusBot,
    selectBot: selectBot,
    setBotPaused: toggleBotPaused,
    syncNeonTelemetry: syncNeonTelemetry,

    upsertBeacon: function (beaconData) {
      if (!beaconData || !beaconData.id) return;
      let b = beacons.get(beaconData.id);
      if (!b) {
        b = new Beacon(beaconData);
        beacons.set(beaconData.id, b);
      } else {
        b.symbol = beaconData.symbol || b.symbol;
        b.score = typeof beaconData.score === 'number' ? beaconData.score : b.score;
        b.xNorm = beaconData.xNorm ?? b.xNorm;
        b.yNorm = beaconData.yNorm ?? b.yNorm;
        b.status = beaconData.status || b.status;
        b.ttl = 8.0;
      }

      const activeBots = bots.filter((bot) => !bot.paused);
      if (b.status === 'LOCKED' && activeBots.length > 0) {
        let chosenBot = activeBots[0];
        let minDist = Infinity;
        activeBots.forEach((bot) => {
          const d = Math.hypot(bot.x - b.worldX, bot.y - b.worldY);
          if (d < minDist) {
            minDist = d;
            chosenBot = bot;
          }
        });
        chosenBot.stateText = `LOCK · ${b.symbol.split('/')[0]}`;
        chosenBot.stateTime = 3.0;
        chosenBot.lockedBeaconId = b.id;
        triggerLightningStrike(chosenBot, b);
      }
    },

    emitWorkerSignal: function (signal) {
      if (!signal || !signal.botId || !signal.workerId) return;
      const bot = bots.find((b) => b.id === signal.botId);
      if (!bot || bot.paused) return;

      const worker = bot.workers.find((w) => w.id === signal.workerId);
      if (worker) {
        worker.currentPill = signal.label || `• ${signal.state || 'ACTIVE'}`;
        worker.pillTime = 2.4;
        worker.activePulse = 1.0;
      }
    },

    emitTradeFill: function (fill) {
      if (!fill || !fill.symbol) return;
      const bot = bots.find((b) => b.id === fill.botId && !b.paused) || bots.find((b) => !b.paused);
      if (bot) {
        bot.stateText = `FILL · ${fill.pnl || '+1.00%'}`;
        bot.stateTime = 3.8;
      }
      const b = beacons.get(fill.beaconId);
      if (b) {
        b.status = 'CAPTURED';
      }
    },

    resetView: resetView
  };

  // --- 12. WEBSOCKET TELEMETRY CLIENT ---
  function connectWebSocket(customUrl) {
    if (wsSocket) {
      try { wsSocket.close(); } catch (e) {}
    }

    const targetUrl = customUrl || wsUrl;
    setModeBadge('connecting', 'CONNECTING');

    try {
      wsSocket = new WebSocket(targetUrl);

      wsSocket.onopen = function () {
        isLiveWS = true;
        setModeBadge('live', 'LIVE WS');
      };

      wsSocket.onmessage = function (event) {
        try {
          const envelope = JSON.parse(event.data);
          const type = envelope.type;
          const payload = envelope.payload;

          if (type === 'TOPOLOGY') {
            window.BotSwarmBridge.setTopology(payload);
          } else if (type === 'BEACON_UPSERT') {
            window.BotSwarmBridge.upsertBeacon(payload);
          } else if (type === 'WORKER_SIGNAL') {
            window.BotSwarmBridge.emitWorkerSignal(payload);
          } else if (type === 'TRADE_FILL') {
            window.BotSwarmBridge.emitTradeFill(payload);
          }
        } catch (err) {
          console.warn('[BotSwarmBridge] Error parsing WS envelope:', err);
        }
      };

      wsSocket.onerror = function () {
        isLiveWS = false;
        setModeBadge('demo', 'DEMO SIM');
      };

      wsSocket.onclose = function () {
        isLiveWS = false;
        setModeBadge('demo', 'DEMO SIM');
      };
    } catch (e) {
      isLiveWS = false;
      setModeBadge('demo', 'DEMO SIM');
    }
  }

  function setModeBadge(mode, text) {
    const badge = document.getElementById('modeBadge');
    const label = document.getElementById('modeText');
    if (!badge || !label) return;
    badge.className = 'mode-badge ' + mode;
    label.textContent = text;
  }

  // --- 13. AUTONOMOUS DEMO SIMULATION (WHEN WS IDLE) ---
  function runDemoSimulationStep(dt) {
    if (isLiveWS) return;
    const activeBots = bots.filter((b) => !b.paused);
    if (!activeBots.length) return;

    demoTimer += dt * simulationPace;
    if (demoTimer > 2.3) {
      demoTimer = 0;

      const asset = CANDIDATE_ASSETS[Math.floor(Math.random() * CANDIDATE_ASSETS.length)];
      const sym = `${asset}/USDT`;
      const id = `demo-${asset.toLowerCase()}`;
      const score = Math.random() > 0.35 ? +(0.64 + Math.random() * 0.33).toFixed(2) : +(0.35 + Math.random() * 0.24).toFixed(2);
      const isLock = score >= 0.62;

      const xN = +(0.12 + Math.random() * 0.76).toFixed(2);
      const yN = +(0.16 + Math.random() * 0.68).toFixed(2);

      window.BotSwarmBridge.upsertBeacon({
        id: id,
        symbol: sym,
        score: score,
        xNorm: xN,
        yNorm: yN,
        status: isLock ? 'LOCKED' : 'SKIPPED'
      });

      const targetBot = activeBots[Math.floor(Math.random() * activeBots.length)];
      if (isLock) {
        const scanLabel = targetBot.isNeon
          ? `• 6-gate adx ${(19 + Math.random() * 14).toFixed(0)}`
          : `• cvd +${(2.0 + Math.random() * 2.4).toFixed(1)}σ`;

        window.BotSwarmBridge.emitWorkerSignal({
          botId: targetBot.id,
          workerId: 'SCAN',
          beaconId: id,
          state: 'TRIANGULATING',
          label: scanLabel
        });

        setTimeout(() => {
          window.BotSwarmBridge.emitWorkerSignal({
            botId: targetBot.id,
            workerId: 'EXEC',
            beaconId: id,
            state: 'LOCK',
            label: targetBot.isNeon ? '• maker 2bps' : '• limit lock'
          });
        }, 550);

        setTimeout(() => {
          if (Math.random() > 0.4) {
            window.BotSwarmBridge.emitTradeFill({
              botId: targetBot.id,
              beaconId: id,
              symbol: sym,
              side: 'BUY',
              pnl: `+${(0.75 + Math.random() * 1.45).toFixed(2)}%`
            });
          }
        }, 1350);
      } else {
        window.BotSwarmBridge.emitWorkerSignal({
          botId: targetBot.id,
          workerId: 'RISK',
          beaconId: id,
          state: 'VETO',
          label: targetBot.isNeon ? '• gate veto' : '• skip noise'
        });
      }
    }
  }

  // --- 14. POINTER INTERACTION (CLICK TO INSPECT, DRAG BOT/BEACON, PAN/ZOOM) ---
  function setupPanAndDrag() {
    function getPointerPos(e) {
      const rect = canvas.getBoundingClientRect();
      const touch = e.touches && e.touches[0] ? e.touches[0] : (e.changedTouches && e.changedTouches[0] ? e.changedTouches[0] : null);
      const clientX = touch ? touch.clientX : e.clientX;
      const clientY = touch ? touch.clientY : e.clientY;
      const sx = clientX - rect.left;
      const sy = clientY - rect.top;
      const wpos = screenToWorld(sx, sy);
      return { sx, sy, wx: wpos.x, wy: wpos.y };
    }

    function onPointerDown(e) {
      if (!canvas) return;
      cameraTarget = null; // manual interaction cancels smooth camera lerp
      const { sx, sy, wx, wy } = getPointerPos(e);
      pointerDownScreen = { x: sx, y: sy };
      pointerDragMoved = false;

      const hitBot = findHitBot(wx, wy);
      if (hitBot) {
        draggedBot = hitBot;
        draggedBot.isDragged = true;
        dragOffset = { x: wx - hitBot.x, y: wy - hitBot.y };
        canvas.classList.add('is-dragging');
        canvas.style.cursor = 'grabbing';
        return;
      }

      const hitBeacon = findHitBeacon(wx, wy);
      if (hitBeacon) {
        draggedBeacon = hitBeacon;
        draggedBeacon.isDragged = true;
        dragOffset = { x: wx - hitBeacon.worldX, y: wy - hitBeacon.worldY };
        canvas.classList.add('is-dragging');
        canvas.style.cursor = 'grabbing';
        return;
      }

      isPanning = true;
      panStart = { x: sx - panX, y: sy - panY };
      canvas.classList.add('is-panning');
      canvas.style.cursor = 'grabbing';
    }

    function onPointerMove(e) {
      if (!canvas) return;
      const { sx, sy, wx, wy } = getPointerPos(e);

      if (draggedBot || draggedBeacon || isPanning) {
        if (Math.hypot(sx - pointerDownScreen.x, sy - pointerDownScreen.y) >= 5) {
          pointerDragMoved = true;
        }
      }

      if (draggedBot) {
        if (pointerDragMoved) {
          if (e.cancelable && e.touches) e.preventDefault();
          draggedBot.isCustomPosition = true;
          draggedBot.x = wx - dragOffset.x;
          draggedBot.y = wy - dragOffset.y;
          draggedBot.updateWorkers(0);
        }
        return;
      }

      if (draggedBeacon) {
        if (e.cancelable && e.touches) e.preventDefault();
        draggedBeacon.worldX = wx - dragOffset.x;
        draggedBeacon.worldY = wy - dragOffset.y;
        const rect = canvas.getBoundingClientRect();
        draggedBeacon.xNorm = draggedBeacon.worldX / (rect.width || 1);
        draggedBeacon.yNorm = draggedBeacon.worldY / (rect.height || 1);
        return;
      }

      if (isPanning) {
        if (e.cancelable && e.touches) e.preventDefault();
        panX = sx - panStart.x;
        panY = sy - panStart.y;
        return;
      }

      const hitBot = findHitBot(wx, wy);
      const hitBeacon = findHitBeacon(wx, wy);
      if (hitBot !== hoveredBot || hitBeacon !== hoveredBeacon) {
        hoveredBot = hitBot;
        hoveredBeacon = hitBeacon;
        canvas.style.cursor = hitBot ? 'pointer' : hitBeacon ? 'grab' : 'grab';
      }
    }

    function onPointerUp() {
      if (draggedBot) {
        const clickedBot = draggedBot;
        draggedBot.isDragged = false;
        draggedBot = null;
        // Click (<5px move) opens Inspector Drawer without locking custom position
        if (!pointerDragMoved) {
          selectBot(clickedBot.id);
        }
      } else if (isPanning && !pointerDragMoved && selectedBotId) {
        // Clicking empty canvas space dismisses Inspector Drawer
        closeInspector();
      }

      if (draggedBeacon) {
        draggedBeacon.isDragged = false;
        draggedBeacon = null;
      }

      isPanning = false;
      if (canvas) {
        canvas.classList.remove('is-dragging', 'is-panning');
        canvas.style.cursor = hoveredBot ? 'pointer' : 'grab';
      }
    }

    function onWheel(e) {
      e.preventDefault();
      cameraTarget = null;
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;

      const zoomFactor = e.deltaY < 0 ? 1.08 : 0.92;
      const newZoom = Math.max(0.45, Math.min(2.4, zoom * zoomFactor));

      panX = sx - (sx - panX) * (newZoom / zoom);
      panY = sy - (sy - panY) * (newZoom / zoom);
      zoom = newZoom;
    }

    function onDblClick() {
      resetView();
    }

    canvas.addEventListener('mousedown', onPointerDown);
    window.addEventListener('mousemove', onPointerMove);
    window.addEventListener('mouseup', onPointerUp);
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('dblclick', onDblClick);

    canvas.addEventListener('touchstart', onPointerDown, { passive: true });
    window.addEventListener('touchmove', onPointerMove, { passive: false });
    window.addEventListener('touchend', onPointerUp);
  }

  // --- 15. MAIN ANIMATION & RENDER LOOP ---
  function render(time) {
    if (!isRunning) return;

    if (document.visibilityState === 'hidden') {
      animFrameId = requestAnimationFrame(render);
      return;
    }

    const dt = Math.min(0.1, (time - lastTime) / 1000);
    lastTime = time;

    // Smooth camera focus interpolation
    if (cameraTarget) {
      const ease = Math.min(1, dt * 10);
      panX += (cameraTarget.panX - panX) * ease;
      panY += (cameraTarget.panY - panY) * ease;
      zoom += (cameraTarget.zoom - zoom) * ease;
      if (
        Math.abs(cameraTarget.panX - panX) < 0.5 &&
        Math.abs(cameraTarget.panY - panY) < 0.5 &&
        Math.abs(cameraTarget.zoom - zoom) < 0.004
      ) {
        panX = cameraTarget.panX;
        panY = cameraTarget.panY;
        zoom = cameraTarget.zoom;
        cameraTarget = null;
      }
    }

    const rect = canvas.getBoundingClientRect();
    const cssW = rect.width;
    const cssH = rect.height;

    if (cssW <= 0 || cssH <= 0) {
      animFrameId = requestAnimationFrame(render);
      return;
    }

    const dpr = window.devicePixelRatio || 1;
    const targetW = Math.round(cssW * dpr);
    const targetH = Math.round(cssH * dpr);
    if (canvas.width !== targetW || canvas.height !== targetH) {
      canvas.width = targetW;
      canvas.height = targetH;
    }

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    ctx.save();
    ctx.translate(panX, panY);
    ctx.scale(zoom, zoom);

    // Subtle Radar Coordinate Grid
    const gridMax = Math.max(cssW, cssH) * 2;
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.04)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(cssW * 0.5, -gridMax);
    ctx.lineTo(cssW * 0.5, gridMax);
    ctx.moveTo(-gridMax, cssH * 0.5);
    ctx.lineTo(gridMax, cssH * 0.5);
    ctx.arc(cssW * 0.5, cssH * 0.5, cssW * 0.21, 0, Math.PI * 2);
    ctx.arc(cssW * 0.5, cssH * 0.5, cssW * 0.42, 0, Math.PI * 2);
    ctx.stroke();

    // Subtle Neural Link Line between BOT-05 (NEON-5) & BOT-06 (NEON-6) when both active
    const b5 = bots.find((b) => b.id === 'BOT-05');
    const b6 = bots.find((b) => b.id === 'BOT-06');
    if (b5 && b6) {
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(b5.x, b5.y);
      ctx.lineTo(b6.x, b6.y);
      ctx.strokeStyle = b5.paused || b6.paused ? 'rgba(100, 116, 139, 0.14)' : 'rgba(34, 211, 238, 0.18)';
      ctx.lineWidth = 1.2;
      ctx.setLineDash([4, 6]);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
    }

    // 1. Update & Draw Bots
    const coords = getConstellationCoords(cssW, cssH, bots.length);
    bots.forEach((b, i) => {
      if (coords[i]) {
        b.update(dt, coords[i].x, coords[i].y);
        b.draw(ctx);
      }
    });

    // 2. Update & Draw Beacons
    for (const [id, b] of beacons.entries()) {
      b.update(dt, cssW, cssH);
      if (b.life <= 0) {
        beacons.delete(id);
      } else {
        b.draw(ctx);
      }
    }

    // 3. Update & Draw Lightning Strikes
    for (let i = lightningStrikes.length - 1; i >= 0; i--) {
      const strike = lightningStrikes[i];
      strike.life -= dt * 3.5;
      if (strike.life <= 0) {
        lightningStrikes.splice(i, 1);
        continue;
      }
      ctx.save();
      ctx.globalAlpha = Math.max(0, strike.life);
      ctx.beginPath();
      strike.segments.forEach((pt, idx) => {
        if (idx === 0) ctx.moveTo(pt.x, pt.y);
        else ctx.lineTo(pt.x, pt.y);
      });
      ctx.strokeStyle = strike.color;
      ctx.lineWidth = 2.2;
      ctx.shadowColor = strike.color;
      ctx.shadowBlur = 12;
      ctx.stroke();
      ctx.restore();
    }

    // 4. Update & Draw Particles
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.life -= dt * 2.0;
      if (p.life <= 0) {
        particles.splice(i, 1);
        continue;
      }
      ctx.beginPath();
      ctx.arc(p.x, p.y, 2, 0, Math.PI * 2);
      ctx.fillStyle = p.color;
      ctx.globalAlpha = Math.max(0, p.life);
      ctx.fill();
    }

    ctx.restore();

    // 5. Autonomous Demo Tick (when WS disconnected)
    runDemoSimulationStep(dt);

    animFrameId = requestAnimationFrame(render);
  }

  // --- 16. RESIZE HANDLER ---
  function resizeCanvas() {
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = rect.width || (canvas.parentElement ? canvas.parentElement.clientWidth : 0) || window.innerWidth || 1200;
    const h = rect.height || 430;
    if (w > 0 && h > 0) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
  }

  window.resizeSwarmCanvas = resizeCanvas;
  window.resetSwarmView = resetView;

  // --- 17. CONTROLS, ROSTER & INSPECTOR EVENT BINDING ---
  function setupControls() {
    // 1. Reset View
    const btnResetView = document.getElementById('btnResetView');
    if (btnResetView) btnResetView.addEventListener('click', resetView);

    // 2. Segmented Fleet Size Switcher (6 | 4 | 3)
    [6, 4, 3].forEach((n) => {
      const btn = document.getElementById(`btnFleet${n}`);
      if (btn) {
        btn.addEventListener('click', () => initBots(n));
      }
    });

    // 3. Drop Alpha Beacon
    const btnDropAlpha = document.getElementById('btnDropAlpha');
    if (btnDropAlpha) {
      btnDropAlpha.addEventListener('click', () => {
        const asset = CANDIDATE_ASSETS[Math.floor(Math.random() * CANDIDATE_ASSETS.length)];
        const id = 'alpha-' + Date.now();
        window.BotSwarmBridge.upsertBeacon({
          id: id,
          symbol: `${asset}/USDT`,
          score: 0.94,
          xNorm: +(0.15 + Math.random() * 0.70).toFixed(2),
          yNorm: +(0.18 + Math.random() * 0.64).toFixed(2),
          status: 'LOCKED'
        });
      });
    }

    // 4. Simulation Pace
    const btnPace = document.getElementById('btnPace');
    if (btnPace) {
      btnPace.addEventListener('click', () => {
        if (simulationPace === 1.0) simulationPace = 2.0;
        else if (simulationPace === 2.0) simulationPace = 0.5;
        else simulationPace = 1.0;
        btnPace.textContent = `Pace: ${simulationPace.toFixed(1)}x`;
      });
    }

    // 5. Roster Bar Event Delegation (Click card -> Inspect; Focus/Pause buttons)
    const rosterBar = document.getElementById('swarmRosterBar');
    if (rosterBar) {
      rosterBar.addEventListener('click', (e) => {
        const actionBtn = e.target.closest('button[data-action]');
        if (actionBtn) {
          e.stopPropagation();
          const botId = actionBtn.getAttribute('data-bot-id');
          const action = actionBtn.getAttribute('data-action');
          if (action === 'focus') focusBot(botId);
          else if (action === 'pause') toggleBotPaused(botId);
          return;
        }
        const cell = e.target.closest('.swarm-roster-cell[data-bot-id]');
        if (cell) {
          selectBot(cell.getAttribute('data-bot-id'));
        }
      });
    }

    // 6. Bot Inspector Drawer Actions
    const btnCloseInspector = document.getElementById('btnCloseInspector');
    if (btnCloseInspector) btnCloseInspector.addEventListener('click', closeInspector);

    const btnInspectorFocus = document.getElementById('btnInspectorFocus');
    if (btnInspectorFocus) {
      btnInspectorFocus.addEventListener('click', () => {
        if (selectedBotId) focusBot(selectedBotId);
      });
    }

    const btnInspectorPause = document.getElementById('btnInspectorPause');
    if (btnInspectorPause) {
      btnInspectorPause.addEventListener('click', () => {
        if (selectedBotId) toggleBotPaused(selectedBotId);
      });
    }

    const btnInspectorSyncNeon = document.getElementById('btnInspectorSyncNeon');
    if (btnInspectorSyncNeon) {
      btnInspectorSyncNeon.addEventListener('click', () => syncNeonTelemetry());
    }

    const btnInspectorOpenNeon = document.getElementById('btnInspectorOpenNeon');
    if (btnInspectorOpenNeon) {
      btnInspectorOpenNeon.addEventListener('click', () => {
        if (typeof window.switchAppView === 'function') {
          window.switchAppView('neon');
        }
      });
    }

    // 7. Blueprint Modal Open/Close
    const btnBlueprint = document.getElementById('btnBlueprint');
    const modalBackdrop = document.getElementById('modalBackdrop');
    const btnCloseModal = document.getElementById('btnCloseModal');
    const modeBadge = document.getElementById('modeBadge');

    function openModal() {
      if (modalBackdrop) modalBackdrop.classList.add('open');
    }
    function closeModal() {
      if (modalBackdrop) modalBackdrop.classList.remove('open');
    }

    if (btnBlueprint) btnBlueprint.addEventListener('click', openModal);
    if (modeBadge) modeBadge.addEventListener('click', openModal);
    if (btnCloseModal) btnCloseModal.addEventListener('click', closeModal);
    if (modalBackdrop) {
      modalBackdrop.addEventListener('click', (e) => {
        if (e.target === modalBackdrop) closeModal();
      });
    }

    // ESC closes Modal or Inspector
    window.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      if (modalBackdrop && modalBackdrop.classList.contains('open')) {
        closeModal();
      } else if (selectedBotId) {
        closeInspector();
      }
    });

    // 8. Connect WS / Demo Mode
    const btnConnectWs = document.getElementById('btnConnectWs');
    const wsUrlInput = document.getElementById('wsUrlInput');
    if (btnConnectWs && wsUrlInput) {
      btnConnectWs.addEventListener('click', () => {
        const val = wsUrlInput.value.trim();
        if (val) {
          wsUrl = val;
          connectWebSocket(val);
        }
      });
    }

    const btnDemoMode = document.getElementById('btnDemoMode');
    if (btnDemoMode) {
      btnDemoMode.addEventListener('click', () => {
        if (wsSocket) {
          try { wsSocket.close(); } catch (e) {}
        }
        isLiveWS = false;
        setModeBadge('demo', 'DEMO SIM');
        closeModal();
      });
    }

    // 9. Copy Schema
    const btnCopySchema = document.getElementById('btnCopySchema');
    const schemaContent = document.getElementById('schemaContent');
    const copyFeedback = document.getElementById('copyFeedback');
    if (btnCopySchema && schemaContent) {
      btnCopySchema.addEventListener('click', () => {
        navigator.clipboard.writeText(schemaContent.textContent).then(() => {
          if (copyFeedback) {
            copyFeedback.classList.add('visible');
            setTimeout(() => copyFeedback.classList.remove('visible'), 2000);
          }
        });
      });
    }

    // 10. Collapse / Expand Deck
    const btnCollapse = document.getElementById('btnCollapseSwarm');
    const swarmDeck = document.getElementById('swarmDeck');
    if (btnCollapse && swarmDeck) {
      btnCollapse.addEventListener('click', () => {
        const isCollapsed = swarmDeck.classList.toggle('collapsed');
        btnCollapse.textContent = isCollapsed ? 'Expand' : 'Collapse';
        if (!isCollapsed) {
          setTimeout(resizeCanvas, 60);
        }
      });
    }
  }

  // --- 18. BOOTSTRAP ENTRY POINT ---
  function init() {
    canvas = document.getElementById('neuralCanvas');
    if (!canvas) return;
    ctx = canvas.getContext('2d');

    initBots(6);
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    setupControls();
    setupPanAndDrag();

    const schemaEl = document.getElementById('schemaContent');
    if (schemaEl) {
      schemaEl.textContent = `// 1. 6-Bot Frontend Bridge API (window.BotSwarmBridge)
window.BotSwarmBridge.setTopology({
  bots: [
    { id: "BOT-01", name: "LIGHTNING", role: "Scalp Velocity", accent: "#f5c869", pair: "SOL/USDT" },
    { id: "BOT-02", name: "TIGER", role: "Prey Radar", accent: "#38bdf8", pair: "BTC/USDT" },
    { id: "BOT-03", name: "MACRO", role: "Regime Forecast", accent: "#c084fc", pair: "ETH/USDT" },
    { id: "BOT-04", name: "STORM", role: "Trend Momentum", accent: "#34d399", pair: "BNB/USDT" },
    { id: "BOT-05", name: "NEON-5", role: "Trend Hunter", strategyKey: "neon-trend", accent: "#22d3ee", pair: "BTC/USDT" },
    { id: "BOT-06", name: "NEON-6", role: "Maker Arbiter", strategyKey: "neon-maker", accent: "#2dd4bf", pair: "LINK/USDT" }
  ]
});

// 2. Fleet & Interactive Controls
window.BotSwarmBridge.setFleetSize(6);        // 6 | 4 | 3
window.BotSwarmBridge.focusBot("BOT-05");     // Smooth camera focus + open Inspector
window.BotSwarmBridge.setBotPaused("BOT-06", true);
window.BotSwarmBridge.syncNeonTelemetry();    // Pull live 6-gate telemetry from /api/neon/overview

// 3. WebSocket JSON Envelope (/swarm)
// { "type": "BEACON_UPSERT" | "WORKER_SIGNAL" | "TRADE_FILL" | "TOPOLOGY", "payload": { ... } }`;
    }

    // Hydrate BOT-05 & BOT-06 with live NEON telemetry and refresh every 15s while visible
    syncNeonTelemetry();
    if (neonSyncTimer) clearInterval(neonSyncTimer);
    neonSyncTimer = setInterval(() => {
      if (document.visibilityState === 'visible') {
        syncNeonTelemetry();
      }
    }, 15000);

    connectWebSocket();

    lastTime = performance.now();
    animFrameId = requestAnimationFrame(render);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
