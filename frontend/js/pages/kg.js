// ===== 肿瘤知识图谱页面 v3.0（医疗） =====
// 本体（实体类型 / 关系类型 / 配色 / 形状）由后端 /kg/ontology 提供，前端不再硬编码本体。
var KG_ONTOLOGY = { entities: [], relations: [] };
var KG_TYPE_MAP = {};      // entity_type -> { label, color, shape }
var KG_REL_COLORS = {};    // relation_type -> color

// 关系配色（循环取用，保证相邻关系视觉可分辨）
var _REL_PALETTE = ['#8B5CF6', '#0EA5E9', '#F59E0B', '#10B981', '#EF4444',
                    '#EC4899', '#14B8A6', '#6366F1', '#84CC16'];

function buildOntologyMaps() {
    KG_TYPE_MAP = {};
    (KG_ONTOLOGY.entities || []).forEach(function (e) {
        KG_TYPE_MAP[e.type] = { label: e.label, color: e.color || '#6B7280', shape: e.shape || 'ellipse' };
    });
    KG_REL_COLORS = {};
    (KG_ONTOLOGY.relations || []).forEach(function (r, i) {
        KG_REL_COLORS[r.type] = _REL_PALETTE[i % _REL_PALETTE.length];
    });
}

function nodeColor(n) {
    if (n.entity_color) return n.entity_color;
    var t = KG_TYPE_MAP[n.entity_type];
    return (t && t.color) || '#6B7280';
}
function nodeShape(n) {
    var t = KG_TYPE_MAP[n.entity_type];
    return (t && t.shape) || 'ellipse';
}
function typeLabel(n) {
    if (n.entity_label) return n.entity_label;
    var t = KG_TYPE_MAP[n.entity_type];
    return (t && t.label) || n.entity_type || '实体';
}
function edgeColor(e) {
    return KG_REL_COLORS[e.relation_type] || e.color || '#94A3B8';
}

registerPage('kg', function (container) {
    container.innerHTML = `
        <style>
        .kg-mode-btn {
            padding:0.375rem 0.875rem;border:1px solid var(--color-border);
            background:var(--color-card-bg);color:var(--color-text-secondary);
            border-radius:6px;cursor:pointer;font-size:0.8125rem;transition:all 0.15s;
        }
        .kg-mode-btn:hover { background:var(--color-bg); }
        .kg-mode-btn.active { background:var(--color-primary);color:#fff;border-color:var(--color-primary); }
        .kg-entity-item {
            padding:0.4rem 0.6rem;border:1px solid var(--color-border);border-radius:6px;
            cursor:pointer;font-size:0.8125rem;display:flex;justify-content:space-between;
            align-items:center;gap:0.5rem;background:var(--color-card-bg);
        }
        .kg-entity-item:hover { background:var(--color-bg);border-color:var(--color-primary); }
        </style>
        <h1 class="page-title">肿瘤知识图谱</h1>
        <p class="page-desc">以癌种为中心，探索基因、药物、治疗、分期、症状、检查、不良反应之间的循证关联。</p>
        <hr class="divider">

        <!-- 模式切换 -->
        <div style="margin-bottom:1rem;">
            <div class="kg-mode-tabs" style="display:flex;gap:0.5rem;">
                <button class="kg-mode-btn active" data-mode="cancer" onclick="switchKGMode('cancer')">癌种全景</button>
                <button class="kg-mode-btn" data-mode="search" onclick="switchKGMode('search')">实体搜索</button>
                <button class="kg-mode-btn" data-mode="browse" onclick="switchKGMode('browse')">实体浏览</button>
            </div>
        </div>

        <!-- 模式1：癌种全景 -->
        <div id="kg-cancer-panel" class="kg-panel">
            <div class="card" style="padding:1rem;">
                <label style="font-size:0.8125rem;font-weight:600;color:var(--color-text-secondary);display:block;margin-bottom:0.25rem;">选择癌种</label>
                <div style="display:flex;gap:0.5rem;">
                    <select id="kg-cancer-select" class="select" style="flex:1;"></select>
                    <button class="btn btn-primary" onclick="loadCancerGraph()">查看图谱</button>
                </div>
                <div style="font-size:0.75rem;color:var(--color-text-muted);margin-top:0.375rem;">展示该癌种相关的基因、药物、治疗、分期、症状、检查与不良反应子图</div>
            </div>
        </div>

        <!-- 模式2：实体搜索 -->
        <div id="kg-search-panel" class="kg-panel" style="display:none;">
            <div class="card" style="padding:1rem;">
                <label style="font-size:0.8125rem;font-weight:600;color:var(--color-text-secondary);display:block;margin-bottom:0.25rem;">搜索医学实体</label>
                <div style="display:flex;gap:0.5rem;">
                    <input type="text" id="kg-search-input" class="input" placeholder="例如：肺癌、EGFR、奥希替尼、靶向治疗" style="flex:1;" onkeydown="if(event.key==='Enter')searchKGEntities()">
                    <button class="btn btn-primary" onclick="searchKGEntities()">搜索</button>
                </div>
                <div style="font-size:0.75rem;color:var(--color-text-muted);margin-top:0.375rem;">按规范名或别名匹配；点击结果查看该实体的邻域图谱</div>
                <div id="kg-search-results" style="margin-top:0.5rem;display:flex;flex-direction:column;gap:0.375rem;"></div>
            </div>
        </div>

        <!-- 模式3：实体浏览 -->
        <div id="kg-browse-panel" class="kg-panel" style="display:none;">
            <div class="card" style="padding:1rem;">
                <label style="font-size:0.8125rem;font-weight:600;color:var(--color-text-secondary);display:block;margin-bottom:0.25rem;">按类型浏览实体</label>
                <div style="display:flex;gap:0.5rem;">
                    <select id="kg-browse-type" class="select" style="flex:1;"></select>
                    <button class="btn btn-primary" onclick="browseEntities()">浏览</button>
                </div>
                <div id="kg-browse-results" style="margin-top:0.5rem;display:flex;flex-direction:column;gap:0.375rem;max-height:320px;overflow-y:auto;"></div>
            </div>
        </div>

        <!-- 图谱容器 -->
        <div class="card" style="margin-top:0.75rem;padding:0;">
            <div style="display:flex;justify-content:space-between;align-items:center;padding:0.625rem 1rem;border-bottom:1px solid var(--color-border);">
                <div id="kg-graph-title" class="kg-graph-title" style="font-weight:600;font-size:0.8125rem;color:var(--color-text);"></div>
                <div style="display:flex;gap:0.375rem;">
                    <button class="btn btn-sm" onclick="toggleKGLayout()" id="kg-layout-btn" style="font-size:0.75rem;">布局：力导向</button>
                    <button class="btn btn-sm" onclick="resetKGView()" style="font-size:0.75rem;">重置视图</button>
                    <button class="btn btn-sm" onclick="fitKGView()" style="font-size:0.75rem;">适应布局</button>
                </div>
            </div>
            <div id="kg-canvas-container" style="position:relative;height:500px;background:var(--color-bg);overflow:hidden;cursor:grab;">
                <canvas id="kg-canvas" style="width:100%;height:100%;"></canvas>
                <div id="kg-tooltip" style="position:absolute;display:none;background:rgba(255,255,255,0.96);border:1px solid var(--color-border);border-radius:6px;padding:0.5rem 0.75rem;font-size:0.75rem;max-width:280px;box-shadow:0 4px 12px rgba(0,0,0,0.08);pointer-events:none;z-index:10;"></div>
                <!-- 图例 -->
                <div id="kg-legend" style="position:absolute;bottom:6px;left:6px;background:rgba(255,255,255,0.94);border:1px solid var(--color-border);border-radius:6px;padding:5px 9px;font-size:0.65rem;color:var(--color-text-secondary);z-index:5;line-height:1.7;pointer-events:none;max-width:calc(100% - 12px);">
                    <div id="kg-legend-types" style="display:flex;flex-wrap:wrap;gap:0.2rem 0.6rem;"></div>
                    <div style="display:flex;flex-wrap:wrap;gap:0.2rem 0.6rem;margin-top:1px;">
                        <span style="font-weight:600;min-width:3em;">节点大小：</span>
                        <span><span style="display:inline-block;width:13px;height:13px;background:#6B7280;border-radius:50%;vertical-align:middle;"></span> 高连接</span>
                        <span><span style="display:inline-block;width:9px;height:9px;background:#6B7280;border-radius:50%;vertical-align:middle;"></span> 中连接</span>
                        <span><span style="display:inline-block;width:6px;height:6px;background:#6B7280;border-radius:50%;vertical-align:middle;"></span> 低连接</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- 控制栏 -->
        <div class="card" style="margin-top:0.5rem;padding:0.625rem 1rem;">
            <div style="display:flex;gap:1rem;flex-wrap:wrap;align-items:center;font-size:0.8125rem;">
                <label style="display:flex;align-items:center;gap:0.375rem;color:var(--color-text-secondary);">
                    置信度阈值
                    <input type="range" id="kg-edge-threshold" min="0" max="1" step="0.05" value="0" style="width:80px;">
                    <span id="kg-threshold-val" style="font-weight:600;min-width:2rem;">0.00</span>
                </label>
                <label style="display:flex;align-items:center;gap:0.25rem;color:var(--color-text-secondary);">
                    标签
                    <select id="kg-label-mode" class="select" style="width:auto;font-size:0.75rem;">
                        <option value="smart">智能</option>
                        <option value="core">仅核心</option>
                        <option value="all">全部</option>
                        <option value="none">无</option>
                    </select>
                </label>
                <span style="color:var(--color-text-muted);font-size:0.75rem;" id="kg-stats-badge"></span>
            </div>
            <div style="font-size:0.7rem;color:var(--color-text-muted);margin-top:0.25rem;">提示：力导向布局更易识别核心实体，圆形布局适合查看整体结构</div>
        </div>

        <!-- 详情面板 -->
        <div id="kg-detail-panel" style="display:none;margin-top:0.5rem;"></div>

        <!-- 智能洞察 -->
        <div id="kg-insight-panel" class="card" style="margin-top:0.5rem;padding:0.625rem 1rem;display:none;">
            <div style="font-weight:600;font-size:0.8125rem;color:var(--color-text);margin-bottom:0.25rem;">图谱洞察</div>
            <div id="kg-insight-text" style="font-size:0.8125rem;color:var(--color-text-secondary);line-height:1.7;"></div>
        </div>
    `;

    // 加载本体 -> 构建映射 -> 填充下拉
    api.get('/kg/ontology').then(function (resp) {
        if (resp && resp.success && resp.data) {
            KG_ONTOLOGY = resp.data;
        }
        buildOntologyMaps();
        renderLegend();
        initCancerSelect();
        initBrowseTypeSelect();
    }).catch(function () {
        buildOntologyMaps();
        renderLegend();
        initCancerSelect();
        initBrowseTypeSelect();
    });
});

function initCancerSelect() {
    var sel = document.getElementById('kg-cancer-select');
    if (!sel) return;
    api.get('/search/cancer_types').then(function (resp) {
        var list = (resp && resp.data) || [];
        sel.innerHTML = '';
        list.forEach(function (c) {
            var opt = document.createElement('option');
            opt.value = c.code;
            opt.textContent = c.label_zh || c.code;
            sel.appendChild(opt);
        });
    }).catch(function () {
        sel.innerHTML = '<option value="">加载失败</option>';
    });
}

function initBrowseTypeSelect() {
    var sel = document.getElementById('kg-browse-type');
    if (!sel) return;
    sel.innerHTML = '';
    (KG_ONTOLOGY.entities || []).forEach(function (e) {
        var opt = document.createElement('option');
        opt.value = e.type;
        opt.textContent = e.label;
        sel.appendChild(opt);
    });
}

function renderLegend() {
    var box = document.getElementById('kg-legend-types');
    if (!box) return;
    var html = '<span style="font-weight:600;min-width:3em;">类型：</span>';
    html += (KG_ONTOLOGY.entities || []).map(function (e) {
        return '<span><span class="kg-legend-icon" style="display:inline-block;width:8px;height:8px;background:' + e.color + ';border-radius:50%;"></span> ' + escapeHtml(e.label) + '</span>';
    }).join('');
    box.innerHTML = html;
}

// ===== 模式切换 =====
window.switchKGMode = function (mode) {
    document.querySelectorAll('.kg-mode-btn').forEach(function (b) {
        b.classList.toggle('active', b.dataset.mode === mode);
    });
    document.querySelectorAll('.kg-panel').forEach(function (p) { p.style.display = 'none'; });
    var panel = document.getElementById('kg-' + mode + '-panel');
    if (panel) panel.style.display = 'block';
};

function clearGraph() {
    if (window._kgState) window._kgState.running = false;
    window._kgState = null;
    var ip = document.getElementById('kg-insight-panel');
    if (ip) ip.style.display = 'none';
    var canvas = document.getElementById('kg-canvas');
    if (canvas) {
        var ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    document.getElementById('kg-graph-title').textContent = '';
    document.getElementById('kg-detail-panel').style.display = 'none';
    document.getElementById('kg-stats-badge').textContent = '';
}

// ===== 渲染图谱 =====
function renderKG(data, title, layoutMode) {
    clearGraph();
    var nodes = (data.nodes || []).slice();
    var edges = (data.edges || []).slice();
    if (nodes.length === 0) { document.getElementById('kg-graph-title').textContent = '暂无数据'; return; }

    document.getElementById('kg-graph-title').textContent = title || '知识图谱';
    var badgeText = nodes.length + ' 实体 | ' + edges.length + ' 关系';
    document.getElementById('kg-stats-badge').innerHTML = badgeText;

    var canvas = document.getElementById('kg-canvas');
    var container = document.getElementById('kg-canvas-container');
    if (!canvas || !container) return;

    var dpr = window.devicePixelRatio || 1;
    var width = container.clientWidth;
    var height = container.clientHeight;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    var isCircular = layoutMode === 'circular';
    var positions = {}, velocities = {};
    var cx = width / 2, cy = height / 2;

    if (isCircular && nodes.length > 0) {
        var baseRadius = Math.min(width, height) * 0.38;
        var maxDeg = 0;
        nodes.forEach(function (n) { maxDeg = Math.max(maxDeg, n.degree || 0); });
        var sorted = nodes.slice().sort(function (a, b) { return (b.degree || 0) - (a.degree || 0); });
        sorted.forEach(function (n, i) {
            var angle = (i / nodes.length) * Math.PI * 2 + (Math.random() - 0.5) * 0.3;
            var degRatio = maxDeg > 0 ? ((n.degree || 0) / maxDeg) : 0.5;
            var r = baseRadius * (0.35 + (1 - degRatio * 0.6) * 0.65);
            r += (Math.random() - 0.5) * baseRadius * 0.2;
            positions[n.id] = { x: cx + Math.cos(angle) * r, y: cy + Math.sin(angle) * r };
            velocities[n.id] = { x: 0, y: 0 };
        });
    } else {
        // 按实体类型聚簇
        var groups = {};
        nodes.forEach(function (n) {
            var t = n.entity_type || '';
            if (!groups[t]) groups[t] = [];
            groups[t].push(n);
        });
        var typeList = Object.keys(groups);
        typeList.forEach(function (t, idx) {
            var group = groups[t];
            var clusterCx, clusterCy;
            if (typeList.length === 1) {
                clusterCx = cx; clusterCy = cy;
            } else {
                var angle = (idx / typeList.length) * Math.PI * 2;
                clusterCx = cx + Math.cos(angle) * Math.min(width, height) * 0.30;
                clusterCy = cy + Math.sin(angle) * Math.min(height, width) * 0.26;
            }
            group.forEach(function (node, i) {
                var ga = Math.PI * (3 - Math.sqrt(5));
                var a = i * ga + idx * 2.0;
                var r = 24 + Math.sqrt(i) * 20;
                positions[node.id] = { x: clusterCx + Math.cos(a) * r, y: clusterCy + Math.sin(a) * r };
                velocities[node.id] = { x: 0, y: 0 };
            });
        });
    }

    var state = {
        nodes: nodes, edges: edges, positions: positions, velocities: velocities,
        zoom: 1, panX: 0, panY: 0,
        hoveredNode: null, selectedNode: null, draggedNode: null,
        hoveredEdge: null, selectedEdge: null,
        edgeThreshold: parseFloat(document.getElementById('kg-edge-threshold').value),
        labelMode: document.getElementById('kg-label-mode').value,
        layoutTick: 0, maxLayoutTicks: isCircular ? 3 : 300, running: true,
        isCircular: isCircular, _time: 0
    };
    window._kgState = state;
    bindKGControls(state);
    generateKGInsight(data);

    function tick() {
        if (!state.running) return;
        if (state.layoutTick < state.maxLayoutTicks) {
            applyKGForces(state, width, height);
            state.layoutTick++;
        }
        state._time += 0.02;
        drawKG(ctx, state, width, height);
        requestAnimationFrame(tick);
    }
    tick();
    bindKGCanvas(canvas, container, state);
}

// ===== 力导向布局 =====
function applyKGForces(state, w, h) {
    var nodes = state.nodes, pos = state.positions, vel = state.velocities;
    var n = nodes.length, tick = state.layoutTick;
    var progress = tick / state.maxLayoutTicks;
    var temp = Math.max(0.05, 1 - progress * 0.96);
    var k = Math.sqrt(w * h / n) * 0.7;
    var rep = k * k * 1.2, spr = 0.018 * temp;

    var groups = {};
    nodes.forEach(function (node) { var t = node.entity_type || ''; if (!groups[t]) groups[t] = []; groups[t].push(node); });

    for (var i = 0; i < n; i++) {
        for (var j = i + 1; j < n; j++) {
            var ni = nodes[i], nj = nodes[j];
            var pi = pos[ni.id], pj = pos[nj.id];
            var dx = pi.x - pj.x, dy = pi.y - pj.y;
            var dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
            var sameType = (ni.entity_type || '') === (nj.entity_type || '');
            var force = rep * (sameType ? 1.0 : 1.8) / (dist * dist);
            vel[ni.id].x += (dx / dist) * force;
            vel[ni.id].y += (dy / dist) * force;
            vel[nj.id].x -= (dx / dist) * force;
            vel[nj.id].y -= (dy / dist) * force;
        }
    }

    state.edges.forEach(function (e) {
        var u = pos[e.from], v = pos[e.to];
        if (!u || !v) return;
        var dx = v.x - u.x, dy = v.y - u.y;
        var dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        var ideal = k * 1.4;
        var force = (dist - ideal) * spr;
        u.x += (dx / dist) * force; u.y += (dy / dist) * force;
        v.x -= (dx / dist) * force; v.y -= (dy / dist) * force;
    });

    Object.keys(groups).forEach(function (t) {
        var group = groups[t];
        if (group.length < 2) return;
        var gx = 0, gy = 0;
        group.forEach(function (node) { gx += pos[node.id].x; gy += pos[node.id].y; });
        gx /= group.length; gy /= group.length;
        group.forEach(function (node) {
            var p = pos[node.id];
            p.x += (gx - p.x) * 0.03 * temp;
            p.y += (gy - p.y) * 0.03 * temp;
        });
    });

    nodes.forEach(function (node) {
        var p = pos[node.id], v = vel[node.id];
        p.x += v.x * temp; p.y += v.y * temp;
        v.x *= 0.85; v.y *= 0.85;
        p.x = Math.max(20, Math.min(w - 20, p.x));
        p.y = Math.max(20, Math.min(h - 20, p.y));
    });
}

// ===== 绘制 =====
function drawKG(ctx, state, w, h) {
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.strokeStyle = 'rgba(0,0,0,0.035)';
    ctx.lineWidth = 0.5;
    for (var gx = 0; gx <= w; gx += 40) { ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, h); ctx.stroke(); }
    for (var gy = 0; gy <= h; gy += 40) { ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(w, gy); ctx.stroke(); }
    ctx.restore();

    ctx.save();
    ctx.translate(state.panX + w / 2, state.panY + h / 2);
    ctx.scale(state.zoom, state.zoom);
    ctx.translate(-w / 2, -h / 2);

    var si = 1 / Math.max(state.zoom, 0.1);

    var adj = {};
    state.nodes.forEach(function (n) { adj[n.id] = []; });
    state.edges.forEach(function (e) {
        if (adj[e.from]) adj[e.from].push(e.to);
        if (adj[e.to]) adj[e.to].push(e.from);
    });
    state._adj = adj;

    var neighborSet = {};
    if (state.hoveredNode && state._adj) {
        (state._adj[state.hoveredNode.id] || []).forEach(function (item) { neighborSet[item] = true; });
    }
    if (state.hoveredEdge && !state.hoveredNode) {
        neighborSet[state.hoveredEdge.from] = true;
        neighborSet[state.hoveredEdge.to] = true;
    }

    // 边
    state.edges.forEach(function (e) {
        var u = state.positions[e.from], v = state.positions[e.to];
        if (!u || !v) return;
        if (e.similarity != null && e.similarity < state.edgeThreshold) return;

        var midX = (u.x + v.x) / 2, midY = (u.y + v.y) / 2;
        var dx = v.x - u.x, dy = v.y - u.y;
        var dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        var curv = 0.08;
        var ctrlX = midX - (dy / dist) * dist * curv;
        var ctrlY = midY + (dx / dist) * dist * curv;

        var isNodeHovered = state.hoveredNode && (state.hoveredNode.id === e.from || state.hoveredNode.id === e.to);
        var isEdgeHovered = state.hoveredEdge && state.hoveredEdge.from === e.from && state.hoveredEdge.to === e.to;
        var isHovered = isNodeHovered || isEdgeHovered;

        ctx.beginPath();
        ctx.moveTo(u.x, u.y);
        ctx.quadraticCurveTo(ctrlX, ctrlY, v.x, v.y);

        var base = edgeColor(e);
        if (isHovered) {
            ctx.strokeStyle = base; ctx.lineWidth = 2.6 * si; ctx.globalAlpha = 0.95;
        } else if (state.hoveredNode || state.hoveredEdge) {
            ctx.strokeStyle = '#CBD5E1'; ctx.lineWidth = 0.7 * si; ctx.globalAlpha = 0.08;
        } else {
            ctx.strokeStyle = base; ctx.lineWidth = 1.5 * si; ctx.globalAlpha = 0.55;
        }
        ctx.stroke();
        ctx.globalAlpha = 1;

        // 端点圆点
        ctx.save();
        ctx.fillStyle = isHovered ? base : '#94A3B8';
        ctx.globalAlpha = isHovered ? 0.7 : 0.28;
        ctx.beginPath(); ctx.arc(u.x, u.y, 2.4 * si, 0, Math.PI * 2); ctx.fill();
        ctx.beginPath(); ctx.arc(v.x, v.y, 2.4 * si, 0, Math.PI * 2); ctx.fill();
        ctx.restore();
    });

    var degThreshold = 0;
    if (state.nodes.length > 12) {
        var degs = state.nodes.map(function (n) { return n.degree || 0; }).sort(function (a, b) { return a - b; });
        degThreshold = degs[Math.floor(degs.length * 0.7)] || 1;
    }

    ctx.shadowColor = 'rgba(0,0,0,0.10)';
    ctx.shadowBlur = 6 * si;
    ctx.shadowOffsetY = 3 * si;

    // 节点
    state.nodes.forEach(function (n) {
        var p = state.positions[n.id];
        if (!p) return;
        var shape = nodeShape(n);
        var deg = n.degree || 0;
        var baseR = deg >= 8 ? 13 : (deg >= 3 ? 9 : (deg >= 1 ? 6 : 4));
        var radius = (n.is_core ? Math.max(baseR, 12) : baseR) * si;
        var isHovered = state.hoveredNode && state.hoveredNode.id === n.id;
        var isSelected = state.selectedNode && state.selectedNode.id === n.id;
        var isDimmed = (state.hoveredNode && !isHovered && !neighborSet[n.id]) ||
                       (state.hoveredEdge && !state.hoveredNode && !neighborSet[n.id]);

        if (isDimmed) ctx.globalAlpha = 0.18;

        if (isHovered || isSelected) {
            ctx.save();
            ctx.shadowColor = 'transparent'; ctx.shadowBlur = 0;
            ctx.beginPath();
            ctx.arc(p.x, p.y, radius + 10 * si, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(245,158,11,0.15)';
            ctx.fill();
            ctx.restore();
        }

        ctx.save();
        var color = nodeColor(n);
        var grad = ctx.createRadialGradient(p.x - radius * 0.3, p.y - radius * 0.3, radius * 0.1, p.x, p.y, radius);
        grad.addColorStop(0, lightenColor(color, 40));
        grad.addColorStop(1, color);

        ctx.beginPath();
        if (shape === 'diamond') {
            ctx.moveTo(p.x, p.y - radius);
            ctx.lineTo(p.x + radius * 1.15, p.y);
            ctx.lineTo(p.x, p.y + radius);
            ctx.lineTo(p.x - radius * 1.15, p.y);
        } else if (shape === 'triangle') {
            var triH = radius * 1.15;
            ctx.moveTo(p.x, p.y - triH);
            ctx.lineTo(p.x + triH * 0.866, p.y + triH * 0.5);
            ctx.lineTo(p.x - triH * 0.866, p.y + triH * 0.5);
        } else if (shape === 'roundRect') {
            var rw = radius * 1.6, rh = radius * 1.1, rr = radius * 0.35;
            var hw = rw / 2, hh = rh / 2;
            ctx.moveTo(p.x + hw - rr, p.y - hh);
            ctx.lineTo(p.x - hw + rr, p.y - hh);
            ctx.arcTo(p.x - hw, p.y - hh, p.x - hw, p.y - hh + rr, rr);
            ctx.lineTo(p.x - hw, p.y + hh - rr);
            ctx.arcTo(p.x - hw, p.y + hh, p.x - hw + rr, p.y + hh, rr);
            ctx.lineTo(p.x + hw - rr, p.y + hh);
            ctx.arcTo(p.x + hw, p.y + hh, p.x + hw, p.y + hh - rr, rr);
            ctx.lineTo(p.x + hw, p.y - hh + rr);
            ctx.arcTo(p.x + hw, p.y - hh, p.x + hw - rr, p.y - hh, rr);
        } else {
            ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
        }
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();

        ctx.shadowColor = 'transparent'; ctx.shadowBlur = 0;
        ctx.lineWidth = (isSelected ? 3 : 1.8) * si;
        ctx.strokeStyle = isSelected ? '#F59E0B' : (isHovered ? '#FFFFFF' : 'rgba(255,255,255,0.85)');
        ctx.stroke();
        ctx.restore();

        if (isDimmed) ctx.globalAlpha = 1;

        var showLabel = (state.labelMode === 'all') ||
            (state.labelMode === 'core' && (isHovered || isSelected || n.is_core)) ||
            (state.labelMode === 'smart' && (isHovered || isSelected || n.is_core || (n.degree || 0) >= degThreshold));
        if (state.labelMode === 'none') showLabel = isHovered || isSelected;

        if (showLabel) {
            ctx.save();
            ctx.shadowColor = 'transparent'; ctx.shadowBlur = 0;
            ctx.font = Math.max(8, 11 * si) + 'px "Inter", "Noto Sans SC", sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            var label = n.label || n.title || n.id || '';
            var maxLen = state.zoom >= 1.5 ? 24 : 12;
            var text = label.length > maxLen ? label.substring(0, maxLen) + '…' : label;
            var labelY = p.y + radius + 4 * si;
            ctx.fillStyle = 'rgba(255,255,255,0.7)';
            ctx.fillText(text, p.x + 0.8 * si, labelY + 0.8 * si);
            ctx.fillStyle = '#1F2937';
            ctx.fillText(text, p.x, labelY);
            ctx.restore();
        }
    });

    ctx.restore();
}

function lightenColor(color, amount) {
    if (!color) return '#9CA3AF';
    if (color.charAt(0) !== '#') return color;
    color = color.replace('#', '');
    var r = parseInt(color.substring(0, 2), 16);
    var g = parseInt(color.substring(2, 4), 16);
    var b = parseInt(color.substring(4, 6), 16);
    r = Math.min(255, r + amount);
    g = Math.min(255, g + amount);
    b = Math.min(255, b + amount);
    return '#' + [r, g, b].map(function (c) { return c.toString(16).padStart(2, '0'); }).join('');
}

// ===== Canvas 交互 =====
function bindKGCanvas(canvas, container, state) {
    function getPos(evt) {
        var rect = canvas.getBoundingClientRect();
        return {
            x: (evt.clientX - rect.left - state.panX - rect.width / 2) / state.zoom + rect.width / 2,
            y: (evt.clientY - rect.top - state.panY - rect.height / 2) / state.zoom + rect.height / 2,
            clientX: evt.clientX, clientY: evt.clientY
        };
    }
    function findNode(pos) {
        for (var i = state.nodes.length - 1; i >= 0; i--) {
            var n = state.nodes[i], p = state.positions[n.id];
            if (!p) continue;
            var r = (8 + Math.min(6, (n.degree || 0) * 0.5)) / Math.max(state.zoom, 0.1);
            var dx = pos.x - p.x, dy = pos.y - p.y;
            if (dx * dx + dy * dy <= r * r) return n;
        }
        return null;
    }
    function findEdge(pos) {
        var hitThreshold = 8 / Math.max(state.zoom, 0.1);
        var bestEdge = null, bestDist = hitThreshold;
        state.edges.forEach(function (e) {
            var u = state.positions[e.from], v = state.positions[e.to];
            if (!u || !v) return;
            if (e.similarity != null && e.similarity < state.edgeThreshold) return;
            var midX = (u.x + v.x) / 2, midY = (u.y + v.y) / 2;
            var dx = v.x - u.x, dy = v.y - u.y;
            var dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
            var ctrlX = midX - (dy / dist) * dist * 0.08;
            var ctrlY = midY + (dx / dist) * dist * 0.08;
            for (var t = 0; t <= 1; t += 0.083) {
                var mt = 1 - t;
                var px = mt * mt * u.x + 2 * mt * t * ctrlX + t * t * v.x;
                var py = mt * mt * u.y + 2 * mt * t * ctrlY + t * t * v.y;
                var ddx = pos.x - px, ddy = pos.y - py;
                var d = Math.sqrt(ddx * ddx + ddy * ddy);
                if (d < bestDist) { bestDist = d; bestEdge = e; }
            }
        });
        return bestEdge;
    }

    canvas.addEventListener('mousemove', function (e) {
        var pos = getPos(e);
        var node = findNode(pos);
        var edge = node ? null : findEdge(pos);
        state.hoveredNode = node;
        state.hoveredEdge = edge;
        canvas.style.cursor = (node || edge) ? 'pointer' : 'grab';

        var tooltip = document.getElementById('kg-tooltip');
        if (node && tooltip) {
            tooltip.style.display = 'block';
            tooltip.style.left = (pos.clientX - container.getBoundingClientRect().left + 12) + 'px';
            tooltip.style.top = (pos.clientY - container.getBoundingClientRect().top + 12) + 'px';
            tooltip.innerHTML = '<div style="font-weight:600;color:var(--color-text);margin-bottom:0.25rem;">' + escapeHtml(node.label || node.id) + '</div>' +
                '<div style="color:var(--color-text-muted);margin-bottom:0.25rem;">' + escapeHtml(typeLabel(node)) + ' | 连接 ' + (node.degree || 0) + '</div>' +
                '<div style="color:var(--color-text-secondary);font-size:0.7rem;">点击查看邻域</div>';
        } else if (edge && tooltip) {
            tooltip.style.display = 'block';
            tooltip.style.left = (pos.clientX - container.getBoundingClientRect().left + 12) + 'px';
            tooltip.style.top = (pos.clientY - container.getBoundingClientRect().top + 12) + 'px';
            tooltip.innerHTML = '<div style="font-weight:600;color:var(--color-text);margin-bottom:0.25rem;">' + escapeHtml(edge.relation_label || edge.label || edge.relation_type || '关联') + '</div>' +
                '<div style="color:var(--color-text-secondary);font-size:0.8125rem;">' +
                escapeHtml(edge.from) + ' <span style="color:var(--color-text-muted);">→</span> ' + escapeHtml(edge.to) + '</div>' +
                '<div style="color:var(--color-text-muted);font-size:0.75rem;">置信度 ' + (edge.similarity != null ? edge.similarity.toFixed(2) : '-') + '</div>';
        } else if (tooltip) {
            tooltip.style.display = 'none';
        }
    });

    canvas.addEventListener('mouseleave', function () {
        state.hoveredNode = null;
        state.hoveredEdge = null;
        var tooltip = document.getElementById('kg-tooltip');
        if (tooltip) tooltip.style.display = 'none';
    });

    canvas.addEventListener('mousedown', function (e) {
        var pos = getPos(e);
        var node = findNode(pos);
        if (node) {
            state.selectedNode = node;
            state.selectedEdge = null;
            state.draggedNode = node;
            var p = state.positions[node.id];
            state._dragOffX = p.x - pos.x;
            state._dragOffY = p.y - pos.y;
            showKGDetail(node);
            return;
        }
        var edge = findEdge(pos);
        if (edge) {
            state.selectedEdge = edge;
            state.selectedNode = null;
            state.draggedNode = null;
            showKGEdgeDetail(edge, state);
            return;
        }
        state.selectedNode = null;
        state.selectedEdge = null;
        document.getElementById('kg-detail-panel').style.display = 'none';
    });

    window.addEventListener('mousemove', function (e) {
        if (!state.draggedNode) return;
        var rect = canvas.getBoundingClientRect();
        var pos = {
            x: (e.clientX - rect.left - state.panX - rect.width / 2) / state.zoom + rect.width / 2,
            y: (e.clientY - rect.top - state.panY - rect.height / 2) / state.zoom + rect.height / 2
        };
        state.positions[state.draggedNode.id].x = pos.x + state._dragOffX || 0;
        state.positions[state.draggedNode.id].y = pos.y + state._dragOffY || 0;
    });
    window.addEventListener('mouseup', function () { state.draggedNode = null; });

    canvas.addEventListener('wheel', function (e) {
        e.preventDefault();
        state.zoom = Math.max(0.3, Math.min(3, state.zoom * (e.deltaY > 0 ? 0.9 : 1.1)));
    }, { passive: false });
}

// ===== 详情面板 =====
function showKGDetail(node) {
    var panel = document.getElementById('kg-detail-panel');
    var html = '<div class="card" style="padding:0.75rem 1rem;">';
    html += '<div style="margin-bottom:0.5rem;">';
    html += '<span class="badge" style="background:' + nodeColor(node) + ';color:#fff;">' + escapeHtml(typeLabel(node)) + '</span>';
    if (node.is_core) html += '<span class="badge badge-warning" style="margin-left:0.375rem;">核心</span>';
    html += '</div>';
    html += '<h3 style="font-size:1rem;font-weight:600;margin:0 0 0.5rem;color:var(--color-text);">' + escapeHtml(node.label || node.id) + '</h3>';
    html += '<div style="margin-bottom:0.25rem;font-size:0.8125rem;"><strong>连接度：</strong>' + (node.degree || 0) + '</div>';
    html += '<div style="margin-top:0.5rem;"><button class="btn btn-sm btn-primary" onclick="loadEntityNeighborhood(\'' + escapeHtml(String(node.id).replace(/'/g, "\\'")) + '\')">查看邻域图谱</button></div>';
    html += '</div>';
    panel.innerHTML = html;
    panel.style.display = 'block';
}

function showKGEdgeDetail(edge, state) {
    var panel = document.getElementById('kg-detail-panel');
    var fromNode = state.nodes.find(function (n) { return n.id === edge.from; });
    var toNode = state.nodes.find(function (n) { return n.id === edge.to; });
    var html = '<div class="card" style="padding:0.75rem 1rem;">';
    html += '<h3 style="font-size:1rem;font-weight:600;margin:0 0 0.75rem;color:var(--color-text);">' + escapeHtml(edge.relation_label || edge.label || '关联') + '</h3>';
    html += '<div style="display:flex;align-items:center;gap:0.5rem;font-size:0.8125rem;">';
    html += '<span style="padding:0.25rem 0.5rem;background:var(--color-bg);border-radius:6px;">' + escapeHtml(fromNode ? (fromNode.label || edge.from) : edge.from) + '</span>';
    html += '<span style="color:var(--color-text-muted);">→</span>';
    html += '<span style="padding:0.25rem 0.5rem;background:var(--color-bg);border-radius:6px;">' + escapeHtml(toNode ? (toNode.label || edge.to) : edge.to) + '</span>';
    html += '</div>';
    html += '<div style="margin-top:0.5rem;font-size:0.75rem;color:var(--color-text-muted);">置信度 ' + (edge.similarity != null ? edge.similarity.toFixed(2) : '-');
    if (edge.source_ref) html += ' | 来源条目 ' + escapeHtml(edge.source_ref);
    html += '</div>';
    html += '</div>';
    panel.innerHTML = html;
    panel.style.display = 'block';
}

function bindKGControls(state) {
    function sync() {
        state.edgeThreshold = parseFloat(document.getElementById('kg-edge-threshold').value);
        state.labelMode = document.getElementById('kg-label-mode').value;
        document.getElementById('kg-threshold-val').textContent = state.edgeThreshold.toFixed(2);
    }
    document.getElementById('kg-edge-threshold').addEventListener('input', sync);
    document.getElementById('kg-label-mode').addEventListener('change', sync);
    sync();
}

window.resetKGView = function () {
    var state = window._kgState;
    if (!state) return;
    state.zoom = 1; state.panX = 0; state.panY = 0;
};

window.fitKGView = function () {
    var state = window._kgState;
    if (!state || state.nodes.length === 0) return;
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    state.nodes.forEach(function (n) {
        var p = state.positions[n.id];
        if (p) { minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x); minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y); }
    });
    if (!isFinite(minX)) return;
    var w = document.getElementById('kg-canvas-container').clientWidth;
    var h = document.getElementById('kg-canvas-container').clientHeight;
    var gw = maxX - minX + 60, gh = maxY - minY + 60;
    state.zoom = Math.min(w / gw, h / gh, 2);
    state.panX = (w / 2 - (minX + maxX) / 2) * state.zoom;
    state.panY = (h / 2 - (minY + maxY) / 2) * state.zoom;
};

// ===== 图谱洞察 =====
function generateKGInsight(data) {
    var nodes = data.nodes || [];
    var edges = data.edges || [];
    var ip = document.getElementById('kg-insight-panel');
    if (nodes.length === 0) { ip.style.display = 'none'; return; }

    var byType = {};
    nodes.forEach(function (n) {
        var t = typeLabel(n);
        byType[t] = (byType[t] || 0) + 1;
    });
    var coreNodes = nodes.filter(function (n) { return n.is_core || (n.degree || 0) >= 8; });

    var parts = [];
    parts.push('该图谱包含 ' + nodes.length + ' 个实体、' + edges.length + ' 条关系');
    var typeParts = Object.keys(byType).map(function (t) { return t + ' ' + byType[t]; });
    if (typeParts.length) parts.push('实体分布：' + typeParts.join('、'));
    if (coreNodes.length > 0) {
        var coreLabels = coreNodes.slice(0, 5).map(function (n) { return n.label || n.id; });
        var text = '核心实体：' + coreLabels.join('、');
        if (coreNodes.length > 5) text += ' 等';
        parts.push(text);
    }
    document.getElementById('kg-insight-text').textContent = parts.join('；') + '。';
    ip.style.display = 'block';
}

// ===== 数据加载 =====
window.loadCancerGraph = function () {
    var code = document.getElementById('kg-cancer-select').value;
    if (!code) return;
    document.getElementById('kg-graph-title').textContent = '加载中...';
    api.get('/kg/cancer/' + encodeURIComponent(code)).then(function (resp) {
        if (resp && resp.success && resp.data) {
            var d = resp.data;
            renderKG(d.graph, (d.cancer_name || code) + ' 知识图谱', window._kgLayoutMode);
        } else {
            clearGraph();
            document.getElementById('kg-graph-title').textContent = (resp && resp.message) || '暂无数据';
        }
    }).catch(function () {
        document.getElementById('kg-graph-title').textContent = '请求失败';
    });
};

window.searchKGEntities = function () {
    var q = document.getElementById('kg-search-input').value.trim();
    if (!q) return;
    var box = document.getElementById('kg-search-results');
    box.innerHTML = '<div style="font-size:0.8125rem;color:var(--color-text-muted);">搜索中...</div>';
    api.get('/kg/entity/search', { q: q, limit: 30 }).then(function (resp) {
        var list = (resp && resp.data && resp.data.entities) || [];
        if (!list.length) {
            box.innerHTML = '<div class="alert alert-info">未找到相关实体，请尝试其他关键词</div>';
            return;
        }
        box.innerHTML = '';
        list.forEach(function (e) { box.appendChild(entityItem(e)); });
    }).catch(function () {
        box.innerHTML = '<div class="alert alert-info">搜索请求失败</div>';
    });
};

window.browseEntities = function () {
    var type = document.getElementById('kg-browse-type').value;
    if (!type) return;
    var box = document.getElementById('kg-browse-results');
    box.innerHTML = '<div style="font-size:0.8125rem;color:var(--color-text-muted);">加载中...</div>';
    api.get('/kg/entities', { entity_type: type, page_size: 200 }).then(function (resp) {
        var list = (resp && resp.data) || [];
        if (!list.length) {
            box.innerHTML = '<div class="alert alert-info">该类型暂无实体</div>';
            return;
        }
        box.innerHTML = '';
        list.forEach(function (e) { box.appendChild(entityItem(e)); });
    }).catch(function () {
        box.innerHTML = '<div class="alert alert-info">加载失败</div>';
    });
};

function entityItem(e) {
    var div = document.createElement('div');
    div.className = 'kg-entity-item';
    var t = KG_TYPE_MAP[e.type] || {};
    var aliases = (e.aliases || []).length > 1 ? (' · ' + (e.aliases || []).join('/')) : '';
    div.innerHTML = '<span style="display:flex;align-items:center;gap:0.4rem;">' +
        '<span style="display:inline-block;width:8px;height:8px;background:' + (t.color || '#6B7280') + ';border-radius:50%;"></span>' +
        escapeHtml(e.name || e.entity_id) + '</span>' +
        '<span style="color:var(--color-text-muted);font-size:0.75rem;">' + escapeHtml(t.label || e.type || '') + escapeHtml(aliases) + '</span>';
    div.addEventListener('click', function () { loadEntityNeighborhood(e.entity_id); });
    return div;
}

window.loadEntityNeighborhood = function (entityId) {
    if (!entityId) return;
    document.getElementById('kg-graph-title').textContent = '加载中...';
    api.get('/kg/entity/' + encodeURIComponent(entityId)).then(function (resp) {
        if (resp && resp.success && resp.data) {
            var d = resp.data;
            var name = (d.entity && d.entity.name) || entityId;
            renderKG(d.graph, name + ' · 邻域图谱', window._kgLayoutMode);
        } else {
            clearGraph();
            document.getElementById('kg-graph-title').textContent = (resp && resp.message) || '暂无邻域数据';
        }
    }).catch(function () {
        document.getElementById('kg-graph-title').textContent = '请求失败';
    });
};

// ===== 布局切换 =====
window._kgLayoutMode = undefined;

window.toggleKGLayout = function () {
    window._kgLayoutMode = window._kgLayoutMode === 'circular' ? undefined : 'circular';
    var btn = document.getElementById('kg-layout-btn');
    if (btn) btn.textContent = window._kgLayoutMode === 'circular' ? '布局：圆形' : '布局：力导向';
    var data = window._kgLastData;
    if (data && window._kgState) {
        var title = document.getElementById('kg-graph-title').textContent;
        renderKG(data, title, window._kgLayoutMode);
    }
};

var _origRenderKG = renderKG;
renderKG = function (data, title, layoutMode) {
    window._kgLastData = data;
    _origRenderKG(data, title, layoutMode);
};
