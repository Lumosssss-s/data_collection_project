/**
 * 疾病知识库列表页（NM-01）
 * 路由：#/diseases
 * 功能：名称归一检索 / 症状反查 / 分类浏览（分面）
 */
registerPage('diseases', function (container) {
    container.innerHTML = `
        <h1 class="page-title">疾病知识库</h1>
        <p class="page-subtitle" style="color:var(--color-text-muted);margin-bottom:1rem;">
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
        html += '<div class="card" style="padding:0.75rem 1rem;margin-bottom:0.75rem;">';
        if (cats.length) {
            html += '<div style="margin-bottom:0.5rem;"><span style="font-size:0.8125rem;color:var(--color-text-muted);margin-right:0.5rem;">类别</span>';
            html += facetChips(cats, 'category');
            html += '</div>';
        }
        if (cts.length) {
            html += '<div><span style="font-size:0.8125rem;color:var(--color-text-muted);margin-right:0.5rem;">癌种</span>';
            html += facetChips(cts, 'cancer_type');
            html += '</div>';
        }
        html += '</div>';
    }

    html += '<div style="font-size:0.875rem;color:var(--color-text-muted);margin-bottom:0.5rem;">共 ' + (data.total || 0) + ' 个疾病档案</div>';

    if (!data.items || !data.items.length) {
        if (!data.degraded) html += '<div class="alert alert-info">暂无疾病档案</div>';
    } else {
        html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:0.75rem;">';
        data.items.forEach(function (it) { html += diseaseCard(it); });
        html += '</div>';
    }

    box.innerHTML = html;
    bindFacetChips(box);
}

function facetChips(items, key) {
    const cur = _diseaseFilter[key] || '';
    let html = '<button class="badge ' + (cur === '' ? 'badge-primary' : 'badge-muted') +
        '" style="cursor:pointer;border:none;margin-right:0.375rem;" data-facet="' + key + '" data-value="">全部</button>';
    items.forEach(function (f) {
        const val = f.value || '';
        const label = f.label || val;
        const active = cur === val;
        html += '<button class="badge ' + (active ? 'badge-primary' : 'badge-muted') +
            '" style="cursor:pointer;border:none;margin-right:0.375rem;" data-facet="' + key +
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
        html += '<div class="alert alert-info">' + escapeHtml(data.note || '未找到匹配的疾病') + '</div>';
    }

    if (data.normalized && mode === 'name' && data.normalized !== q) {
        html += '<div class="alert alert-info">名称已归一：「' + escapeHtml(q) + '」→「' + escapeHtml(data.normalized) + '」</div>';
    }

    html += '<div style="font-size:0.875rem;color:var(--color-text-muted);margin:0.75rem 0;">命中 ' + (data.total || 0) + ' 个疾病</div>';
    if (data.items && data.items.length) {
        html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:0.75rem;">';
        data.items.forEach(function (it) { html += diseaseCard(it); });
        html += '</div>';
    } else {
        html += '<button class="btn btn-secondary btn-sm" onclick="loadDiseaseBrowse()">返回浏览全部</button>';
    }
    box.innerHTML = html;
}

function diseaseCard(it) {
    const name = it.name_canonical || it.disease_id || '未命名';
    let html = '<a class="card" href="#/disease/' + encodeURIComponent(it.disease_id) + '" style="text-decoration:none;color:inherit;padding:1rem;display:block;">';
    html += '<div style="font-weight:600;font-size:1rem;margin-bottom:0.25rem;">' + escapeHtml(name) + '</div>';
    if (it.name_en) html += '<div style="font-size:0.75rem;color:var(--color-text-muted);margin-bottom:0.375rem;">' + escapeHtml(it.name_en) + '</div>';
    html += '<div style="margin-bottom:0.5rem;">';
    if (it.category_label) html += '<span class="badge badge-info">' + escapeHtml(it.category_label) + '</span> ';
    if (it.cancer_type) html += '<span class="badge badge-muted">' + escapeHtml(it.cancer_type) + '</span>';
    html += '</div>';
    if (it.overview) html += '<div style="font-size:0.8125rem;color:var(--color-text-secondary);line-height:1.5;">' + escapeHtml(it.overview) + '…</div>';
    if (it.departments && it.departments.length) {
        html += '<div style="font-size:0.75rem;color:var(--color-text-muted);margin-top:0.5rem;">就诊科室：' + escapeHtml(it.departments.join('、')) + '</div>';
    }
    html += '</a>';
    return html;
}
