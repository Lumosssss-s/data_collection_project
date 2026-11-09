/**
 * 疾病知识库列表页（NM-01）
 * 路由：#/diseases
 * 功能：名称归一检索 / 症状反查 / 分类浏览（分面）
 */
registerPage('diseases', function (container) {
    container.innerHTML = `
        <h1 class="page-title">疾病知识库</h1>
        <p class="page-desc">
            以疾病为中心的结构化百科：支持按疾病名检索、按症状反查、按类别/癌种浏览。
        </p>

        <div class="card" style="padding:1rem;">
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;">
                <input id="disease-q" class="input" style="flex:1;min-width:200px;"
                       placeholder="输入疾病名（如 肺CA / NSCLC）或症状（如 咳嗽、咯血）">
                <select id="disease-mode" class="select" style="width:auto;">
                    <option value="name">按疾病名</option>
                    <option value="symptom">按症状反查</option>
                </select>
                <button id="disease-search-btn" class="btn btn-primary">检索</button>
            </div>
        </div>

        <div id="disease-browse" style="margin-top:1rem;"></div>
    `;

    const qInput = document.getElementById('disease-q');
    const modeSel = document.getElementById('disease-mode');
    document.getElementById('disease-search-btn').addEventListener('click', doDiseaseSearch);
    qInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') doDiseaseSearch();
    });

    loadDiseaseBrowse();
});

// 当前浏览筛选
let _diseaseFilter = { category: '', cancer_type: '' };

function doDiseaseSearch() {
    const q = (document.getElementById('disease-q').value || '').trim();
    const mode = document.getElementById('disease-mode').value;
    const box = document.getElementById('disease-browse');
    if (!q) { loadDiseaseBrowse(); return; }

    showLoading(box);
    api.get('/diseases/search', { q: q, mode: mode, size: 20 }).then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '检索失败'); return; }
        renderDiseaseResult(box, resp.data, q, mode);
    }).catch(function (err) { showError(box, err.message); });
}

function loadDiseaseBrowse() {
    const box = document.getElementById('disease-browse');
    showLoading(box);
    api.get('/diseases', {
        category: _diseaseFilter.category,
        cancer_type: _diseaseFilter.cancer_type,
        size: 200
    }).then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '加载失败'); return; }
        renderDiseaseBrowse(box, resp.data);
    }).catch(function (err) { showError(box, err.message); });
}

function renderDiseaseBrowse(box, data) {
    let html = '';

    if (data.degraded) {
        html += '<div class="alert alert-warning">' + escapeHtml(data.note || '数据未就绪') + '</div>';
    }

    // 分面筛选
    const cats = (data.facets && data.facets.category) || [];
    const cts = (data.facets && data.facets.cancer_type) || [];
    if (cats.length || cts.length) {
        html += '<div class="card d2-lib-filter">';
        if (cats.length) {
            html += '<div class="d2-lib-facet-row"><span class="d2-lib-facet-label">类别</span>';
            html += facetChips(cats, 'category');
            html += '</div>';
        }
        if (cts.length) {
            html += '<div class="d2-lib-facet-row"><span class="d2-lib-facet-label">癌种</span>';
            html += facetChips(cts, 'cancer_type');
            html += '</div>';
        }
        html += '</div>';
    }

    html += '<div class="d2-lib-count">共 ' + (data.total || 0) + ' 个疾病档案</div>';

    if (!data.items || !data.items.length) {
        if (!data.degraded) html += emptyState('暂无疾病档案');
    } else {
        html += '<div class="d2-lib-grid">';
        data.items.forEach(function (it) { html += diseaseCard(it); });
        html += '</div>';
    }

    box.innerHTML = html;
    bindFacetChips(box);
}

function facetChips(items, key) {
    const cur = _diseaseFilter[key] || '';
    let html = '<button class="badge d2-lib-chip ' + (cur === '' ? 'badge-primary' : 'badge-muted') +
        '" data-facet="' + key + '" data-value="">全部</button>';
    items.forEach(function (f) {
        const val = f.value || '';
        const label = f.label || val;
        const active = cur === val;
        html += '<button class="badge d2-lib-chip ' + (active ? 'badge-primary' : 'badge-muted') +
            '" data-facet="' + key +
            '" data-value="' + escapeHtml(val) + '">' + escapeHtml(label) + ' (' + f.count + ')</button>';
    });
    return html;
}

function bindFacetChips(box) {
    box.querySelectorAll('button[data-facet]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            _diseaseFilter[btn.dataset.facet] = btn.dataset.value || '';
            loadDiseaseBrowse();
        });
    });
}

function renderDiseaseResult(box, data, q, mode) {
    let html = '';
    if (data.degraded) {
        html += '<div class="alert alert-warning">' + escapeHtml(data.note || '数据未就绪') + '</div>';
    } else if (!data.total) {
        html += emptyState(data.note || '未找到匹配的疾病');
    }

    if (data.normalized && mode === 'name' && data.normalized !== q) {
        html += '<div class="alert alert-info">名称已归一：「' + escapeHtml(q) + '」→「' + escapeHtml(data.normalized) + '」</div>';
    }

    html += '<div class="d2-lib-count" style="margin:0.75rem 0;">命中 ' + (data.total || 0) + ' 个疾病</div>';
    if (data.items && data.items.length) {
        html += '<div class="d2-lib-grid">';
        data.items.forEach(function (it) { html += diseaseCard(it); });
        html += '</div>';
    } else {
        html += '<button class="btn btn-secondary btn-sm" onclick="loadDiseaseBrowse()">返回浏览全部</button>';
    }
    box.innerHTML = html;
}

// 拉丁串单独包裹：仅作用于卡片正文，让英文/数字上调一档而不带动周围汉字。
// 先按原始文本切段再转义，避免把 &amp; 这类实体切成碎片。
function latinizeText(raw) {
    const re = /[A-Za-z0-9][A-Za-z0-9 \t\-–—:;.,%()\/+'’]*/g;
    let out = '';
    let last = 0;
    let m;
    while ((m = re.exec(raw))) {
        out += escapeHtml(raw.slice(last, m.index));
        let s = m[0];
        const tm = s.match(/\s+$/);
        const trail = tm ? tm[0] : '';
        if (trail) s = s.slice(0, s.length - trail.length);
        if (s) out += '<span class="latin">' + escapeHtml(s) + '</span>';
        out += escapeHtml(trail);
        last = m.index + m[0].length;
    }
    return out + escapeHtml(raw.slice(last));
}

function diseaseCard(it) {
    const name = it.name_canonical || it.disease_id || '未命名';
    let html = '<a class="card d2-lib-card" href="#/disease/' + encodeURIComponent(it.disease_id) + '">';
    html += '<div class="item-title d2-lib-title">' + escapeHtml(name) + '</div>';
    if (it.name_en) html += '<div class="d2-lib-sub">' + escapeHtml(it.name_en) + '</div>';
    html += '<div class="d2-lib-tags">';
    if (it.category_label) html += '<span class="badge badge-info d2-lib-tag">' + escapeHtml(it.category_label) + '</span>';
    if (it.cancer_type) html += '<span class="badge badge-muted d2-lib-tag">' + escapeHtml(it.cancer_type) + '</span>';
    html += '</div>';
    if (it.overview) html += '<div class="d2-lib-desc">' + latinizeText(it.overview) + '…</div>';
    if (it.departments && it.departments.length) {
        html += '<div class="d2-lib-dept">就诊科室：' + escapeHtml(it.departments.join('、')) + '</div>';
    }
    html += '</a>';
    return html;
}
