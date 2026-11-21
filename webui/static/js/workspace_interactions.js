/**
 * ============================================================================
 * KRONOS WORKSPACE INTERACTIONS ENGINE
 * Provides:
 *  1. Draggable & reorderable cards/panels across all views (with localStorage)
 *  2. Click-and-drag horizontal panning on wide tables, matrices, & strips
 *  3. Collapsible panels for dynamic workspace focus
 *  4. Resizable vertical splitter for Stalking Tiger Radar vs Tactical Deck
 *  5. Non-blocking institutional toast notifications
 * ============================================================================
 */

(function () {
    'use strict';

    const LAYOUT_STORAGE_KEY = 'kronos_workspace_layout_v1';

    // ------------------------------------------------------------------------
    // 1. NON-BLOCKING TOAST NOTIFICATION HELPER
    // ------------------------------------------------------------------------
    function showKronosToast(message, type = 'info', durationMs = 2800) {
        const container = document.getElementById('status-container');
        if (!container) return;
        const el = document.createElement('div');
        el.className = `kronos-toast ${type}`;
        el.textContent = message;
        container.appendChild(el);
        setTimeout(() => {
            el.style.opacity = '0';
            el.style.transform = 'translateY(6px)';
            el.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
            setTimeout(() => el.remove(), 220);
        }, durationMs);
    }
    window.showKronosToast = showKronosToast;

    window.copyTextWithToast = function (elementId, label = 'Value') {
        const el = document.getElementById(elementId);
        if (!el) return;
        const text = el.textContent.trim();
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text)
                .then(() => showKronosToast(`${label} copied: ${text}`, 'success'))
                .catch(() => showKronosToast(`Copy failed for ${text}`, 'error'));
        } else {
            showKronosToast(`${label}: ${text}`, 'info');
        }
    };

    // ------------------------------------------------------------------------
    // 2. PERSISTENT LAYOUT STORAGE HELPERS
    // ------------------------------------------------------------------------
    function loadSavedLayout() {
        try {
            const raw = localStorage.getItem(LAYOUT_STORAGE_KEY);
            return raw ? JSON.parse(raw) : {};
        } catch (e) {
            return {};
        }
    }

    function saveGroupOrder(groupId, container) {
        try {
            const state = loadSavedLayout();
            const ids = Array.from(container.children)
                .filter((el) => el.hasAttribute('data-drag-item'))
                .map((el) => el.getAttribute('data-drag-item'));
            state[groupId] = ids;
            localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(state));
        } catch (e) {
            // Ignore storage quota errors
        }
    }

    function restoreGroupOrder(groupId, container) {
        const state = loadSavedLayout();
        const savedIds = state[groupId];
        if (!Array.isArray(savedIds) || savedIds.length === 0) return;

        const itemsById = new Map();
        Array.from(container.children).forEach((child) => {
            const id = child.getAttribute('data-drag-item');
            if (id) itemsById.set(id, child);
        });

        savedIds.forEach((id) => {
            const el = itemsById.get(id);
            if (el) {
                container.appendChild(el);
                itemsById.delete(id);
            }
        });

        // Append any newly added items not in saved state
        itemsById.forEach((el) => container.appendChild(el));
    }

    // ------------------------------------------------------------------------
    // 3. DRAGGABLE & REORDERABLE CARDS / PANELS ENGINE
    // ------------------------------------------------------------------------
    const GRIP_SVG = `<svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true">
        <circle cx="3.5" cy="2.5" r="1.1"></circle><circle cx="8.5" cy="2.5" r="1.1"></circle>
        <circle cx="3.5" cy="6" r="1.1"></circle><circle cx="8.5" cy="6" r="1.1"></circle>
        <circle cx="3.5" cy="9.5" r="1.1"></circle><circle cx="8.5" cy="9.5" r="1.1"></circle>
    </svg>`;

    const CHEVRON_SVG = `<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <polyline points="4 6 8 10 12 6"></polyline>
    </svg>`;

    let activeDragItem = null;
    let activeDragGroup = null;

    function injectDragHandle(item) {
        if (item.querySelector(':scope > .panel-header .drag-handle, :scope > .card-header .drag-handle, :scope > .tiger-card-header .drag-handle, :scope > .ym-header .drag-handle')) {
            return;
        }

        const handle = document.createElement('span');
        handle.className = 'drag-handle';
        handle.title = 'Drag to reorder';
        handle.innerHTML = GRIP_SVG;

        // Place grip inside header cleanly without breaking existing layout
        const panelHeaderLeft = item.querySelector(':scope > .panel-header .panel-header-left');
        const panelHeader = item.querySelector(':scope > .panel-header');
        const cardHeader = item.querySelector(':scope > .card-header');
        const tigerHeader = item.querySelector(':scope > .tiger-card-header');
        const ymHeader = item.querySelector(':scope > .ym-header');

        if (panelHeaderLeft) {
            panelHeaderLeft.insertBefore(handle, panelHeaderLeft.firstChild);
        } else if (panelHeader) {
            const wrapper = document.createElement('div');
            wrapper.className = 'panel-header-left';
            if (panelHeader.firstElementChild) {
                const first = panelHeader.firstElementChild;
                panelHeader.insertBefore(wrapper, first);
                wrapper.appendChild(handle);
                wrapper.appendChild(first);
            } else {
                panelHeader.insertBefore(handle, panelHeader.firstChild);
            }
        } else if (tigerHeader) {
            const title = tigerHeader.firstElementChild;
            if (title) {
                title.insertBefore(handle, title.firstChild);
            } else {
                tigerHeader.insertBefore(handle, tigerHeader.firstChild);
            }
        } else if (ymHeader) {
            const titleGroup = ymHeader.querySelector('.ym-title-group');
            if (titleGroup) {
                const row = document.createElement('div');
                row.style.display = 'flex';
                row.style.alignItems = 'center';
                row.style.gap = '8px';
                ymHeader.insertBefore(row, titleGroup);
                row.appendChild(handle);
                row.appendChild(titleGroup);
            }
        } else if (cardHeader) {
            cardHeader.insertBefore(handle, cardHeader.firstChild);
        } else {
            // Compact card (e.g. gate-card): enable direct drag on card with subtle top-right handle
            item.style.position = 'relative';
            handle.style.position = 'absolute';
            handle.style.top = '6px';
            handle.style.right = '6px';
            item.appendChild(handle);
        }

        // Only allow drag initiation when pressing the grip handle (or card background on metric/gate cards)
        const allowWholeCardDrag = item.classList.contains('metric-card') || item.classList.contains('gate-card');

        item.addEventListener('pointerdown', (e) => {
            if (e.target.closest('button, input, select, textarea, a, .ym-seg-btn')) {
                item.setAttribute('draggable', 'false');
                return;
            }
            if (allowWholeCardDrag || e.target.closest('.drag-handle')) {
                item.setAttribute('draggable', 'true');
            } else {
                item.setAttribute('draggable', 'false');
            }
        });

        item.addEventListener('pointerup', () => {
            item.setAttribute('draggable', 'false');
        });
    }

    function initDraggableGroups() {
        const groups = document.querySelectorAll('[data-drag-group]');
        groups.forEach((container) => {
            const groupId = container.getAttribute('data-drag-group');
            if (!groupId) return;

            // Remember default order for Reset Layout
            const defaultOrder = Array.from(container.children)
                .filter((el) => el.hasAttribute('data-drag-item'))
                .map((el) => el.getAttribute('data-drag-item'));
            container.dataset.defaultOrder = JSON.stringify(defaultOrder);

            // Restore user's persisted order if any
            restoreGroupOrder(groupId, container);

            Array.from(container.children).forEach((item) => {
                if (!item.hasAttribute('data-drag-item')) return;
                item.setAttribute('draggable', 'false');
                injectDragHandle(item);

                item.addEventListener('dragstart', (e) => {
                    if (item.getAttribute('draggable') !== 'true') {
                        e.preventDefault();
                        return;
                    }
                    activeDragItem = item;
                    activeDragGroup = groupId;
                    item.classList.add('is-dragging');
                    e.dataTransfer.effectAllowed = 'move';
                    try {
                        e.dataTransfer.setData('text/plain', item.getAttribute('data-drag-item') || '');
                    } catch (err) { }
                });

                item.addEventListener('dragend', () => {
                    item.classList.remove('is-dragging');
                    item.setAttribute('draggable', 'false');
                    container.querySelectorAll('.drag-over-target').forEach((el) => el.classList.remove('drag-over-target'));
                    if (activeDragItem && activeDragGroup === groupId) {
                        saveGroupOrder(groupId, container);
                        // Trigger resize for embedded canvases (Swarm Deck / Tiger Radar) if reordered
                        setTimeout(() => {
                            window.dispatchEvent(new Event('resize'));
                            if (typeof window.resizeSwarmCanvas === 'function') window.resizeSwarmCanvas();
                        }, 60);
                    }
                    activeDragItem = null;
                    activeDragGroup = null;
                });

                item.addEventListener('dragover', (e) => {
                    if (!activeDragItem || activeDragGroup !== groupId || activeDragItem === item) return;
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'move';
                    item.classList.add('drag-over-target');
                });

                item.addEventListener('dragleave', () => {
                    item.classList.remove('drag-over-target');
                });

                item.addEventListener('drop', (e) => {
                    if (!activeDragItem || activeDragGroup !== groupId || activeDragItem === item) return;
                    e.preventDefault();
                    item.classList.remove('drag-over-target');

                    const children = Array.from(container.children);
                    const fromIdx = children.indexOf(activeDragItem);
                    const toIdx = children.indexOf(item);
                    if (fromIdx < 0 || toIdx < 0) return;

                    if (fromIdx < toIdx) {
                        container.insertBefore(activeDragItem, item.nextSibling);
                    } else {
                        container.insertBefore(activeDragItem, item);
                    }
                    saveGroupOrder(groupId, container);
                });
            });
        });
    }

    // ------------------------------------------------------------------------
    // 4. COLLAPSIBLE PANELS
    // ------------------------------------------------------------------------
    function initCollapsiblePanels() {
        document.querySelectorAll('[data-collapsible="true"]').forEach((panel) => {
            const header = panel.querySelector(':scope > .panel-header');
            if (!header || header.querySelector('.panel-collapse-btn')) return;

            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'panel-collapse-btn';
            btn.title = 'Collapse / Expand section';
            btn.setAttribute('aria-label', 'Toggle section visibility');
            btn.innerHTML = CHEVRON_SVG;

            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                panel.classList.toggle('is-collapsed');
            });

            let actions = header.querySelector(':scope > .panel-header-actions');
            if (!actions) {
                actions = document.createElement('div');
                actions.className = 'panel-header-actions';
                header.appendChild(actions);
            }
            actions.appendChild(btn);
        });
    }

    // ------------------------------------------------------------------------
    // 5. CLICK-AND-DRAG HORIZONTAL PANNING ON TABLES, MATRICES & STRIPS
    // ------------------------------------------------------------------------
    function bindPannableElement(el) {
        if (el.dataset.panBound === 'true') return;
        el.dataset.panBound = 'true';

        let isDown = false;
        let hasDragged = false;
        let startX = 0;
        let startScrollLeft = 0;

        el.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            // Ignore interactive controls inside scrollable areas
            if (e.target.closest('button, a, input, select, textarea, .drag-handle')) return;
            // Only engage pan if content actually overflows horizontally
            if (el.scrollWidth <= el.clientWidth + 2) return;

            isDown = true;
            hasDragged = false;
            startX = e.pageX;
            startScrollLeft = el.scrollLeft;
        });

        window.addEventListener('mousemove', (e) => {
            if (!isDown) return;
            const dx = e.pageX - startX;
            if (!hasDragged && Math.abs(dx) > 5) {
                hasDragged = true;
                el.classList.add('is-panning');
            }
            if (hasDragged) {
                e.preventDefault();
                el.scrollLeft = startScrollLeft - dx * 1.15;
            }
        });

        window.addEventListener('mouseup', () => {
            if (!isDown) return;
            isDown = false;
            if (hasDragged) {
                el.classList.remove('is-panning');
                // Suppress accidental click right after dragging
                const blockClick = (ev) => {
                    ev.stopPropagation();
                    ev.preventDefault();
                };
                el.addEventListener('click', blockClick, { capture: true, once: true });
                setTimeout(() => el.removeEventListener('click', blockClick, { capture: true }), 40);
            }
            hasDragged = false;
        });
    }

    function initPannableSurfaces() {
        const selectors = '[data-pannable="x"], .table-scroll-wrap, .ym-scroll-wrap, .workspace-status-strip, .nav-tabs';
        document.querySelectorAll(selectors).forEach(bindPannableElement);
    }

    // ------------------------------------------------------------------------
    // 6. STALKING TIGER RESIZABLE VERTICAL SPLITTER (RADAR <-> TACTICAL DECK)
    // ------------------------------------------------------------------------
    function initTigerSplitter() {
        const splitter = document.getElementById('tiger-v-splitter');
        const grid = document.getElementById('tiger-main-grid');
        const leftPane = document.getElementById('tiger-radar-pane');
        const rightPane = document.getElementById('tiger-tactical-pane');
        if (!splitter || !grid || !leftPane || !rightPane) return;

        let isResizing = false;

        splitter.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            isResizing = true;
            splitter.classList.add('dragging');
            document.body.classList.add('is-panning');
            e.preventDefault();
        });

        window.addEventListener('mousemove', (e) => {
            if (!isResizing) return;
            const rect = grid.getBoundingClientRect();
            const offsetX = e.clientX - rect.left;
            const totalW = rect.width;
            if (totalW <= 0) return;

            const pct = Math.max(36, Math.min(72, (offsetX / totalW) * 100));
            leftPane.style.flex = `0 0 ${pct.toFixed(1)}%`;
            rightPane.style.flex = `1 1 ${(100 - pct).toFixed(1)}%`;

            if (typeof window.resizeTigerRadarCanvas === 'function') {
                window.resizeTigerRadarCanvas();
            }
        });

        window.addEventListener('mouseup', () => {
            if (!isResizing) return;
            isResizing = false;
            splitter.classList.remove('dragging');
            document.body.classList.remove('is-panning');
            if (typeof window.resizeTigerRadarCanvas === 'function') {
                window.resizeTigerRadarCanvas();
            }
        });
    }

    // ------------------------------------------------------------------------
    // 7. RESET WORKSPACE LAYOUT ACTION
    // ------------------------------------------------------------------------
    window.resetWorkspaceLayout = function () {
        try {
            localStorage.removeItem(LAYOUT_STORAGE_KEY);
        } catch (e) { }

        document.querySelectorAll('[data-drag-group]').forEach((container) => {
            const raw = container.dataset.defaultOrder;
            if (!raw) return;
            try {
                const defaultOrder = JSON.parse(raw);
                const map = new Map();
                Array.from(container.children).forEach((el) => {
                    const id = el.getAttribute('data-drag-item');
                    if (id) map.set(id, el);
                });
                defaultOrder.forEach((id) => {
                    const el = map.get(id);
                    if (el) container.appendChild(el);
                });
            } catch (e) { }
        });

        // Uncollapse all panels
        document.querySelectorAll('.panel.is-collapsed').forEach((p) => p.classList.remove('is-collapsed'));

        // Reset Tiger splitter proportions
        const leftPane = document.getElementById('tiger-radar-pane');
        const rightPane = document.getElementById('tiger-tactical-pane');
        if (leftPane) leftPane.style.flex = '';
        if (rightPane) rightPane.style.flex = '';

        // Reset interactive cameras
        if (typeof window.resetSwarmView === 'function') window.resetSwarmView();
        if (typeof window.tigerResetView === 'function') window.tigerResetView();

        setTimeout(() => {
            window.dispatchEvent(new Event('resize'));
            if (typeof window.resizeSwarmCanvas === 'function') window.resizeSwarmCanvas();
            if (typeof window.resizeTigerRadarCanvas === 'function') window.resizeTigerRadarCanvas();
        }, 60);

        showKronosToast('Workspace layout, panel order & views reset to default.', 'info');
    };

    // Initialize on DOM Ready
    function initAllWorkspaceInteractions() {
        initDraggableGroups();
        initCollapsiblePanels();
        initPannableSurfaces();
        initTigerSplitter();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAllWorkspaceInteractions);
    } else {
        initAllWorkspaceInteractions();
    }
})();
