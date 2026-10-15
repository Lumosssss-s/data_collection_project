/**
 * 循证检索页面（医疗）
 *
 * 两模式：
 *   - 无关键词：浏览指南文档列表（/search/docs，DocCatalog 驱动）
 *   - 有关键词：循证语义检索（/search），返回推荐条目及证据等级 / 推荐强度 / 溯源
 */
registerPage('search', function (container) {
    container.innerHTML = `
        <h1 class="page-title">循证检索</h1>
        <p class="page-desc">输入临床问题或关键词，返回肿瘤循证推荐条目（含证据等级、推荐强度与出处溯源）</p>
        <div class="alert alert-info">提示：不输入关键词时，可直接按癌种 / 文档类型 / 主题浏览指南文档</div>

        <!-- 搜索栏 -->
        <div class="search-filter-bar">
            <input type="text" id="search-query" class="input search-filter-input" placeholder="例如：EGFR 突变 一线 靶向治疗">
            <div class="search-filter-item">
                <label>癌种</label>
                <select id="search-cancer-type" class="select search-filter-select">
                    <option value="">全部癌种</option>
                </select>
            </div>
            <div class="search-filter-item">
                <label>文档类型</label>
                <select id="search-doc-type" class="select search-filter-select">
                    <option value="">全部类型</option>
                    <option value="guideline">指南</option>
                    <option value="standard">规范</option>
                    <option value="consensus">共识</option>
                </select>
            </div>
            <div class="search-filter-item">
                <label>场景</label>
                <select id="search-scenario" class="select search-filter-select">
                    <option value="">全部场景</option>
                </select>
            </div>
            <div class="search-filter-item search-topic-wrapper">
                <label>主题</label>
                <div id="search-topic-trigger" class="search-topic-trigger">
                    <span id="search-topic-label">全部主题</span>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
                </div>
                <div id="search-topic-dropdown" class="search-topic-dropdown" style="display:none;"></div>
                <select id="search-topic" class="select search-filter-select" multiple style="display:none;"></select>
            </div>
            <button id="search-btn" class="btn btn-primary search-filter-btn">检索</button>
        </div>

        <!-- 结果区 -->
        <div id="search-results"></div>
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
    }).catch(function () { /* 选项加载失败不阻断检索 */ });

    document.getElementById('search-btn').addEventListener('click', doSearch);
    document.getElementById('search-query').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') doSearch();
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
            renderDocList(resultsEl, docs);
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
            renderSearchResults(resultsEl, results, f.query);
        }).catch(function (err) {
            showError(resultsEl, '检索失败: ' + err.message);
        });
    }
}

// ===== 指南文档列表 =====
function renderDocList(container, docs) {
    if (!docs.length) {
        container.innerHTML = '<div class="alert alert-warning">未找到相关指南文档</div>';
        return;
    }
    let html = '<div class="alert alert-success">共 ' + docs.length + ' 篇指南文档</div>';
    html += '<div class="grid-2">';
    docs.forEach(function (d) {
        const cancerTags = (d.cancer_types || []).map(function (c) {
            return '<span class="badge" style="background:var(--color-info-bg);color:var(--color-info);margin-right:0.25rem;">' + escapeHtml(c) + '</span>';
        }).join('');
        html += '<div class="card" style="padding:0.875rem 1rem;cursor:pointer;" onclick="viewGuideDetail(\'' + escapeHtml(d.doc_id || '') + '\')">';
        html += '<div style="font-weight:600;color:var(--color-text);margin-bottom:0.375rem;">' + escapeHtml(d.title || d.doc_id || '') + '</div>';
        html += '<div style="font-size:0.75rem;color:var(--color-text-muted);margin-bottom:0.5rem;">'
              + escapeHtml(d.issuer || '') + (d.doc_type ? ' · ' + escapeHtml(docTypeLabel(d.doc_type)) : '')
              + (d.publish_date ? ' · ' + escapeHtml(d.publish_date) : '') + '</div>';
        html += '<div style="font-size:0.75rem;">' + cancerTags
              + '<span style="color:var(--color-text-muted);">' + (d.item_count || 0) + ' 条推荐</span></div>';
        html += '</div>';
    });
    html += '</div>';
    container.innerHTML = html;
}

// ===== 推荐条目检索结果 =====
function renderSearchResults(container, results, query) {
    if (!results.length) {
        container.innerHTML = '<div class="alert alert-warning">未找到相关推荐条目</div>';
        return;
    }
    let html = '<div class="alert alert-success">找到 ' + results.length + ' 条相关推荐条目</div>';
    html += '<div style="display:flex;flex-direction:column;gap:0.625rem;">';
    results.forEach(function (r) {
        const meta = r.metadata || {};
        html += '<div class="card" style="padding:0.875rem 1rem;">';

        // 标题行：来源标签 + 证据/强度徽标 + 匹配度
        html += '<div style="display:flex;justify-content:space-between;gap:0.5rem;flex-wrap:wrap;align-items:center;margin-bottom:0.375rem;">';
        html += '<div style="font-weight:600;color:var(--color-text);font-size:0.875rem;">'
              + escapeHtml(meta.title || meta.item_id || '') + '</div>';
        html += '<div style="display:flex;gap:0.375rem;flex-wrap:wrap;">';
        if (meta.evidence_level) {
            html += '<span class="badge badge-info" title="证据等级">证据 ' + escapeHtml(String(meta.evidence_level)) + '</span>';
        }
        if (meta.rec_strength) {
            html += '<span class="badge badge-warning" title="推荐强度">推荐 ' + escapeHtml(String(meta.rec_strength)) + '</span>';
        }
        if (r.match_score !== null && r.match_score !== undefined) {
            html += '<span class="badge" style="background:var(--color-bg);color:var(--color-text-secondary);">匹配 ' + (r.match_score * 100).toFixed(0) + '%</span>';
        }
        html += '</div></div>';

        // 溯源
        const srcParts = [];
        if (meta.breadcrumb) srcParts.push(escapeHtml(meta.breadcrumb));
        if (meta.cancer_type) srcParts.push('癌种 ' + escapeHtml(meta.cancer_type));
        if (meta.scenario) srcParts.push('场景 ' + escapeHtml(meta.scenario));
        if (srcParts.length) {
            html += '<div style="font-size:0.75rem;color:var(--color-text-muted);margin-bottom:0.375rem;">' + srcParts.join(' · ') + '</div>';
        }

        // 引用扩展标记
        if (r.retrieval_hop === 2) {
            const ref = r.referenced_doc_name
                ? ('引用自《' + escapeHtml(r.referenced_doc_name) + '》')
                : ('由 ' + escapeHtml(r.referenced_by || '') + ' 引用补入');
            html += '<div style="font-size:0.7rem;color:var(--color-warning);margin-bottom:0.25rem;">↳ ' + ref + '</div>';
        }

        // 正文
        html += '<div style="font-size:0.8125rem;color:var(--color-text-secondary);line-height:1.6;white-space:pre-wrap;">' + escapeHtml(r.content || '') + '</div>';
        html += '</div>';
    });
    html += '</div>';
    container.innerHTML = html;
}

function docTypeLabel(t) {
    const map = { guideline: '指南', standard: '规范', consensus: '共识' };
    return map[t] || t;
}

// ===== 指南详情跳转 =====
window.viewGuideDetail = function (docId) {
    if (!docId) return;
    saveSearchState();
    window.location.hash = '#/guideline/' + docId;
};

// ===== 搜索状态保存 / 恢复（只存条件，返回时重新检索）=====
function saveSearchState() {
    const f = currentFilters();
    try { sessionStorage.setItem('search_state', JSON.stringify(f)); } catch (e) { /* ignore */ }
}

function restoreSearchState() {
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
