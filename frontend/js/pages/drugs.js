/**
 * 药品库（NM-06 列表入口）
 * 路由：#/drugs
 * 数据：GET /patient/drugs（零 LLM，单请求）。2026-11-02 起后端直接透传
 *       cancer_types（说明书适应证口径）/ guideline_use_cancers（指南超适应证口径）/
 *       has_boxed_warning（黑框警示，由 boxed_warning 非空推导，不返回整段文本）/
 *       aliases_zh（中文通用名别名），前端不再做多请求推导。
 *       列表绝不调用 /patient/drug/{id}（该接口每次触发 LLM 白话改写，5–10 秒）。
 */
const DRUG_CANCERS = [
    { code: 'lung', label: '肺癌' },
    { code: 'breast', label: '乳腺癌' },
    { code: 'colorectal', label: '结直肠癌' },
    { code: 'gastric', label: '胃癌' }
];

let _drugState = { items: [], counts: {}, filter: { cancer: '', q: '' }, loaded: false };

registerPage('drugs', function (container) {
    // 二级路由：#/drugs/{drug_id} → 药品详情（归属疾病知识库组，高亮药品库）；
    // 详情数据接口 /patient/drug/{id} 每次触发 LLM 白话改写，属既有行为，列表不调用。
    const hash = window.location.hash.replace('#/', '');
    if (hash.indexOf('drugs/') === 0) {
        renderDrugDetailPage(container, decodeURIComponent(hash.slice('drugs/'.length)));
        return;
    }

    container.innerHTML = ''
        + '<h1 class="page-title">药品库</h1>'
        + '<p class="page-desc">说明书适应证、警示与相互作用</p>'
        + '<div class="card" style="padding:0.75rem 1rem;margin:0.75rem 0 1rem;">'
        + '<div style="display:flex;gap:0.75rem;flex-wrap:wrap;align-items:center;">'
        + '<input id="drugs-q" class="input" style="flex:1;min-width:200px;" placeholder="按中文名 / 通用名 / 商品名过滤，例如 他莫昔芬 或 OSIMERTINIB">'
        + '<label style="font-size:0.8125rem;color:var(--color-text-secondary);">癌种 '
        + '<select id="drugs-cancer" class="select" style="width:auto;"><option value="">全部癌种</option></select></label>'
        + '<button id="drugs-reset" class="btn btn-ghost btn-sm">重置</button>'
        + '</div></div>'
        + '<div id="drugs-result"></div>';

    document.getElementById('drugs-q').addEventListener('input', function () {
        _drugState.filter.q = this.value.trim();
        renderDrugGrid();
    });
    document.getElementById('drugs-cancer').addEventListener('change', function () {
        _drugState.filter.cancer = this.value;
        renderDrugGrid();
    });
    document.getElementById('drugs-reset').addEventListener('click', function () {
        _drugState.filter = { cancer: '', q: '' };
        document.getElementById('drugs-q').value = '';
        document.getElementById('drugs-cancer').value = '';
        renderDrugGrid();
    });

    loadDrugLibrary();
});

// 单请求、零 LLM；癌种计数按 cancer_types（说明书适应证口径）客户端推导
function loadDrugLibrary() {
    const box = document.getElementById('drugs-result');
    showLoading(box);
    window.__drugsPerf = { t0: performance.now(), t1: null, ms: null };

    api.get('/patient/drugs', {})
        .then(function (res) {
            if (!res || !res.success) {
                showError(box, '药品列表加载失败: ' + ((res && res.message) || '未知错误'));
                return;
            }
            const items = (res.data && res.data.items) || [];
            const counts = {};
            DRUG_CANCERS.forEach(function (c) { counts[c.code] = 0; });
            items.forEach(function (it) {
                (it.cancer_types || []).forEach(function (code) {
                    if (counts.hasOwnProperty(code)) counts[code]++;
                });
            });
            _drugState.items = items;
            _drugState.counts = counts;
            _drugState.loaded = true;

            const sel = document.getElementById('drugs-cancer');
            DRUG_CANCERS.forEach(function (c) {
                const opt = document.createElement('option');
                opt.value = c.code;
                opt.textContent = c.label + '（' + (counts[c.code] || 0) + '）';
                sel.appendChild(opt);
            });

            window.__drugsPerf.t1 = performance.now();
            window.__drugsPerf.ms = Math.round(window.__drugsPerf.t1 - window.__drugsPerf.t0);
            renderDrugGrid();
        })
        .catch(function (e) {
            showError(box, '药品列表加载失败: ' + (e && e.message ? e.message : '网络错误'));
        });
}

function renderDrugGrid() {
    const box = document.getElementById('drugs-result');
    if (!box) return;
    if (!_drugState.loaded) return;

    const f = _drugState.filter;
    const q = f.q.toLowerCase();
    const list = _drugState.items.filter(function (it) {
        if (f.cancer && (it.cancer_types || []).indexOf(f.cancer) < 0) return false;
        if (q) {
            const name = String(it.generic_name || '').toLowerCase();
            const brand = (it.brand_names || []).join(' ').toLowerCase();
            const zh = (it.aliases_zh || []).join(' ').toLowerCase();
            if (name.indexOf(q) < 0 && brand.indexOf(q) < 0 && zh.indexOf(q) < 0) return false;
        }
        return true;
    });

    let html = '<div class="results-toolbar">'
        + '<div class="results-count"><strong>' + list.length + '</strong> / ' + _drugState.items.length + ' 个药品</div>'
        + '<div class="results-note">说明书适应证口径 · 零 LLM 列表</div>'
        + '</div>';

    if (!list.length) {
        html += emptyState('未找到匹配的药品，请更换关键词或癌种筛选。');
        box.innerHTML = html;
        return;
    }

    html += '<div class="doc-grid">';
    list.forEach(function (it) { html += drugCard(it); });
    html += '</div>';
    box.innerHTML = html;
}

function drugCard(it) {
    // 癌种标签分两类：说明书适应证（实心）与指南超适应证（描边 + 指南推荐角标）
    let chips = '';
    (it.cancer_types || []).forEach(function (code) {
        chips += '<span data-cancer="' + code + '" style="display:inline-block;padding:0.125rem 0.5rem;margin:0 0.25rem 0.25rem 0;'
            + 'border-radius:6px;font-size:0.75rem;background:var(--color-primary);color:#F7F9F3;">'
            + cancerLabel(code) + '</span>';
    });
    (it.guideline_use_cancers || []).forEach(function (code) {
        chips += '<span data-guideline-cancer="' + code + '" style="display:inline-block;padding:0.125rem 0.5rem;margin:0 0.25rem 0.25rem 0;'
            + 'border-radius:6px;font-size:0.75rem;border:1px solid var(--color-primary);color:var(--color-primary);background:transparent;">'
            + cancerLabel(code)
            + '<span data-guideline-badge style="display:inline-block;margin-left:0.375rem;padding:0 0.25rem;border-radius:4px;'
            + 'font-size:0.6875rem;background:var(--color-primary-soft);color:var(--color-primary-text);">指南推荐</span>'
            + '</span>';
    });
    if (!chips) chips = '<span class="badge badge-muted">无癌种标注</span>';

    // 黑框警示：醒目但不刺眼（深暖红文字 + 浅底 + 细边）
    const boxed = it.has_boxed_warning
        ? '<span data-boxed-warning style="position:absolute;top:0.75rem;right:0.75rem;padding:0.0625rem 0.5rem;border-radius:6px;'
          + 'font-size:0.6875rem;color:#8C3B2E;background:rgba(140,59,46,0.08);border:1px solid rgba(140,59,46,0.35);">黑框警示</span>'
        : '';

    const brands = (it.brand_names || []).filter(Boolean);
    const zh = (it.aliases_zh || []).filter(Boolean);
    return '<a class="card" style="position:relative;text-decoration:none;color:inherit;padding:1rem;display:block;" href="#/drugs/' + encodeURIComponent(it.drug_id) + '">'
        + boxed
        + '<div class="item-title" style="padding-right:' + (boxed ? '4.5rem' : '0') + ';">' + escapeHtml(it.generic_name || it.drug_id || '') + '</div>'
        + (zh.length ? '<div style="font-size:0.8125rem;color:var(--color-text-secondary);margin:0.125rem 0 0;">' + escapeHtml(zh.join('、')) + '</div>' : '')
        + '<div style="font-size:0.75rem;color:var(--color-text-muted);margin:0.25rem 0 0.5rem;">'
        + (brands.length ? '商品名：' + escapeHtml(brands.join('、')) : '无商品名记录') + '</div>'
        + '<div>' + chips + '</div>'
        + '</a>';
}

function cancerLabel(code) {
    const c = DRUG_CANCERS.find(function (x) { return x.code === code; });
    return c ? c.label : code;
}

// 药品详情（#/drugs/{id}）：返回链接回本列表；视图复用 patient.js 的
// ptShell / renderPtDrugDetail（全局函数，含免责声明与相互作用折叠层）。
function renderDrugDetailPage(container, drugId) {
    if (!drugId) { window.location.hash = '#/drugs'; return; }
    container.innerHTML = ptShell(
        '<a class="pt-back" href="#/drugs">← 返回药品库</a><div id="drug-detail-box"></div>'
    );
    const box = document.getElementById('drug-detail-box');
    showLoading(box);
    api.get('/patient/drug/' + encodeURIComponent(drugId)).then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '未找到该药品'); return; }
        renderPtDrugDetail(box, resp.data);
    }).catch(function (err) { showError(box, err.message); });
}
