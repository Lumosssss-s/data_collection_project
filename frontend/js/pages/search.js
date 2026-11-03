/**
 * 循证检索页面（医疗）
 *
 * 两模式：
 *   - 无关键词：浏览指南文档列表（/search/docs，DocCatalog 驱动）
 *   - 有关键词：循证语义检索（/search），返回推荐条目及证据等级 / 推荐强度 / 溯源
 */
// 受控词表代码 → 中文标签（供结果卡片展示，避免出现原始代码）
// 先给全量静态映射，避免筛选下拉尚未加载完时文档卡上露出 lung / colorectal 这类代码
const CANCER_LABELS = {
    lung: '肺癌',
    colorectal: '结直肠癌',
    breast: '乳腺癌',
    gastric: '胃癌',
    thyroid: '甲状腺癌'
};
const SCENARIO_LABELS = {};

// 癌种分类色只分配给肺 / 结直肠 / 乳腺三种；其余癌种回落中性 chip（不新造颜色）
const CANCER_COLORED = ['lung', 'colorectal', 'breast'];
function cancerChip(code) {
    const key = String(code || '');
    const cls = CANCER_COLORED.indexOf(key) >= 0 ? key : 'other';
    return '<span class="cancer-chip" data-cancer="' + cls + '">'
        + escapeHtml(CANCER_LABELS[key] || key) + '</span>';
}

// 数据类型标签：仅"指南"使用数据类型色，规范/共识保持中性
function docTypeTag(t) {
    if (!t) return '';
    if (t === 'guideline') return '<span class="dtype-tag" data-dtype="guideline">指南</span>';
    return '<span class="badge badge-muted">' + escapeHtml(docTypeLabel(t)) + '</span>';
}

registerPage('search', function (container) {
    container.innerHTML = `
        <h1 class="page-title">证据检索</h1>
        <p class="page-desc">输入临床问题或关键词，返回肿瘤循证推荐条目（含证据等级、推荐强度与出处溯源）</p>

        <!-- 搜索主导航区 -->
        <section class="search-hero">
            <div class="search-hero-row">
                <input type="text" id="search-query" class="input search-hero-input" placeholder="输入临床问题，例如：EGFR 突变 一线 靶向治疗">
                <button id="search-btn" class="btn btn-primary search-hero-btn">检索</button>
            </div>
            <p class="search-hero-hint">不输入关键词时，按癌种 / 文档类型 / 主题浏览指南文档</p>
            <div class="search-chips">
                <button class="search-chip" data-q="HER2 阳性乳腺癌一线治疗推荐">HER2 阳性乳腺癌一线治疗推荐</button>
                <button class="search-chip" data-q="结肠癌辅助化疗推荐">结肠癌辅助化疗推荐</button>
                <button class="search-chip" data-q="非小细胞肺癌免疫治疗一线推荐">非小细胞肺癌免疫治疗一线推荐</button>
            </div>
        </section>

        <!-- 横向筛选条：紧接在搜索区下方，与结果工具条同属一条连续结构（只用细线分隔，不做两张卡） -->
        <div class="search-filterbar">
            <div class="sf-item">
                <label for="search-cancer-type">癌种</label>
                <select id="search-cancer-type" class="select sf-select">
                    <option value="">全部癌种</option>
                </select>
            </div>
            <div class="sf-item">
                <label for="search-doc-type">类型</label>
                <select id="search-doc-type" class="select sf-select">
                    <option value="">全部类型</option>
                    <option value="guideline">指南</option>
                    <option value="standard">规范</option>
                    <option value="consensus">共识</option>
                </select>
            </div>
            <div class="sf-item">
                <label for="search-scenario">场景</label>
                <select id="search-scenario" class="select sf-select">
                    <option value="">全部场景</option>
                </select>
            </div>
            <div class="sf-item sf-item-topic">
                <label>主题</label>
                <div id="search-topic-trigger" class="search-topic-trigger">
                    <span id="search-topic-label">全部主题</span>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
                </div>
                <div id="search-topic-dropdown" class="search-topic-dropdown" style="display:none;"></div>
                <select id="search-topic" multiple style="display:none;"></select>
            </div>
            <button type="button" id="sf-reset" class="sf-reset">重置</button>
        </div>

        <!-- 结果流（单列，无左栏） -->
        <div class="search-layout">
            <section class="results-panel">
                <div id="search-results"></div>
            </section>
        </div>
    `;

    // 场景受控词表（§5.7.3，value = scenario 代码）
    const SCENARIOS = [
        { code: 'screening', label: '筛查' },
        { code: 'diagnosis', label: '诊断' },
        { code: 'staging', label: '分期' },
        { code: 'treatment_neoadjuvant', label: '新辅助治疗' },
        { code: 'treatment_adjuvant', label: '辅助治疗' },
        { code: 'treatment_first_line', label: '一线治疗' },
        { code: 'treatment_second_line', label: '二线治疗' },
        { code: 'treatment_later', label: '后线治疗' },
        { code: 'surgery', label: '手术' },
        { code: 'radiotherapy', label: '放疗' },
        { code: 'targeted', label: '靶向治疗' },
        { code: 'immunotherapy', label: '免疫治疗' },
        { code: 'followup', label: '随访' },
        { code: 'supportive_care', label: '支持治疗' },
        { code: 'rehab', label: '康复' },
    ];
    const scenarioSel = document.getElementById('search-scenario');
    SCENARIOS.forEach(function (s) {
        const opt = document.createElement('option');
        opt.value = s.code;
        opt.textContent = s.label;
        scenarioSel.appendChild(opt);
        SCENARIO_LABELS[s.code] = s.label;
    });

    // 加载癌种与主题选项
    Promise.all([
        api.get('/search/cancer_types'),
        api.get('/search/topics')
    ]).then(function (results) {
        const cancerData = results[0];
        const topicData = results[1];

        // 癌种（受控词表）
        const cancerSel = document.getElementById('search-cancer-type');
        if (cancerData && cancerData.data) {
            cancerData.data.forEach(function (c) {
                const opt = document.createElement('option');
                opt.value = c.code;
                opt.textContent = c.label_zh || c.code;
                cancerSel.appendChild(opt);
                CANCER_LABELS[c.code] = c.label_zh || c.code;
            });
        }

        // 主题（多选，自定义下拉）
        const topicSelect = document.getElementById('search-topic');
        const topicDropdown = document.getElementById('search-topic-dropdown');
        const topicTrigger = document.getElementById('search-topic-trigger');
        const topicLabel = document.getElementById('search-topic-label');

        function updateTopicLabel() {
            const selected = Array.from(topicSelect.selectedOptions).map(function (o) { return o.value; });
            if (selected.length === 0) topicLabel.textContent = '全部主题';
            else if (selected.length === 1) topicLabel.textContent = selected[0];
            else topicLabel.textContent = '已选 ' + selected.length + ' 个主题';
        }

        function toggleTopicDropdown(show) {
            topicDropdown.style.display = show ? 'block' : 'none';
            topicTrigger.classList.toggle('active', show);
        }

        if (topicData && topicData.data) {
            topicData.data.forEach(function (t) {
                const value = t.label_zh || t.topic || '';
                if (!value) return;

                const opt = document.createElement('option');
                opt.value = value;
                opt.textContent = value + ' (' + (t.count || 0) + ')';
                topicSelect.appendChild(opt);

                const item = document.createElement('div');
                item.className = 'search-topic-item';
                item.dataset.value = value;
                item.innerHTML = '<span class="search-topic-check"></span><span>' + escapeHtml(value) + ' <span style="color:var(--color-text-muted);font-size:0.75rem;">(' + (t.count || 0) + ')</span></span>';
                item.addEventListener('click', function (e) {
                    e.stopPropagation();
                    const optToToggle = Array.from(topicSelect.options).find(function (o) { return o.value === value; });
                    if (optToToggle) {
                        optToToggle.selected = !optToToggle.selected;
                        item.classList.toggle('selected', optToToggle.selected);
                        updateTopicLabel();
                    }
                });
                topicDropdown.appendChild(item);
            });
        }

        topicTrigger.addEventListener('click', function (e) {
            e.stopPropagation();
            toggleTopicDropdown(topicDropdown.style.display === 'none');
        });
        document.addEventListener('click', function () { toggleTopicDropdown(false); });
        topicDropdown.addEventListener('click', function (e) { e.stopPropagation(); });

        updateTopicLabel();
        restoreSearchState();
        ensureInitialResults();
    }).catch(function () { ensureInitialResults(); });

    // 首屏自动加载：本页每次挂载只跑一次；若 restoreSearchState 已触发检索（容器里已有内容）则不重复请求
    let initialLoadDone = false;
    function ensureInitialResults() {
        if (initialLoadDone) return;
        initialLoadDone = true;
        const box = document.getElementById('search-results');
        if (box && box.children.length) return;
        doSearch();
    }

    document.getElementById('search-btn').addEventListener('click', doSearch);
    document.getElementById('search-query').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') doSearch();
    });

    // 横向筛选条的「重置」：清空四个筛选控件后按当前关键词重跑
    document.getElementById('sf-reset').addEventListener('click', function () {
        document.getElementById('search-cancer-type').value = '';
        document.getElementById('search-doc-type').value = '';
        document.getElementById('search-scenario').value = '';
        const topicSel = document.getElementById('search-topic');
        Array.from(topicSel.options).forEach(function (o) { o.selected = false; });
        Array.from(document.querySelectorAll('.search-topic-item')).forEach(function (it) {
            it.classList.remove('selected');
        });
        document.getElementById('search-topic-label').textContent = '全部主题';
        doSearch();
    });
    Array.from(document.querySelectorAll('.search-chip')).forEach(function (chip) {
        chip.addEventListener('click', function () {
            document.getElementById('search-query').value = chip.getAttribute('data-q') || '';
            doSearch();
        });
    });
});

function currentFilters() {
    return {
        query: document.getElementById('search-query').value.trim(),
        cancerType: document.getElementById('search-cancer-type').value,
        docType: document.getElementById('search-doc-type').value,
        scenario: document.getElementById('search-scenario').value,
        topics: Array.from(document.getElementById('search-topic').selectedOptions).map(function (o) { return o.value; })
    };
}

// 已生效筛选项数量（读现有控件状态，不新增接口）
function activeFilterCount() {
    const f = currentFilters();
    let n = 0;
    if (f.cancerType) n += 1;
    if (f.docType) n += 1;
    if (f.scenario) n += 1;
    if (f.topics.length) n += f.topics.length;
    return n;
}

function filterBadge() {
    const n = activeFilterCount();
    return n > 0 ? '<span class="results-filter">· 已筛 ' + n + ' 项</span>' : '';
}

// 低相关阈值：实测无关查询 top1 最高 0.4477、相关查询 top1 最低 0.5168，取区间中点 0.48
const LOW_REL_THRESHOLD = 0.48;

// 结果相关性偏低时给出换词建议（不等于“没有结果”，措辞不得写成未找到）
// 部分条目（如 PDF 入库的 NHC 记录）match_score 为 null —— 评测集里只有评分有效时才有意义，
// 若整页都没有有效评分，则不提示，避免把“评分缺失”误报成“相关性低”。
function lowRelevanceBar(results) {
    const scores = results
        .map(function (r) { return r.match_score; })
        .filter(function (v) { return v !== null && v !== undefined && v !== ''; })
        .map(Number)
        .filter(function (v) { return Number.isFinite(v); });
    if (!scores.length) return '';
    // 口径与标定一致：取排序后的首个有效评分（等价 top1），不用全页最大值——
    // 全页最大值在 top_k=50 下无关查询可达 0.5498，会越过 0.48 造成漏报。
    const top1 = scores[0];
    if (top1 >= LOW_REL_THRESHOLD) return '';
    return '<div class="results-lowrel">当前结果相关性较低，建议换用更具体的关键词</div>';
}

function doSearch() {
    const f = currentFilters();
    const resultsEl = document.getElementById('search-results');
    showLoading(resultsEl);

    if (!f.query) {
        // 浏览模式：指南文档列表
        const params = {};
        if (f.cancerType) params.cancer_type = f.cancerType;
        if (f.docType) params.doc_type = f.docType;

        api.get('/search/docs', params).then(function (data) {
            const docs = (data && data.data) || [];
            renderDocList(resultsEl, docs, data && data.message, filterBadge());
        }).catch(function (err) {
            showError(resultsEl, '加载指南列表失败: ' + err.message);
        });
    } else {
        // 循证检索模式
        const params = { query: f.query, top_k: 50 };
        if (f.cancerType) params.cancer_type = f.cancerType;
        if (f.docType) params.doc_type = f.docType;
        if (f.scenario) params.scenario = f.scenario;
        if (f.topics.length > 0) params.topic = f.topics.join(',');

        api.get('/search', params).then(function (data) {
            const results = (data && data.data) || [];
            renderSearchResults(resultsEl, results, f.query, data && data.message);
        }).catch(function (err) {
            showError(resultsEl, '检索失败: ' + err.message);
        });
    }
}

// ===== 指南文档列表 =====
// badgeHtml 由调用方提供：检索页传 filterBadge()（读检索页控件），
// 指南页传自己的 guidesFilterBadge()（读指南页控件）。renderDocList 不再直接读任何页面 DOM。
function renderDocList(container, docs, message, badgeHtml) {
    if (!docs.length) {
        container.innerHTML = emptyState(message || '未找到相关指南文档');
        return;
    }
    let html = '<div class="results-toolbar">'
        + '<div class="results-count"><strong>' + docs.length + '</strong>篇指南文档' + (badgeHtml || '') + '</div>'
        + '<div class="results-note">按癌种与文档类型浏览</div>'
        + '</div>';
    html += '<div class="doc-grid">';
    docs.forEach(function (d) {
        const cancerTags = (d.cancer_types || []).map(cancerChip).join('');
        html += '<div class="doc-card" onclick="viewGuideDetail(\'' + escapeHtml(d.doc_id || '') + '\')">';
        html += '<div class="doc-card-title">' + escapeHtml(d.title || d.doc_id || '') + '</div>';
        html += '<div class="doc-card-meta">'
              + escapeHtml(d.issuer || '')
              + (d.publish_date ? ' · ' + escapeHtml(d.publish_date) : '') + '</div>';
        html += '<div class="doc-card-foot"><div>' + docTypeTag(d.doc_type) + cancerTags + '</div>'
              + '<span class="doc-card-count">' + (d.item_count || 0) + ' 条推荐</span></div>';
        html += '</div>';
    });
    html += '</div>';
    container.innerHTML = html;
}

// 指南浏览页（复用 /search/docs 网格，不新开页面）
// 自带癌种 / 类型筛选：与检索浏览模式同参数、零 LLM；
// 筛选状态存 _guidesFilter，只读指南页自己的控件，不读检索页 DOM。
let _guidesFilter = { cancerType: '', docType: '' };

function guidesFilterBadge() {
    let n = 0;
    if (_guidesFilter.cancerType) n += 1;
    if (_guidesFilter.docType) n += 1;
    return n > 0 ? '<span class="results-filter">· 已筛 ' + n + ' 项</span>' : '';
}

function renderGuidesPage(container) {
    container.innerHTML = ''
        + '<h1 class="page-title">指南</h1>'
        + '<p class="page-desc">浏览已入库的指南与规范文档；点击卡片进入速览（概要 / 章节导航 / 全文）。</p>'
        + '<div class="card" style="padding:0.75rem 1rem;margin:0.75rem 0 1rem;">'
        + '<div style="display:flex;gap:0.75rem;flex-wrap:wrap;align-items:center;">'
        + '<label style="font-size:0.8125rem;color:var(--color-text-secondary);">癌种 '
        + '<select id="guides-cancer" class="select" style="width:auto;"><option value="">全部癌种</option></select></label>'
        + '<label style="font-size:0.8125rem;color:var(--color-text-secondary);">类型 '
        + '<select id="guides-doctype" class="select" style="width:auto;"><option value="">全部类型</option>'
        + '<option value="guideline">指南</option><option value="standard">规范</option><option value="consensus">共识</option></select></label>'
        + '<button id="guides-reset" class="btn btn-ghost btn-sm">重置</button>'
        + '</div></div>'
        + '<div id="guides-docs"></div>';

    const cancerSel = document.getElementById('guides-cancer');
    const typeSel = document.getElementById('guides-doctype');
    api.get('/search/cancer_types').then(function (data) {
        ((data && data.data) || []).forEach(function (c) {
            const opt = document.createElement('option');
            opt.value = c.code;
            opt.textContent = c.label_zh || c.code;
            cancerSel.appendChild(opt);
        });
    }).catch(function () { /* 癌种表不可用时保留「全部癌种」一项 */ });
    cancerSel.addEventListener('change', loadGuidesDocs);
    typeSel.addEventListener('change', loadGuidesDocs);
    document.getElementById('guides-reset').addEventListener('click', function () {
        cancerSel.value = '';
        typeSel.value = '';
        loadGuidesDocs();
    });
    loadGuidesDocs();
}

function loadGuidesDocs() {
    _guidesFilter.cancerType = document.getElementById('guides-cancer').value;
    _guidesFilter.docType = document.getElementById('guides-doctype').value;
    const box = document.getElementById('guides-docs');
    showLoading(box);
    const params = {};
    if (_guidesFilter.cancerType) params.cancer_type = _guidesFilter.cancerType;
    if (_guidesFilter.docType) params.doc_type = _guidesFilter.docType;
    api.get('/search/docs', params).then(function (data) {
        renderDocList(box, (data && data.data) || [], data && data.message, guidesFilterBadge());
    }).catch(function (err) {
        showError(box, '加载指南列表失败: ' + err.message);
    });
}

// 证据等级只接受 A–D 首字母，其余值原样展示，不做推测
function normalizeEvidenceGrade(value) {
    const m = String(value || '').trim().match(/^[A-Da-d]/);
    return m ? m[0].toUpperCase() : '';
}

// HTML 属性值转义（escapeHtml 不处理引号）
function escapeAttr(value) {
    return escapeHtml(String(value == null ? '' : value))
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// 推荐强度仅区分强/弱，其余归为中性
function recommendationClass(value) {
    const s = String(value || '');
    if (/强|strong/i.test(s)) return 'rec-strong';
    if (/弱|weak/i.test(s)) return 'rec-weak';
    return 'rec-neutral';
}

// ===== 推荐条目检索结果 =====
function renderSearchResults(container, results, query, message) {
    if (!results.length) {
        container.innerHTML = emptyState(message || '未找到相关推荐条目');
        return;
    }
    let html = '<div class="results-toolbar">'
        + '<div class="results-count"><strong>' + results.length + '</strong>条相关推荐条目' + filterBadge() + '</div>'
        + '<div class="results-note">按语义相关度排序</div>'
        + '</div>';
    html += lowRelevanceBar(results);
    html += '<div class="result-list">';
    results.forEach(function (r) {
        const meta = r.metadata || {};
        html += '<article class="result-item">';

        // 标题行：数据类型标签 + 证据等级 / 推荐强度
        html += '<div class="result-item-head">';
        html += '<h3 class="result-title">' + escapeHtml(meta.title || meta.item_id || '') + '</h3>';
        html += '<div class="result-badges">';
        html += '<span class="dtype-tag" data-dtype="rec">推荐</span>';
        if (meta.evidence_level) {
            const grade = normalizeEvidenceGrade(meta.evidence_level);
            const rawLevel = escapeHtml(String(meta.evidence_level));
            if (grade) {
                html += '<span class="evidence-grade" data-grade="' + grade + '" title="证据等级：' + escapeAttr(meta.evidence_level) + '">'
                      + '<span class="grade-letter">' + grade + '</span><span class="grade-label">级证据</span></span>';
            } else {
                html += '<span class="badge badge-muted" title="证据等级">证据 ' + rawLevel + '</span>';
            }
        }
        if (meta.rec_strength) {
            html += '<span class="rec-strength ' + recommendationClass(meta.rec_strength) + '" title="推荐强度">'
                  + escapeHtml(String(meta.rec_strength)) + '</span>';
        }
        html += '</div></div>';

        // 溯源行：来源 chip + 癌种 + 场景
        const metaParts = [];
        if (meta.breadcrumb) {
            metaParts.push('<span class="source-chip" title="' + escapeAttr(meta.breadcrumb) + '">'
                + '<span class="chip-doc">' + escapeHtml(meta.breadcrumb) + '</span></span>');
        }
        if (meta.cancer_type) {
            metaParts.push(cancerChip(meta.cancer_type));
        }
        if (meta.scenario) {
            metaParts.push('<span>场景 ' + escapeHtml(SCENARIO_LABELS[meta.scenario] || meta.scenario) + '</span>');
        }
        if (metaParts.length) {
            html += '<div class="result-meta">' + metaParts.join('<span class="meta-divider">·</span>') + '</div>';
        }

        // 引用链扩展标记
        if (r.retrieval_hop === 2) {
            const ref = r.referenced_doc_name
                ? ('引用自《' + escapeHtml(r.referenced_doc_name) + '》')
                : ('由 ' + escapeHtml(r.referenced_by || '') + ' 引用补入');
            html += '<div class="result-ref">↳ ' + ref + '</div>';
        }

        // 正文（超长内容折叠为 6 行，可展开，避免单条结果撑满屏幕）
        const contentText = r.content || '';
        const needClamp = contentText.length > 320;
        html += '<div class="result-content' + (needClamp ? ' is-clamped' : '') + '">' + escapeHtml(contentText) + '</div>';
        if (needClamp) {
            html += '<button type="button" class="result-toggle" aria-expanded="false" onclick="toggleResultContent(this)">展开全文</button>';
        }

        // 底栏：匹配度
        if (r.match_score !== null && r.match_score !== undefined) {
            html += '<div class="result-foot">'
                  + '<span class="match-score">匹配度 ' + (r.match_score * 100).toFixed(0) + '%</span>'
                  + '</div>';
        }

        html += '</article>';
    });
    html += '</div>';
    container.innerHTML = html;
}

function docTypeLabel(t) {
    const map = { guideline: '指南', standard: '规范', consensus: '共识' };
    return map[t] || t;
}

// 结果正文展开 / 收起
window.toggleResultContent = function (btn) {
    const content = btn.previousElementSibling;
    if (!content) return;
    const clamped = content.classList.toggle('is-clamped');
    btn.textContent = clamped ? '展开全文' : '收起';
    btn.setAttribute('aria-expanded', String(!clamped));
};

// ===== 指南详情跳转 =====
window.viewGuideDetail = function (docId) {
    if (!docId) return;
    saveSearchState();
    window.location.hash = '#/guideline/' + docId;
};

// ===== 搜索状态保存 / 恢复（只存条件，返回时重新检索）=====
function saveSearchState() {
    // 检索状态只属于检索页：指南页等没有检索控件，既不存也不读，避免跨页 null 引用
    if (getCurrentPage() !== 'search') return;
    const f = currentFilters();
    try { sessionStorage.setItem('search_state', JSON.stringify(f)); } catch (e) { /* ignore */ }
}

function restoreSearchState() {
    // URL 直达：?q=xxx 预填关键词（用于分享/回归验证），优先级高于会话缓存
    let urlQ = '';
    try { urlQ = new URLSearchParams(window.location.search).get('q') || ''; } catch (e) { urlQ = ''; }
    if (urlQ) {
        const qEl = document.getElementById('search-query');
        if (qEl) qEl.value = urlQ;
        return;
    }

    let raw;
    try { raw = sessionStorage.getItem('search_state'); } catch (e) { /* ignore */ }
    if (!raw) return;

    let state;
    try { state = JSON.parse(raw); } catch (e) { /* ignore */ }
    try { sessionStorage.removeItem('search_state'); } catch (e) { /* ignore */ }
    if (!state) return;

    const q = document.getElementById('search-query');
    const cancer = document.getElementById('search-cancer-type');
    const docType = document.getElementById('search-doc-type');
    const scenario = document.getElementById('search-scenario');
    const topicSelect = document.getElementById('search-topic');
    if (q) q.value = state.query || '';
    if (cancer) cancer.value = state.cancerType || '';
    if (docType) docType.value = state.docType || '';
    if (scenario) scenario.value = state.scenario || '';
    if (topicSelect && state.topics) {
        Array.from(topicSelect.options).forEach(function (o) {
            o.selected = state.topics.indexOf(o.value) !== -1;
        });
    }

    // 有任一条件即自动重跑检索，避免返回后出现空列表
    const hasFilter = state.query || state.cancerType || state.docType || state.scenario
        || (state.topics && state.topics.length);
    if (hasFilter) doSearch();
}
