// ===== 肿瘤知识图谱页面 v3.0（医疗） =====
// 本体（实体类型 / 关系类型 / 配色 / 形状）由后端 /kg/ontology 提供，前端不再硬编码本体。
var KG_ONTOLOGY = { entities: [], relations: [] };
var KG_TYPE_MAP = {};      // entity_type -> { label, color, shape }
var KG_REL_COLORS = {};    // relation_type -> color

// 关系配色：医疗蓝灰系，按关系类型循环取用，保证相邻关系可分辨
var _REL_PALETTE = ['#4A7FA5', '#3F8C8C', '#5B8FB9', '#6E8FA8', '#2F7F76',
                    '#7A9CB8', '#4E7C9B', '#8AA3B8', '#5D7A94'];

// 实体配色：医疗蓝灰明度阶梯（7 档蓝 + 1 个警示橙）。
// 选色依据：CIE L*a*b* + CIEDE2000，并对 Machado 2009 三种色觉缺陷做模拟；
// 因 8 类实体在蓝灰区间内无法仅靠色相区分，类别主要由形状承担（见 KG_SYMBOL_PATHS）。
var KG_COOL_COLORS = {
    Cancer: '#0B2545',           // 癌种：最深藏青，承担视觉重心（对比度 14.7:1）
    Gene: '#1B4A73',             // 基因/标志物（8.8:1）
    Drug: '#2A6590',             // 药物（6.0:1）
    Treatment: '#1F6F7A',        // 治疗方式（5.6:1）
    Stage: '#3D7FA8',            // 分期（4.2:1）
    Symptom: '#2E8FA8',          // 症状（3.6:1）
    Examination: '#5B98BE',      // 检查（3.0:1，WCAG 非文本下限）
    AdverseReaction: '#C2410C'   // 不良反应：唯一警示橙，红绿色盲下仍可与蓝系区分（4.9:1）
};

// 8 类实体各自的形状（ECharts symbol path，viewBox 24×24），保证色觉缺陷下仍可分辨
var KG_SYMBOL_PATHS = {
    Cancer: 'path://M12,2A10,10,0,1,0,12,22A10,10,0,1,0,12,2Z',                 // 圆
    Gene: 'path://M12,1L23,12L12,23L1,12Z',                                     // 菱形
    Drug: 'path://M6,4H18A3,3,0,0,1,21,7V17A3,3,0,0,1,18,20H6A3,3,0,0,1,3,17V7A3,3,0,0,1,6,4Z',  // 圆角矩形
    Treatment: 'path://M12,2L21,7V17L12,22L3,17V7Z',                            // 六边形（与药物圆角矩形拉开差异）
    Stage: 'path://M12,2L22,21L2,21Z',                                          // 三角
    Symptom: 'path://M12,5A11,7,0,1,0,12,19A11,7,0,1,0,12,5Z',                  // 椭圆
    Examination: 'path://M12,2C7.6,2,4,5.6,4,10c0,6,8,12,8,12s8-6,8-12C20,5.6,16.4,2,12,2Z',    // 水滴
    AdverseReaction: 'path://M12,2L22,14H15V22H9V14H2Z'                         // 上箭头
};

function buildOntologyMaps() {
    KG_TYPE_MAP = {};
    (KG_ONTOLOGY.entities || []).forEach(function (e) {
        KG_TYPE_MAP[e.type] = {
            label: e.label,
            color: KG_COOL_COLORS[e.type] || e.color || '#6B7280',
            shape: e.shape || 'ellipse'
        };
    });
    KG_REL_COLORS = {};
    (KG_ONTOLOGY.relations || []).forEach(function (r, i) {
        KG_REL_COLORS[r.type] = _REL_PALETTE[i % _REL_PALETTE.length];
    });
}

function nodeColor(n) {
    // 优先用前端冷色板，其次退回后端返回的实体色
    var t = KG_TYPE_MAP[n.entity_type];
    if (t && t.color) return t.color;
    return n.entity_color || '#6B7280';
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
                <div id="kg-graph-title" class="sub-title"></div>
                <div style="display:flex;gap:0.375rem;">
                    <button class="btn btn-sm" onclick="toggleKGLayout()" id="kg-layout-btn" style="font-size:0.75rem;">布局：力导向</button>
                    <button class="btn btn-sm" onclick="resetKGView()" style="font-size:0.75rem;">重置视图</button>
                    <button class="btn btn-sm" onclick="fitKGView()" style="font-size:0.75rem;">适应布局</button>
                </div>
            </div>
            <div id="kg-canvas-container" style="position:relative;height:500px;background:var(--color-bg);overflow:hidden;cursor:grab;">
                <div id="kg-graph" style="width:100%;height:100%;"></div>
                <div id="kg-tooltip" style="position:absolute;display:none;background:rgba(255,255,255,0.96);border:1px solid var(--color-border);border-radius:6px;padding:0.5rem 0.75rem;font-size:0.75rem;max-width:280px;box-shadow:0 4px 12px rgba(0,0,0,0.08);pointer-events:none;z-index:10;"></div>
            </div>
            <!-- 图例放在画布外，避免遮挡底部节点 -->
            <div id="kg-legend" style="padding:6px 12px;border-top:1px solid var(--color-border);background:var(--color-card-bg);font-size:0.65rem;color:var(--color-text-secondary);line-height:1.7;">
                <div id="kg-legend-types" style="display:flex;flex-wrap:wrap;gap:0.2rem 0.6rem;"></div>
                <div style="display:flex;flex-wrap:wrap;gap:0.2rem 0.6rem;margin-top:1px;">
                    <span style="font-weight:600;min-width:3em;">节点大小：</span>
                    <span><span style="display:inline-block;width:13px;height:13px;background:#6B7280;border-radius:50%;vertical-align:middle;"></span> 高连接</span>
                    <span><span style="display:inline-block;width:9px;height:9px;background:#6B7280;border-radius:50%;vertical-align:middle;"></span> 中连接</span>
                    <span><span style="display:inline-block;width:6px;height:6px;background:#6B7280;border-radius:50%;vertical-align:middle;"></span> 低连接</span>
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
            <div class="sub-title">图谱洞察</div>
            <div id="kg-insight-text" style="font-size:0.8125rem;color:var(--color-text-secondary);line-height:1.7;"></div>
            <div id="kg-type-chart" style="height:110px;margin-top:0.25rem;"></div>
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

// 图例图标：与图中节点形状一致，色觉缺陷用户可据此把颜色映射到类型
function kgShapeIcon(type, color) {
    var path = KG_SYMBOL_PATHS[type];
    if (!path) {
        return '<span style="display:inline-block;width:8px;height:8px;background:' + color + ';border-radius:50%;"></span>';
    }
    return '<svg width="11" height="11" viewBox="0 0 24 24" style="vertical-align:-1px;margin-right:1px;">' +
        '<path d="' + path.replace('path://', '') + '" fill="' + color + '"></path></svg>';
}

function renderLegend() {
    var box = document.getElementById('kg-legend-types');
    if (!box) return;
    var html = '<span style="font-weight:600;min-width:3em;">类型：</span>';
    html += (KG_ONTOLOGY.entities || []).map(function (e) {
        var t = KG_TYPE_MAP[e.type];
        var color = (t && t.color) || e.color;
        return '<span>' + kgShapeIcon(e.type, color) + ' ' + escapeHtml(e.label) + '</span>';
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
    destroyKGGraph();
    destroyKGTypeChart();
    window._kgState = null;
    var ip = document.getElementById('kg-insight-panel');
    if (ip) ip.style.display = 'none';
    var detail = document.getElementById('kg-detail-panel');
    if (detail) { detail.style.display = 'none'; detail.innerHTML = ''; }
    var titleEl = document.getElementById('kg-graph-title');
    if (titleEl) titleEl.textContent = '';
    var badgeEl = document.getElementById('kg-stats-badge');
    if (badgeEl) badgeEl.textContent = '';
    hideKGTooltip();
}

// ===== ECharts 渲染层 =====
// ECharts 产物约 1MB，进入图谱页时才加载，避免拖慢其他页面首屏。
var _kgEchartsPromise = null;

function ensureKGECharts() {
    if (window.echarts && window.echarts.init) return Promise.resolve(window.echarts);
    if (!_kgEchartsPromise) {
        _kgEchartsPromise = new Promise(function (resolve, reject) {
            var s = document.createElement('script');
            s.src = 'vendor/echarts.min.js';
            s.onload = function () {
                (window.echarts && window.echarts.init)
                    ? resolve(window.echarts)
                    : reject(new Error('ECharts 未导出全局变量'));
            };
            s.onerror = function () { reject(new Error('ECharts 资源加载失败')); };
            document.head.appendChild(s);
        });
    }
    return _kgEchartsPromise;
}

function destroyKGGraph() {
    if (window._kgResizeObserver) {
        window._kgResizeObserver.disconnect();
        window._kgResizeObserver = null;
    }
    if (window._kgChart) {
        try { window._kgChart.dispose(); } catch (e) { /* 容器可能已随路由销毁 */ }
        window._kgChart = null;
    }
}

// 前端形状优先（8 类各不相同）；未知实体类型回退到后端本体的 4 种形状
var _KG_SYMBOL_MAP = {
    diamond: 'diamond',
    triangle: 'triangle',
    roundRect: 'roundRect',
    ellipse: 'circle',
    circle: 'circle'
};

function kgNodeSymbol(n) {
    return KG_SYMBOL_PATHS[n.entity_type] || _KG_SYMBOL_MAP[nodeShape(n)] || 'circle';
}

function kgNodeSize(n) {
    var deg = n.degree || 0;
    var base = deg >= 8 ? 26 : (deg >= 3 ? 20 : (deg >= 1 ? 15 : 12));
    return n.is_core ? Math.max(base, 26) : base;
}

function kgShortLabel(n) {
    var label = n.label || n.title || n.id || '';
    return label.length > 12 ? label.substring(0, 12) + '…' : label;
}

// ===== 渲染图谱 =====
function renderKG(data, title, layoutMode) {
    destroyKGGraph();
    destroyKGTypeChart();
    window._kgState = null;

    var nodes = (data.nodes || []).slice();
    var edges = (data.edges || []).slice();
    var ip = document.getElementById('kg-insight-panel');
    if (ip) ip.style.display = 'none';
    var detail = document.getElementById('kg-detail-panel');
    if (detail) { detail.style.display = 'none'; detail.innerHTML = ''; }
    var titleEl = document.getElementById('kg-graph-title');
    var badgeEl = document.getElementById('kg-stats-badge');
    if (badgeEl) badgeEl.textContent = '';
    if (!nodes.length) { if (titleEl) titleEl.textContent = '暂无数据'; return; }

    if (titleEl) titleEl.textContent = title || '知识图谱';
    if (badgeEl) badgeEl.textContent = nodes.length + ' 实体 | ' + edges.length + ' 关系';

    if (!document.getElementById('kg-graph')) return;

    var threshold = parseFloat(document.getElementById('kg-edge-threshold').value) || 0;
    var labelMode = document.getElementById('kg-label-mode').value;

    // 置信度阈值：与旧版一致，仅隐藏低于阈值的边，节点全部保留
    var visibleEdges = edges.filter(function (e) {
        return e.similarity == null || e.similarity >= threshold;
    });

    // 标签策略：smart = 核心实体 + 每类连接度最高的 3 个；其余节点悬停时显示
    var smartKeep = null;
    if (labelMode === 'smart') {
        smartKeep = {};
        var byType = {};
        nodes.forEach(function (n) {
            var t = n.entity_type || '';
            if (!byType[t]) byType[t] = [];
            byType[t].push(n);
        });
        Object.keys(byType).forEach(function (t) {
            byType[t].slice()
                .sort(function (a, b) { return (b.degree || 0) - (a.degree || 0); })
                .slice(0, 3)
                .forEach(function (n) { smartKeep[String(n.id)] = true; });
        });
    }
    function showLabel(n) {
        if (labelMode === 'none') return false;
        if (labelMode === 'all') return true;
        if (labelMode === 'core') return !!n.is_core;
        return !!n.is_core || !!(smartKeep && smartKeep[String(n.id)]);
    }

    var nodeMap = {};
    var edgeMap = {};
    var catIndex = {};
    var categories = [];
    (KG_ONTOLOGY.entities || []).forEach(function (e) {
        catIndex[e.type] = categories.length;
        var t = KG_TYPE_MAP[e.type];
        categories.push({
            name: e.label || e.type,
            itemStyle: { color: (t && t.color) || e.color || '#6B7280' }
        });
    });

    var graphNodes = nodes.map(function (n) {
        var id = String(n.id);
        nodeMap[id] = n;
        return {
            id: id,
            // ECharts 用 name 关联边，必须唯一，故用 id；显示文字由 label.formatter 提供
            name: id,
            category: catIndex[n.entity_type] != null ? catIndex[n.entity_type] : undefined,
            symbol: kgNodeSymbol(n),
            symbolSize: kgNodeSize(n),
            label: { show: showLabel(n) },
            itemStyle: n.is_core
                ? { borderColor: '#2B6CB0', borderWidth: 2.5, shadowBlur: 12, shadowColor: 'rgba(43,108,176,0.38)' }
                : { borderColor: 'rgba(226,232,240,0.95)', borderWidth: 1.4, shadowBlur: 6, shadowColor: 'rgba(15,23,42,0.12)' }
        };
    });

    var graphLinks = visibleEdges.map(function (e, i) {
        var id = 'e' + i;
        edgeMap[id] = e;
        return {
            id: id,
            source: String(e.from),
            target: String(e.to),
            lineStyle: { color: edgeColor(e), curveness: 0.12, width: 1.2, opacity: 0.45 }
        };
    });

    var option = {
        backgroundColor: 'transparent',
        animationDuration: 500,
        animationDurationUpdate: 300,
        tooltip: {
            trigger: 'item',
            confine: true,
            backgroundColor: 'rgba(255,255,255,0.97)',
            borderColor: '#E5E7EB',
            borderWidth: 1,
            padding: [8, 10],
            textStyle: { color: '#1E293B', fontSize: 12 },
            extraCssText: 'box-shadow:0 6px 18px rgba(15,23,42,0.10);border-radius:8px;',
            formatter: function (p) {
                if (p.dataType === 'edge') {
                    var e = edgeMap[p.data.id] || {};
                    var from = nodeMap[String(e.from)];
                    var to = nodeMap[String(e.to)];
                    return '<div style="font-weight:600;margin-bottom:2px;">' +
                        escapeHtml(e.relation_label || e.label || e.relation_type || '关联') + '</div>' +
                        '<div style="font-size:12px;color:#374151;">' +
                        escapeHtml(from ? (from.label || e.from) : e.from) + ' → ' +
                        escapeHtml(to ? (to.label || e.to) : e.to) + '</div>' +
                        '<div style="font-size:11px;color:#9CA3AF;">置信度 ' +
                        (e.similarity != null ? e.similarity.toFixed(2) : '-') +
                        (e.source_ref ? ' · ' + escapeHtml(e.source_ref) : '') + '</div>';
                }
                var n = nodeMap[String(p.data.id)] || {};
                return '<div style="font-weight:600;margin-bottom:2px;">' + escapeHtml(n.label || n.id) + '</div>' +
                    '<div style="font-size:12px;color:#374151;">' + escapeHtml(typeLabel(n)) + ' · 连接 ' + (n.degree || 0) + '</div>' +
                    '<div style="font-size:11px;color:#9CA3AF;">点击查看邻域</div>';
            }
        },
        series: [{
            type: 'graph',
            layout: layoutMode === 'circular' ? 'circular' : 'force',
            data: graphNodes,
            links: graphLinks,
            categories: categories,
            roam: true,
            draggable: true,
            nodeScaleRatio: 0.35,
            top: 30,
            left: 20,
            right: 20,
            bottom: 30,
            force: {
                repulsion: nodes.length > 60 ? 620 : 330,
                edgeLength: [55, 110],
                gravity: 0.18,
                friction: 0.2,
                layoutAnimation: true
            },
            circular: { rotateLabel: false },
            label: {
                show: true,
                position: 'bottom',
                distance: 4,
                fontSize: 11,
                color: '#1E293B',
                backgroundColor: 'rgba(248,250,252,0.86)',
                padding: [2, 4],
                borderRadius: 3,
                formatter: function (p) {
                    var n = nodeMap[String(p.data.id)];
                    return n ? kgShortLabel(n) : '';
                }
            },
            labelLayout: { hideOverlap: true },
            edgeSymbol: ['none', 'arrow'],
            edgeSymbolSize: 5,
            emphasis: {
                focus: 'adjacency',
                scale: 1.15,
                label: { show: true, fontWeight: 600 },
                itemStyle: { borderColor: '#2B6CB0', borderWidth: 2 },
                lineStyle: { width: 2.4, opacity: 0.95 }
            },
            blur: {
                itemStyle: { opacity: 0.18 },
                label: { opacity: 0.12 },
                lineStyle: { opacity: 0.05 }
            }
        }]
    };

    ensureKGECharts().then(function (echarts) {
        var host = document.getElementById('kg-graph');
        if (!host) return null;   // 已切走页面
        var chart = echarts.init(host, null, { renderer: 'canvas' });
        window._kgChart = chart;
        window._kgState = { nodes: nodes, edges: visibleEdges, raw: data };
        chart.setOption(option);

        chart.on('click', function (p) {
            if (p.dataType === 'node') {
                var node = nodeMap[String(p.data.id)];
                if (node) showKGDetail(node);
            } else if (p.dataType === 'edge') {
                var edge = edgeMap[p.data.id];
                if (edge) showKGEdgeDetail(edge, window._kgState);
            }
        });
        // 点击空白处收起详情面板
        chart.getZr().on('click', function (evt) {
            if (evt.target) return;
            var panel = document.getElementById('kg-detail-panel');
            if (panel) panel.style.display = 'none';
        });

        bindKGGraphControls();
        generateKGInsight(data);

        if (window.ResizeObserver) {
            if (window._kgResizeObserver) window._kgResizeObserver.disconnect();
            window._kgResizeObserver = new ResizeObserver(function () {
                if (window._kgChart) window._kgChart.resize();
            });
            window._kgResizeObserver.observe(host);
        }
        return chart;
    }).catch(function (e) {
        if (titleEl) titleEl.textContent = '图谱渲染失败：' + ((e && e.message) || '未知错误');
    });
}

// 阈值/标签变化的绑定（每次重建图表实例时重新注册）
function bindKGGraphControls() {
    var threshold = document.getElementById('kg-edge-threshold');
    var labelSel = document.getElementById('kg-label-mode');
    var rerender = function () {
        var last = window._kgLastData;
        if (!last) return;
        var titleEl = document.getElementById('kg-graph-title');
        renderKG(last, titleEl ? titleEl.textContent : '', window._kgLayoutMode);
    };
    var timer = null;
    var debounced = function () {
        if (timer) clearTimeout(timer);
        timer = setTimeout(rerender, 250);
    };

    if (threshold) {
        threshold.oninput = function () {
            document.getElementById('kg-threshold-val').textContent = parseFloat(threshold.value).toFixed(2);
            debounced();
        };
    }
    if (labelSel) labelSel.onchange = rerender;
}

// ===== 详情面板 =====
function showKGDetail(node) {
    var panel = document.getElementById('kg-detail-panel');
    var html = '<div class="card" style="padding:0.75rem 1rem;">';
    html += '<div style="margin-bottom:0.5rem;">';
    html += '<span class="badge" style="background:' + nodeColor(node) + ';color:#fff;">' + escapeHtml(typeLabel(node)) + '</span>';
    if (node.is_core) html += '<span class="badge badge-warning" style="margin-left:0.375rem;">核心</span>';
    html += '</div>';
    html += '<h3 class="item-title">' + escapeHtml(node.label || node.id) + '</h3>';
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
    html += '<h3 class="item-title" style="margin-bottom:0.75rem;">' + escapeHtml(edge.relation_label || edge.label || '关联') + '</h3>';
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

// ===== 视图控制 =====
// ECharts 的 graph 系列没有 fitView API：布局只在 setOption 时按容器自适应一次，
// 用户漫游/拖拽后无法单独重置视口，因此统一用“重建图表”恢复初始布局与缩放。
window.resetKGView = function () {
    var last = window._kgLastData;
    if (!last || !window._kgChart) return;
    var titleEl = document.getElementById('kg-graph-title');
    renderKG(last, titleEl ? titleEl.textContent : '', window._kgLayoutMode);
};

window.fitKGView = function () {
    var last = window._kgLastData;
    if (!last || !window._kgChart) return;
    window._kgChart.resize();   // 容器尺寸变化时先同步画布，再重排
    var titleEl = document.getElementById('kg-graph-title');
    renderKG(last, titleEl ? titleEl.textContent : '', window._kgLayoutMode);
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
    renderKGTypeChart(nodes);
}

// ===== 实体类型分布图（G2） =====
var _kgG2Promise = null;
var _kgTypeChart = null;

function ensureKGG2() {
    if (window.G2) return Promise.resolve(window.G2);
    if (!_kgG2Promise) {
        _kgG2Promise = new Promise(function (resolve, reject) {
            var s = document.createElement('script');
            s.src = 'vendor/g2.min.js';
            s.onload = function () {
                window.G2 ? resolve(window.G2) : reject(new Error('G2 未导出全局变量'));
            };
            s.onerror = function () { reject(new Error('G2 资源加载失败')); };
            document.head.appendChild(s);
        });
    }
    return _kgG2Promise;
}

function destroyKGTypeChart() {
    if (_kgTypeChart) {
        try { _kgTypeChart.destroy(); } catch (e) { /* 容器可能已销毁 */ }
        _kgTypeChart = null;
    }
}

function renderKGTypeChart(nodes) {
    if (!nodes || !nodes.length) return;
    var counts = {};
    nodes.forEach(function (n) {
        var t = typeLabel(n);
        counts[t] = (counts[t] || 0) + 1;
    });
    var rows = Object.keys(counts)
        .map(function (t) { return { type: t, count: counts[t] }; })
        .sort(function (a, b) { return b.count - a.count; });
    var colors = rows.map(function (r) {
        var hit = null;
        Object.keys(KG_TYPE_MAP).forEach(function (k) {
            if (KG_TYPE_MAP[k].label === r.type) hit = KG_TYPE_MAP[k].color;
        });
        return hit || '#6B7280';
    });

    ensureKGG2().then(function (G2) {
        if (!document.getElementById('kg-type-chart')) return;
        destroyKGTypeChart();
        _kgTypeChart = new G2.Chart({ container: 'kg-type-chart', autoFit: true, padding: [4, 8, 22, 26] });
        _kgTypeChart.options({
            type: 'interval',
            data: rows,
            encode: { x: 'type', y: 'count', color: 'type' },
            scale: { color: { range: colors } },
            legend: false,
            style: { radiusTopLeft: 2, radiusTopRight: 2, maxWidth: 28 },
            axis: {
                x: { title: false, labelFontSize: 9, tick: false, line: false, labelAutoHide: true },
                y: { title: false, labelFontSize: 9, tick: false, grid: false }
            }
        });
        _kgTypeChart.render();
    }).catch(function () { /* 图表失败不影响图谱本体 */ });
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
            box.innerHTML = emptyState('未找到相关实体，请尝试其他关键词');
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
            box.innerHTML = emptyState('该类型暂无实体');
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

    var last = window._kgLastData;
    if (!last) return;
    var titleEl = document.getElementById('kg-graph-title');
    renderKG(last, titleEl ? titleEl.textContent : '', window._kgLayoutMode);
};

// 缓存最近一次渲染数据，供阈值/标签/布局切换复用
var _kgRenderKGBase = renderKG;
renderKG = function (data, title, layoutMode) {
    window._kgLastData = data;
    return _kgRenderKGBase(data, title, layoutMode);
};

// 路由切走时释放图表实例，避免 canvas 与力导向计算常驻
window.addEventListener('hashchange', function () {
    setTimeout(function () {
        if (!document.getElementById('kg-graph')) destroyKGGraph();
    }, 0);
});