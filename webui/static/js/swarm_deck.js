/**
 * webui/static/js/swarm_deck.js — Interactive Neural Swarm Canvas & BotSwarmBridge
 *
 * Features:
 * - Draggable Bots & Workers: Click & drag any bot hub to relocate it anywhere on canvas.
 * - Draggable Beacons: Drag candidate asset beacons directly.
 * - Viewport Pan & Zoom: Click & drag empty canvas space to pan; mouse wheel to zoom (0.4x - 2.5x).
 * - Reset View: "Reset View" button & canvas double-click to snap back to default layout.
 * - Full Touch & Mouse Support with zero-lag worker tracking.
 * - Implements window.BotSwarmBridge with auto-reconnect to ws://localhost:8765/swarm.
 * - Graceful fallback to autonomous demo simulation when WS is idle.
 */

(function () {
  'use strict';

  // --- 1. CONFIGURATION & COLOR PALETTES ---
  const WORKER_STAGES = [
    { id: 'SCAN', label: 'SCAN', color: '#f43f5e', name: 'Scanner' },
    { id: 'FLOW', label: 'FLOW', color: '#fb7185', name: 'Orderflow' },
    { id: 'RISK', label: 'RISK', color: '#2dd4bf', name: 'Risk Arbiter' },
    { id: 'VALID', label: 'VALID', color: '#fbbf24', name: 'Trajectory' },
    { id: 'EXEC', label: 'EXEC', color: '#a855f7', name: 'Execution' },
    { id: 'LEDGER', label: 'LEDGER', color: '#34d399', name: 'Ledger' }
  ];

  const DEFAULT_BOTS_4 = [
    { id: 'BOT-01', name: 'LIGHTNING', accent: '#f5c869', pair: 'SOL/USDT' },
    { id: 'BOT-02', name: 'TIGER', accent: '#38bdf8', pair: 'BTC/USDT' },
    { id: 'BOT-03', name: 'MACRO', accent: '#c084fc', pair: 'ETH/USDT' },
    { id: 'BOT-04', name: 'STORM', accent: '#34d399', pair: 'BNB/USDT' }
  ];

  const DEFAULT_BOTS_3 = [
    { id: 'BOT-01', name: 'LIGHTNING', accent: '#f5c869', pair: 'SOL/USDT' },
    { id: 'BOT-02', name: 'TIGER', accent: '#38bdf8', pair: 'BTC/USDT' },
    { id: 'BOT-03', name: 'MACRO', accent: '#c084fc', pair: 'ETH/USDT' }
  ];

  const CANDIDATE_ASSETS = ['SOL', 'BTC', 'ETH', 'BNB', 'PEPE', 'DOGE', 'SUI', 'AVAX', 'NEAR', 'LINK', 'RENDER', 'APT'];

  // --- 2. ENGINE & INTERACTION STATE ---
  let canvas, ctx;
  let animFrameId = null;
  let isRunning = true;
  let botsCount = 4;
  let simulationPace = 1.0;
  let isLiveWS = false;
  let wsSocket = null;
  let wsUrl = (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + (window.location.hostname || 'localhost') + ':8765/swarm';

  let bots = [];
  let beacons = new Map(); // id -> Beacon
  let particles = [];
  let lightningStrikes = [];

  // Pan, Zoom & Dragging state
  let panX = 0;
  let panY = 0;
  let zoom = 1.0;
  let isPanning = false;
  let panStart = { x: 0, y: 0 };
  let draggedBot = null;
  let draggedBeacon = null;
  let dragOffset = { x: 0, y: 0 };
  let hoveredBot = null;
  let hoveredBeacon = null;

  let lastTime = performance.now();
  let demoTimer = 0;

  // --- 3. BOT & WORKER CLASSES ---
  class BotNode {
    constructor(cfg, targetX, targetY) {
      this.id = cfg.id;
      this.name = cfg.name;
      this.accent = cfg.accent || '#f5c869';
      this.pair = cfg.pair || 'BTC/USDT';
      this.x = targetX;
      this.y = targetY;
      this.isCustomPosition = false;
      this.isDragged = false;
      this.radius = 24;
      this.angle = 0;
      this.stateText = 'HUNTING';
      this.stateTime = 0;
      this.lockedBeaconId = null;

      // Initialize 6 satellite workers orbiting this bot
      this.workers = WORKER_STAGES.map((st, i) => ({
        id: st.id,
        label: st.label,
        color: st.color,
        angleOffset: (i * (Math.PI * 2) / 6),
        orbitRadius: 65,
        x: targetX,
        y: targetY,
        currentPill: null,
        pillTime: 0,
        activePulse: 0
      }));

      this.updateWorkers(0);
    }

    update(dt, defaultX, defaultY) {
      // If user hasn't dragged this bot, anchor to default quadrant
      if (!this.isCustomPosition && !this.isDragged) {
        this.x = defaultX;
        this.y = defaultY;
      }

      this.angle += dt * 0.4 * simulationPace;

      if (this.stateTime > 0) {
        this.stateTime -= dt;
        if (this.stateTime <= 0) {
          this.stateText = 'HUNTING';
          this.lockedBeaconId = null;
        }
      }

      this.updateWorkers(dt);
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
            w.activePulse = Math.max(0, w.activePulse - dt * 2.5);
          }
        }
      });
    }

    draw(ctx) {
      // 1. Draw glowing tentacle filaments to workers
      this.workers.forEach((w) => {
        ctx.beginPath();
        ctx.moveTo(this.x, this.y);
        const midX = (this.x + w.x) / 2 + Math.cos(this.angle) * 8;
        const midY = (this.y + w.y) / 2 + Math.sin(this.angle) * 8;
        ctx.quadraticCurveTo(midX, midY, w.x, w.y);
        ctx.strokeStyle = w.activePulse > 0 ? w.color : 'rgba(255, 255, 255, 0.12)';
        ctx.lineWidth = w.activePulse > 0 ? 2 : 1;
        ctx.stroke();

        // Worker node
        ctx.beginPath();
        ctx.arc(w.x, w.y, 4.5 + w.activePulse * 3, 0, Math.PI * 2);
        ctx.fillStyle = w.color;
        ctx.shadowColor = w.color;
        ctx.shadowBlur = w.activePulse > 0 ? 14 : 5;
        ctx.fill();
        ctx.shadowBlur = 0;

        // Worker label
        ctx.font = '600 8px monospace';
        ctx.fillStyle = '#94a3b8';
        ctx.textAlign = 'center';
        ctx.fillText(w.label, w.x, w.y - 8);

        // Worker pill badge
        if (w.currentPill) {
          ctx.font = '500 8.5px monospace';
          const pWidth = ctx.measureText(w.currentPill).width + 10;
          ctx.fillStyle = 'rgba(10, 14, 22, 0.90)';
          ctx.strokeStyle = w.color;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.roundRect(w.x - pWidth / 2, w.y + 7, pWidth, 14, 6);
          ctx.fill();
          ctx.stroke();

          ctx.fillStyle = '#f8fafc';
          ctx.fillText(w.currentPill, w.x, w.y + 17);
        }
      });

      // 2. Drag / Hover indicator halo
      if (this.isDragged || this === hoveredBot) {
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.radius + 12, 0, Math.PI * 2);
        ctx.strokeStyle = this.accent;
        ctx.lineWidth = this.isDragged ? 2 : 1.2;
        ctx.setLineDash([4, 4]);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // 3. Draw Bot Hub Outer Radar Reticle
      ctx.save();
      ctx.translate(this.x, this.y);
      ctx.rotate(this.angle * 0.5);

      ctx.beginPath();
      ctx.arc(0, 0, this.radius + 6, 0, Math.PI * 1.5);
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
      ctx.lineWidth = 1.2;
      ctx.setLineDash([4, 6]);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.beginPath();
      ctx.arc(0, 0, this.radius + 2, Math.PI * 0.8, Math.PI * 1.8);
      ctx.strokeStyle = this.accent;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.restore();

      // 4. Central Bot Core
      ctx.beginPath();
      ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(11, 15, 24, 0.94)';
      ctx.strokeStyle = this.accent;
      ctx.lineWidth = 2;
      ctx.shadowColor = this.accent;
      ctx.shadowBlur = this.isDragged ? 20 : 12;
      ctx.fill();
      ctx.stroke();
      ctx.shadowBlur = 0;

      // Inner text / icon
      ctx.fillStyle = this.accent;
      ctx.font = 'bold 10px monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(this.id, this.x, this.y - 3);

      // Name & state tags below
      ctx.textBaseline = 'alphabetic';
      ctx.font = '700 9px monospace';
      ctx.fillStyle = '#f8fafc';
      ctx.fillText(this.name, this.x, this.y + 36);

      ctx.font = '500 8.5px monospace';
      if (this.stateText.startsWith('FILL')) {
        ctx.fillStyle = '#34d399';
      } else if (this.stateText.startsWith('LOCK')) {
        ctx.fillStyle = '#f5c869';
      } else {
        ctx.fillStyle = '#64748b';
      }
      ctx.fillText(this.stateText, this.x, this.y + 47);
    }
  }

  // --- 4. BEACON (BINANCE ASSET CANDIDATE) ---
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

    draw(ctx, w, h) {
      const px = this.worldX;
      const py = this.worldY;
      const alpha = Math.max(0, Math.min(1, this.life));

      ctx.save();
      ctx.globalAlpha = alpha;

      let col = '#38bdf8';
      if (this.status === 'LOCKED') col = '#f5c869';
      if (this.status === 'SKIPPED') col = '#ef4444';
      if (this.status === 'CAPTURED') col = '#34d399';

      // Pulse ring for locked/captured
      if (this.status === 'LOCKED' || this.status === 'CAPTURED') {
        const ringR = 12 + (Math.sin(this.pulse) + 1) * 4;
        ctx.beginPath();
        ctx.arc(px, py, ringR, 0, Math.PI * 2);
        ctx.strokeStyle = col;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Diamond marker
      const sz = 8;
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

      // Symbol & Score text
      ctx.font = '600 8.5px monospace';
      ctx.fillStyle = col;
      ctx.textAlign = 'center';
      ctx.fillText(this.symbol, px, py - 12);

      ctx.font = '500 7.5px monospace';
      ctx.fillStyle = '#cbd5e1';
      ctx.fillText((this.score * 100).toFixed(0) + '%', px, py + 16);

      ctx.restore();
    }
  }

  // --- 5. INITIALIZE TOPOLOGY ---
  function initBots(count) {
    botsCount = count;
    const cfgList = count === 3 ? DEFAULT_BOTS_3 : DEFAULT_BOTS_4;
    bots = cfgList.map((cfg) => new BotNode(cfg, 0, 0));
    updateSwarmSummary();
  }

  function updateSwarmSummary() {
    const el = document.getElementById('swarmSummary');
    if (el) {
      el.textContent = `${bots.length} bots · ${bots.length * 6} agent workers · spot crypto`;
    }
  }

  function getQuadrantCoords(w, h, count) {
    if (count === 3) {
      return [
        { x: w * 0.50, y: h * 0.32 },
        { x: w * 0.28, y: h * 0.68 },
        { x: w * 0.72, y: h * 0.68 }
      ];
    }
    return [
      { x: w * 0.28, y: h * 0.34 },
      { x: w * 0.72, y: h * 0.34 },
      { x: w * 0.28, y: h * 0.70 },
      { x: w * 0.72, y: h * 0.70 }
    ];
  }

  // --- 6. COORDINATE TRANSFORMATIONS & HIT TESTING ---
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
      if (dist <= b.radius + 14) {
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
    panX = 0;
    panY = 0;
    zoom = 1.0;
    bots.forEach((b) => {
      b.isCustomPosition = false;
      b.isDragged = false;
    });
    if (canvas) {
      canvas.classList.remove('is-dragging', 'is-panning');
      canvas.style.cursor = 'grab';
    }
  }

  // --- 7. LIGHTNING EXECUTION STRIKE EFFECT ---
  function triggerLightningStrike(bot, beacon) {
    if (!canvas) return;
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

    // Spawn burst particles
    for (let i = 0; i < 16; i++) {
      const ang = Math.random() * Math.PI * 2;
      const spd = 20 + Math.random() * 80;
      particles.push({
        x: bx,
        y: by,
        vx: Math.cos(ang) * spd,
        vy: Math.sin(ang) * spd,
        color: bot.accent,
        life: 0.8
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
      const offset = (Math.random() - 0.5) * 24;
      pts.push({ x: lx + offset, y: ly + offset });
    }
    pts.push({ x: x2, y: y2 });
    return pts;
  }

  // --- 8. BOTSWARM BRIDGE API ---
  window.BotSwarmBridge = {
    setTopology: function (data) {
      if (!data || !data.bots || !Array.isArray(data.bots)) return;
      bots = data.bots.map((b) => new BotNode(b, 0, 0));
      botsCount = bots.length;
      updateSwarmSummary();
    },

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

      // If status is LOCKED, assign to closest bot
      if (b.status === 'LOCKED' && bots.length > 0) {
        let chosenBot = bots[0];
        let minDist = Infinity;
        bots.forEach((bot) => {
          const d = Math.hypot(bot.x - b.worldX, bot.y - b.worldY);
          if (d < minDist) {
            minDist = d;
            chosenBot = bot;
          }
        });
        chosenBot.stateText = `LOCKED • ${b.symbol}`;
        chosenBot.stateTime = 3.0;
        chosenBot.lockedBeaconId = b.id;
        triggerLightningStrike(chosenBot, b);
      }
    },

    emitWorkerSignal: function (signal) {
      if (!signal || !signal.botId || !signal.workerId) return;
      const bot = bots.find((b) => b.id === signal.botId);
      if (!bot) return;

      const worker = bot.workers.find((w) => w.id === signal.workerId);
      if (worker) {
        worker.currentPill = signal.label || `• ${signal.state || 'ACTIVE'}`;
        worker.pillTime = 2.5;
        worker.activePulse = 1.0;
      }
    },

    emitTradeFill: function (fill) {
      if (!fill || !fill.symbol) return;
      const bot = bots.find((b) => b.id === fill.botId) || bots[0];
      if (bot) {
        bot.stateText = `FILL • ${fill.pnl || '+1.00%'}`;
        bot.stateTime = 4.0;
      }
      let b = beacons.get(fill.beaconId);
      if (b) {
        b.status = 'CAPTURED';
      }
    },

    resetView: resetView
  };

  // --- 9. WEBSOCKET TELEMETRY CLIENT ---
  function connectWebSocket(customUrl) {
    if (wsSocket) {
      try { wsSocket.close(); } catch (e) {}
    }

    const targetUrl = customUrl || wsUrl;
    setModeBadge('connecting', 'CONNECTING...');

    try {
      wsSocket = new WebSocket(targetUrl);

      wsSocket.onopen = function () {
        isLiveWS = true;
        setModeBadge('live', 'LIVE WS STREAM');
        console.log('[BotSwarmBridge] WebSocket connected to', targetUrl);
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

  // --- 10. AUTONOMOUS DEMO SIMULATION (WHEN WS IDLE) ---
  function runDemoSimulationStep(dt) {
    if (isLiveWS) return;

    demoTimer += dt * simulationPace;
    if (demoTimer > 2.2) {
      demoTimer = 0;

      const asset = CANDIDATE_ASSETS[Math.floor(Math.random() * CANDIDATE_ASSETS.length)];
      const sym = `${asset}/USDT`;
      const id = `demo-${asset.toLowerCase()}`;
      const score = Math.random() > 0.35 ? +(0.62 + Math.random() * 0.35).toFixed(2) : +(0.35 + Math.random() * 0.25).toFixed(2);
      const isLock = score >= 0.62;

      const xN = +(0.10 + Math.random() * 0.80).toFixed(2);
      const yN = +(0.15 + Math.random() * 0.70).toFixed(2);

      window.BotSwarmBridge.upsertBeacon({
        id: id,
        symbol: sym,
        score: score,
        xNorm: xN,
        yNorm: yN,
        status: isLock ? 'LOCKED' : 'SKIPPED'
      });

      const targetBot = bots[Math.floor(Math.random() * bots.length)];
      if (isLock) {
        window.BotSwarmBridge.emitWorkerSignal({
          botId: targetBot.id,
          workerId: 'SCAN',
          beaconId: id,
          state: 'TRIANGULATING',
          label: `• cvd breakout +${(2.0 + Math.random() * 2.5).toFixed(1)}σ`
        });

        setTimeout(() => {
          window.BotSwarmBridge.emitWorkerSignal({
            botId: targetBot.id,
            workerId: 'EXEC',
            beaconId: id,
            state: 'LOCK',
            label: `• maker limit`
          });
        }, 600);

        setTimeout(() => {
          if (Math.random() > 0.4) {
            window.BotSwarmBridge.emitTradeFill({
              botId: targetBot.id,
              beaconId: id,
              symbol: sym,
              side: 'BUY',
              pnl: `+${(0.8 + Math.random() * 1.6).toFixed(2)}%`
            });
          }
        }, 1400);
      } else {
        window.BotSwarmBridge.emitWorkerSignal({
          botId: targetBot.id,
          workerId: 'RISK',
          beaconId: id,
          state: 'VETO',
          label: '• skip: high spread / noise'
        });
      }
    }
  }

  // --- 11. POINTER INTERACTION (DRAG BOT, DRAG BEACON, PAN VIEWPORT) ---
  function setupPanAndDrag() {
    function getPointerPos(e) {
      const rect = canvas.getBoundingClientRect();
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      const clientY = e.touches ? e.touches[0].clientY : e.clientY;
      const sx = clientX - rect.left;
      const sy = clientY - rect.top;
      const wpos = screenToWorld(sx, sy);
      return { sx, sy, wx: wpos.x, wy: wpos.y };
    }

    function onPointerDown(e) {
      if (!canvas) return;
      const { sx, sy, wx, wy } = getPointerPos(e);

      // Check if user clicked a Bot Hub
      const hitBot = findHitBot(wx, wy);
      if (hitBot) {
        draggedBot = hitBot;
        draggedBot.isDragged = true;
        draggedBot.isCustomPosition = true;
        dragOffset = { x: wx - hitBot.x, y: wy - hitBot.y };
        canvas.classList.add('is-dragging');
        canvas.style.cursor = 'grabbing';
        return;
      }

      // Check if user clicked a Beacon
      const hitBeacon = findHitBeacon(wx, wy);
      if (hitBeacon) {
        draggedBeacon = hitBeacon;
        draggedBeacon.isDragged = true;
        dragOffset = { x: wx - hitBeacon.worldX, y: wy - hitBeacon.worldY };
        canvas.classList.add('is-dragging');
        canvas.style.cursor = 'grabbing';
        return;
      }

      // Otherwise: Pan viewport
      isPanning = true;
      panStart = { x: sx - panX, y: sy - panY };
      canvas.classList.add('is-panning');
      canvas.style.cursor = 'grabbing';
    }

    function onPointerMove(e) {
      if (!canvas) return;
      const { sx, sy, wx, wy } = getPointerPos(e);

      // 1. Dragging a Bot
      if (draggedBot) {
        if (e.cancelable && e.touches) e.preventDefault();
        draggedBot.x = wx - dragOffset.x;
        draggedBot.y = wy - dragOffset.y;
        draggedBot.updateWorkers(0);
        return;
      }

      // 2. Dragging a Beacon
      if (draggedBeacon) {
        if (e.cancelable && e.touches) e.preventDefault();
        draggedBeacon.worldX = wx - dragOffset.x;
        draggedBeacon.worldY = wy - dragOffset.y;
        const rect = canvas.getBoundingClientRect();
        draggedBeacon.xNorm = draggedBeacon.worldX / (rect.width || 1);
        draggedBeacon.yNorm = draggedBeacon.worldY / (rect.height || 1);
        return;
      }

      // 3. Panning Viewport
      if (isPanning) {
        if (e.cancelable && e.touches) e.preventDefault();
        panX = sx - panStart.x;
        panY = sy - panStart.y;
        return;
      }

      // 4. Hover State Feedback
      const hitBot = findHitBot(wx, wy);
      const hitBeacon = findHitBeacon(wx, wy);

      if (hitBot !== hoveredBot || hitBeacon !== hoveredBeacon) {
        hoveredBot = hitBot;
        hoveredBeacon = hitBeacon;
        canvas.style.cursor = (hitBot || hitBeacon) ? 'grab' : 'crosshair';
      }
    }

    function onPointerUp() {
      if (draggedBot) {
        draggedBot.isDragged = false;
        draggedBot = null;
      }
      if (draggedBeacon) {
        draggedBeacon.isDragged = false;
        draggedBeacon = null;
      }
      isPanning = false;
      if (canvas) {
        canvas.classList.remove('is-dragging', 'is-panning');
        canvas.style.cursor = (hoveredBot || hoveredBeacon) ? 'grab' : 'crosshair';
      }
    }

    // Wheel Zoom around pointer
    function onWheel(e) {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;

      const zoomFactor = e.deltaY < 0 ? 1.08 : 0.92;
      const newZoom = Math.max(0.4, Math.min(2.5, zoom * zoomFactor));

      panX = sx - (sx - panX) * (newZoom / zoom);
      panY = sy - (sy - panY) * (newZoom / zoom);
      zoom = newZoom;
    }

    // Double-click to reset view
    function onDblClick() {
      resetView();
    }

    // Mouse Listeners
    canvas.addEventListener('mousedown', onPointerDown);
    window.addEventListener('mousemove', onPointerMove);
    window.addEventListener('mouseup', onPointerUp);
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('dblclick', onDblClick);

    // Touch Listeners
    canvas.addEventListener('touchstart', onPointerDown, { passive: true });
    window.addEventListener('touchmove', onPointerMove, { passive: false });
    window.addEventListener('touchend', onPointerUp);
  }

  // --- 12. MAIN ANIMATION & RENDER LOOP ---
  function render(time) {
    if (!isRunning) return;

    // Visibility throttle: zero CPU when tab is hidden
    if (document.visibilityState === 'hidden') {
      animFrameId = requestAnimationFrame(render);
      return;
    }

    const dt = Math.min(0.1, (time - lastTime) / 1000);
    lastTime = time;

    const rect = canvas.getBoundingClientRect();
    const cssW = rect.width;
    const cssH = rect.height;

    // Reset transform to 1 CSS unit = 1 pixel
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    ctx.save();
    // Apply pan & zoom
    ctx.translate(panX, panY);
    ctx.scale(zoom, zoom);

    // Infinite/Extended Radar Grid
    const gridMax = Math.max(cssW, cssH) * 2;
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.025)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(cssW * 0.5, -gridMax); ctx.lineTo(cssW * 0.5, gridMax);
    ctx.moveTo(-gridMax, cssH * 0.5); ctx.lineTo(gridMax, cssH * 0.5);
    ctx.arc(cssW * 0.5, cssH * 0.5, cssW * 0.22, 0, Math.PI * 2);
    ctx.arc(cssW * 0.5, cssH * 0.5, cssW * 0.44, 0, Math.PI * 2);
    ctx.stroke();

    // 1. Update & Draw Bots
    const coords = getQuadrantCoords(cssW, cssH, bots.length);
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
        b.draw(ctx, cssW, cssH);
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
      ctx.lineWidth = 2.5;
      ctx.shadowColor = strike.color;
      ctx.shadowBlur = 14;
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

    // 5. Autonomous Demo Tick (when disconnected from WS)
    runDemoSimulationStep(dt);

    animFrameId = requestAnimationFrame(render);
  }

  // --- 13. RESIZE HANDLER ---
  function resizeCanvas() {
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
  }

  // --- 14. DOCK CONTROLS & MODAL EVENT BINDING ---
  function setupControls() {
    // 1. Reset View Button
    const btnResetView = document.getElementById('btnResetView');
    if (btnResetView) {
      btnResetView.addEventListener('click', resetView);
    }

    // 2. Toggle Bot Count
    const btnBotCount = document.getElementById('btnBotCount');
    if (btnBotCount) {
      btnBotCount.addEventListener('click', () => {
        const next = botsCount === 4 ? 3 : 4;
        initBots(next);
        btnBotCount.textContent = `Bots: ${next}`;
      });
    }

    // 3. Drop Alpha Lightning Button
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

    // 4. Cycle Simulation Pace
    const btnPace = document.getElementById('btnPace');
    if (btnPace) {
      btnPace.addEventListener('click', () => {
        if (simulationPace === 1.0) simulationPace = 2.0;
        else if (simulationPace === 2.0) simulationPace = 0.5;
        else simulationPace = 1.0;
        btnPace.textContent = `Pace: ${simulationPace.toFixed(1)}x`;
      });
    }

    // 5. Modal Open/Close
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

    // 6. Connect WS in modal
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

    // 7. Demo Mode button in modal
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

    // 8. Copy Schema Button
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

    // 9. Collapse / Expand Deck
    const btnCollapse = document.getElementById('btnCollapseSwarm');
    const swarmDeck = document.getElementById('swarmDeck');
    if (btnCollapse && swarmDeck) {
      btnCollapse.addEventListener('click', () => {
        const isCollapsed = swarmDeck.classList.toggle('collapsed');
        btnCollapse.textContent = isCollapsed ? '[ + ] Expand' : '[ - ] Collapse';
        setTimeout(resizeCanvas, 320);
      });
    }
  }

  // --- 15. BOOTSTRAP ENTRY POINT ---
  function init() {
    canvas = document.getElementById('neuralCanvas');
    if (!canvas) return;
    ctx = canvas.getContext('2d');

    initBots(4);
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    setupControls();
    setupPanAndDrag();

    // Populate schema box text
    const schemaEl = document.getElementById('schemaContent');
    if (schemaEl) {
      schemaEl.textContent = `// 1. Direct Frontend Bridge API (window.BotSwarmBridge)
window.BotSwarmBridge.setTopology({
  bots: [
    { id: "BOT-01", name: "LIGHTNING", accent: "#f5c869", pair: "SOL/USDT" },
    { id: "BOT-02", name: "TIGER", accent: "#38bdf8", pair: "BTC/USDT" },
    { id: "BOT-03", name: "MACRO", accent: "#c084fc", pair: "ETH/USDT" },
    { id: "BOT-04", name: "STORM", accent: "#34d399", pair: "BNB/USDT" }
  ]
});

window.BotSwarmBridge.upsertBeacon({
  id: "sig-904",
  symbol: "SOL/USDT",
  score: 0.92, // >= 0.62 triggers lock & execution cascade; < 0.62 skips
  xNorm: 0.51, // normalized viewport X [0.06 .. 0.94]
  yNorm: 0.48, // normalized viewport Y [0.08 .. 0.90]
  status: "PEEKING" // "PEEKING" | "LOCKED" | "SKIPPED" | "CAPTURED"
});

window.BotSwarmBridge.emitWorkerSignal({
  botId: "BOT-01",
  workerId: "SCAN", // "SCAN" | "FLOW" | "RISK" | "VALID" | "EXEC" | "LEDGER"
  beaconId: "sig-904",
  state: "TRIANGULATING",
  label: "• cvd breakout +3.4σ"
});

window.BotSwarmBridge.emitTradeFill({
  botId: "BOT-01",
  beaconId: "sig-904",
  symbol: "SOL/USDT",
  side: "BUY",
  pnl: "+1.42%"
});

// 2. WebSocket JSON Envelope (ws://localhost:8765/swarm)
// { "type": "BEACON_UPSERT" | "WORKER_SIGNAL" | "TRADE_FILL" | "TOPOLOGY", "payload": { ... } }`;
    }

    // Auto-attempt connect to WebSocket telemetry hub
    connectWebSocket();

    // Start render loop
    lastTime = performance.now();
    animFrameId = requestAnimationFrame(render);
  }

  // DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
