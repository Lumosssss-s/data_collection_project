/**
 * 知识库管理页面（BE-13）
 * 路由: #/admin
 *
 * 管理员通过令牌（MEDICAL_ADMIN_TOKEN）访问知识库管理接口：
 *   - 条目管理：新增 / 编辑 / 删除 / 批量导入（doc / rec / drug / term）
 *   - 文档目录：浏览 / 重建
 */
registerPage('admin', function (container) {
    container.innerHTML = `
        <h1 class="page-title">知识库管理</h1>
        <p class="page-desc">管理已入库的指南文档与推荐条目（doc / rec / drug / term）。批量文件入库请使用 ingest.py。</p>
        <hr class="divider">

        <div class="card" style="padding:1rem;">
            <label style="font-size:0.8125rem;font-weight:600;color:var(--color-text-secondary);display:block;margin-bottom:0.375rem;">管理员令牌（MEDICAL_ADMIN_TOKEN）</label>
            <div style="display:flex;gap:0.5rem;align-items:center;">
                <input type="password" id="admin-token" class="input" placeholder="请输入管理员令牌" style="flex:1;">
                <button class="btn btn-secondary" onclick="adminSaveToken()">保存</button>
            </div>
            <div id="admin-token-hint" style="font-size:0.75rem;color:var(--color-text-muted);margin-top:0.375rem;"></div>
        </div>

        <!-- Tab 切换 -->
        <div style="display:flex;gap:0.5rem;margin-top:1rem;">
            <button class="btn btn-primary btn-sm admin-tab-btn" data-tab="items">条目管理</button>
            <button class="btn btn-secondary btn-sm admin-tab-btn" data-tab="add">新增条目</button>
            <button class="btn btn-secondary btn-sm admin-tab-btn" data-tab="batch">批量导入</button>
            <button class="btn btn-secondary btn-sm admin-tab-btn" data-tab="catalog">文档目录</button>
        </div>

        <div id="admin-panel-items" class="admin-panel" style="margin-top:0.75rem;"></div>
        <div id="admin-panel-add" class="admin-panel" style="margin-top:0.75rem;display:none;"></div>
        <div id="admin-panel-batch" class="admin-panel" style="margin-top:0.75rem;display:none;"></div>
        <div id="admin-panel-catalog" class="admin-panel" style="margin-top:0.75rem;display:none;"></div>
    `;

    adminRefreshTokenHint();
    renderAdminItemsPanel();
    renderAdminAddPanel();

    container.querySelectorAll('.admin-tab-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            container.querySelectorAll('.admin-tab-btn').forEach(function (b) {
                b.className = 'btn btn-secondary btn-sm admin-tab-btn';
            });
            this.className = 'btn btn-primary btn-sm admin-tab-btn';
            container.querySelectorAll('.admin-panel').forEach(function (p) { p.style.display = 'none'; });
            document.getElementById('admin-panel-' + this.dataset.tab).style.display = 'block';

            if (this.dataset.tab === 'catalog') renderAdminCatalogPanel();
            if (this.dataset.tab === 'batch') renderAdminBatchPanel();
        });
    });
});

// ===== Token =====
function adminToken() {
    return localStorage.getItem('medicalAdminToken') || '';
}

window.adminSaveToken = function () {
    localStorage.setItem('medicalAdminToken', (document.getElementById('admin-token').value || '').trim());
    adminRefreshTokenHint();
};

function adminRefreshTokenHint() {
    const hint = document.getElementById('admin-token-hint');
    const input = document.getElementById('admin-token');
    if (!hint || !input) return;
    const t = adminToken();
    if (t) { hint.textContent = '已保存令牌（浏览器本地存储）'; input.value = t; }
    else { hint.textContent = '尚未保存令牌，管理操作将返回 401/403'; }
}

// ===== 请求封装 =====
async function adminRequest(method, path, body, params) {
    const url = new URL(API_BASE + path, window.location.origin);
    if (params) {
        Object.entries(params).forEach(function (kv) {
            if (kv[1] !== undefined && kv[1] !== null && kv[1] !== '') url.searchParams.set(kv[0], kv[1]);
        });
    }
    const opts = { method: method, headers: { 'Authorization': 'Bearer ' + adminToken() } };
    if (body !== undefined) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }
    const resp = await fetch(url.toString(), opts);
    if (resp.status === 401 || resp.status === 403) throw new Error('认证失败：请检查管理员令牌');
    const json = await resp.json().catch(function () { return null; });
    if (!resp.ok) throw new Error((json && json.detail) || ('API错误: ' + resp.status));
    return json;
}

const adminGet = function (path, params) { return adminRequest('GET', path, undefined, params); };
const adminPost = function (path, body, params) { return adminRequest('POST', path, body === null ? undefined : body, params); };
const adminPut = function (path, body, params) { return adminRequest('PUT', path, body, params); };
const adminDelete = function (path) { return adminRequest('DELETE', path); };

// ===== 面板一：条目管理 =====
function renderAdminItemsPanel() {
    const el = document.getElementById('admin-panel-items');
    el.innerHTML = `
        <div class="card" style="padding:1rem;">
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;">
                <select id="admin-data-type" class="select" style="width:auto;">
                    <option value="">全部类型</option>
                    <option value="doc">doc 指南</option>
                    <option value="rec">rec 推荐条目</option>
                    <option value="drug">drug 药品说明书</option>
                    <option value="term">term 术语</option>
                </select>
                <button class="btn btn-primary btn-sm" onclick="adminLoadItems()">加载条目</button>
            </div>
        </div>
        <div id="admin-items-list" style="margin-top:0.75rem;"></div>
    `;
}

window.adminLoadItems = function () {
    const box = document.getElementById('admin-items-list');
    const dataType = document.getElementById('admin-data-type').value;
    showLoading(box);
    adminGet('/admin/items', { data_type: dataType, page_size: 100 }).then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '加载失败'); return; }
        const items = (resp.data && resp.data.items) || [];
        let html = '<div class="card" style="padding:1rem;"><div class="card-title">条目（' + items.length + ' 条）</div>';
        if (!items.length) {
            html += emptyState('暂无条目');
        } else {
            html += '<div class="table-wrap"><table>';
            html += '<tr>' + ['ID', '类型', '标题', '癌种', '操作'].map(function (h) {
                return '<th style="border:1px solid var(--color-border);padding:6px 10px;text-align:left;background:var(--color-bg);">' + h + '</th>';
            }).join('') + '</tr>';
            items.forEach(function (it) {
                const id = adminItemId(it);
                const title = it.title || it.canonical || it.generic_name || it.breadcrumb || '';
                const cancer = (it.cancer_types || (it.cancer_type ? [it.cancer_type] : [])).join('、');
                html += '<tr>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;font-family:var(--font-mono);font-size:0.75rem;">' + escapeHtml(id) + '</td>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + escapeHtml(it.data_type || '') + '</td>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + escapeHtml(title) + '</td>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + escapeHtml(cancer) + '</td>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;white-space:nowrap;">'
                      + '<button class="btn btn-ghost btn-sm" onclick="adminEditItem(\'' + escapeHtml(id) + '\')">编辑</button>'
                      + '<button class="btn btn-ghost btn-sm" style="color:var(--color-error);" onclick="adminDeleteItem(\'' + escapeHtml(id) + '\')">删除</button>'
                      + '</td>';
                html += '</tr>';
            });
            html += '</table></div>';
        }
        html += '</div>';
        box.innerHTML = html;
    }).catch(function (err) { showError(box, err.message); });
};

function adminItemId(it) {
    return it._id || it.doc_id || it.rec_id || it.drug_id || it.term_id || '';
}

window.adminDeleteItem = function (id) {
    if (!confirm('确认删除条目 ' + id + ' ？此操作不可撤销。')) return;
    const box = document.getElementById('admin-items-list');
    adminDelete('/admin/item/' + encodeURIComponent(id)).then(function (resp) {
        if (resp && resp.success) { window.adminLoadItems(); }
        else { alert('删除失败：' + ((resp && resp.message) || '未知错误')); }
    }).catch(function (err) { alert('删除失败：' + err.message); });
};

window.adminEditItem = function (id) {
    const box = document.getElementById('admin-items-list');
    adminGet('/admin/item/' + encodeURIComponent(id)).then(function (resp) {
        if (!resp || !resp.success) { alert('获取条目失败'); return; }
        const item = resp.data;
        // 以 JSON 编辑（覆盖所有字段，兼容各 data_type 的异构字段）
        box.innerHTML = `
            <div class="card" style="padding:1rem;">
                <div class="card-title">编辑条目：${escapeHtml(id)}（JSON）</div>
                <textarea id="admin-edit-json" class="textarea" style="width:100%;height:320px;font-family:var(--font-mono);font-size:0.75rem;">${escapeHtml(JSON.stringify(item, null, 2))}</textarea>
                <div style="margin-top:0.5rem;display:flex;gap:0.5rem;">
                    <button class="btn btn-primary btn-sm" onclick="adminSaveEdit('${escapeHtml(id)}')">保存</button>
                    <button class="btn btn-secondary btn-sm" onclick="adminLoadItems()">取消</button>
                </div>
                <div style="font-size:0.75rem;color:var(--color-text-muted);margin-top:0.375rem;">提示：JSON 中的业务 ID 字段（doc_id/rec_id/drug_id/term_id）不会被覆盖。</div>
            </div>`;
    }).catch(function (err) { alert('获取条目失败：' + err.message); });
};

window.adminSaveEdit = function (id) {
    let payload;
    try {
        payload = JSON.parse(document.getElementById('admin-edit-json').value);
    } catch (e) {
        alert('JSON 格式错误：' + e.message);
        return;
    }
    adminPut('/admin/item/' + encodeURIComponent(id), payload).then(function (resp) {
        if (resp && resp.success) window.adminLoadItems();
        else alert('保存失败：' + ((resp && resp.message) || '未知错误'));
    }).catch(function (err) { alert('保存失败：' + err.message); });
};

// ===== 面板二：新增条目 =====
function renderAdminAddPanel() {
    const el = document.getElementById('admin-panel-add');
    el.innerHTML = `
        <div class="card" style="padding:1rem;">
            <label style="font-size:0.8125rem;font-weight:600;color:var(--color-text-secondary);display:block;margin-bottom:0.375rem;">条目类型</label>
            <select id="admin-add-type" class="select" style="width:auto;margin-bottom:0.75rem;">
                <option value="doc">doc 指南</option>
                <option value="rec">rec 推荐条目</option>
                <option value="drug">drug 药品说明书</option>
                <option value="term">term 术语</option>
            </select>
            <div id="admin-add-fields"></div>
            <button class="btn btn-primary btn-sm" style="margin-top:0.75rem;" onclick="adminCreateItem()">新增</button>
            <div id="admin-add-result" style="margin-top:0.5rem;"></div>
        </div>
    `;
    document.getElementById('admin-add-type').addEventListener('change', renderAdminAddFields);
    renderAdminAddFields();
}

function field(label, id, placeholder, required) {
    return '<div style="margin-bottom:0.5rem;"><label style="font-size:0.75rem;color:var(--color-text-secondary);display:block;margin-bottom:0.2rem;">'
        + label + (required ? ' <span style="color:var(--color-error);">*</span>' : '')
        + '</label><input type="text" id="' + id + '" class="input" placeholder="' + (placeholder || '') + '" style="width:100%;"></div>';
}

function renderAdminAddFields() {
    const type = document.getElementById('admin-add-type').value;
    const wrap = document.getElementById('admin-add-fields');
    let html = '';

    if (type === 'doc') {
        html += field('文档 ID (doc_id)', 'f-doc_id', 'DOC-LUNG-2025', true);
        html += field('标题 (title)', 'f-title', '非小细胞肺癌诊疗指南', true);
        html += field('文档类型 (doc_type)', 'f-doc_type', 'guideline / standard / consensus');
        html += field('发布机构 (issuer)', 'f-issuer', '中国临床肿瘤学会');
        html += field('发布日期 (publish_date)', 'f-publish_date', '2025-03-01');
        html += field('版本 (version)', 'f-version', '2025');
        html += field('癌种 (cancer_types)', 'f-cancer_types', 'lung,breast（逗号分隔）');
        html += field('条目数 (item_count)', 'f-item_count', '0');
        html += field('摘要 (summary)', 'f-summary', '');
    } else if (type === 'rec') {
        html += field('条目 ID (rec_id)', 'f-rec_id', 'REC-LUNG-001', true);
        html += field('所属文档 (doc_id)', 'f-doc_id', 'DOC-LUNG-2025', true);
        html += field('癌种 (cancer_type)', 'f-cancer_type', 'lung', true);
        html += field('标题 (title)', 'f-title', '一线靶向治疗');
        html += field('正文 (content)', 'f-content', '', true);
        html += field('位置 (breadcrumb)', 'f-breadcrumb', '第四章 治疗 > 靶向治疗');
        html += field('场景 (scenario)', 'f-scenario', 'treatment_first_line');
        html += field('证据等级 (evidence_level)', 'f-evidence_level', 'high / moderate / low');
        html += field('推荐强度 (rec_strength)', 'f-rec_strength', 'strong / weak');
        html += field('生物标志物 (biomarker)', 'f-biomarker', 'EGFR,PD-L1（逗号分隔）');
        html += field('分期 (stage)', 'f-stage', 'III,IV（逗号分隔）');
    } else if (type === 'drug') {
        html += field('药品 ID (drug_id)', 'f-drug_id', 'DRUG-OSIMERTINIB', true);
        html += field('通用名 (generic_name)', 'f-generic_name', '奥希替尼');
        html += field('商品名 (brand_name)', 'f-brand_name', '泰瑞沙');
        html += field('正文 (content)', 'f-content', '');
        html += field('癌种 (cancer_type)', 'f-cancer_type', 'lung');
    } else {
        html += field('术语 ID (term_id)', 'f-term_id', 'TERM-EGFR', true);
        html += field('规范名 (canonical)', 'f-canonical', '表皮生长因子受体');
        html += field('别名 (aliases)', 'f-aliases', 'EGFR,HER1（逗号分隔）');
        html += field('正文 (content)', 'f-content', '');
    }
    html += '<div style="font-size:0.75rem;color:var(--color-text-muted);">提示：doc 类型会自动同步文档目录；癌种/多值字段用英文逗号分隔。</div>';
    wrap.innerHTML = html;
}

function val(id) {
    const el = document.getElementById(id);
    return el ? el.value.trim() : '';
}

function splitCsv(s) {
    return s ? s.split(/[,，]/).map(function (x) { return x.trim(); }).filter(Boolean) : [];
}

window.adminCreateItem = function () {
    const type = document.getElementById('admin-add-type').value;
    const resultEl = document.getElementById('admin-add-result');
    const data = buildCreatePayload(type);

    // 校验必填
    const required = type === 'doc' ? ['doc_id', 'title']
        : type === 'rec' ? ['rec_id', 'doc_id', 'cancer_type', 'content']
        : type === 'drug' ? ['drug_id'] : ['term_id'];
    const missing = required.filter(function (k) { return !data[k]; });
    if (missing.length) { resultEl.innerHTML = '<div class="alert alert-error">缺少必填字段：' + missing.join(', ') + '</div>'; return; }

    adminPost('/admin/item', data, { data_type: type }).then(function (resp) {
        if (resp && resp.success) {
            resultEl.innerHTML = '<div class="alert alert-success">新增成功：' + escapeHtml(JSON.stringify(resp.data)) + '</div>';
        } else {
            resultEl.innerHTML = '<div class="alert alert-error">新增失败：' + escapeHtml((resp && resp.message) || '未知错误') + '</div>';
        }
    }).catch(function (err) {
        resultEl.innerHTML = '<div class="alert alert-error">新增失败：' + escapeHtml(err.message) + '</div>';
    });
};

function buildCreatePayload(type) {
    if (type === 'doc') {
        return omitEmpty({
            doc_id: val('f-doc_id'), title: val('f-title'), doc_type: val('f-doc_type'),
            issuer: val('f-issuer'), publish_date: val('f-publish_date'), version: val('f-version'),
            cancer_types: splitCsv(val('f-cancer_types')),
            item_count: val('f-item_count') ? parseInt(val('f-item_count')) : undefined,
            summary: val('f-summary'),
        });
    }
    if (type === 'rec') {
        return omitEmpty({
            rec_id: val('f-rec_id'), doc_id: val('f-doc_id'), cancer_type: val('f-cancer_type'),
            title: val('f-title'), content: val('f-content'), breadcrumb: val('f-breadcrumb'),
            scenario: val('f-scenario'), evidence_level: val('f-evidence_level'),
            rec_strength: val('f-rec_strength'),
            biomarker: splitCsv(val('f-biomarker')), stage: splitCsv(val('f-stage')),
        });
    }
    if (type === 'drug') {
        return omitEmpty({
            drug_id: val('f-drug_id'), generic_name: val('f-generic_name'),
            brand_name: val('f-brand_name'), content: val('f-content'), cancer_type: val('f-cancer_type'),
        });
    }
    return omitEmpty({
        term_id: val('f-term_id'), canonical: val('f-canonical'),
        aliases: splitCsv(val('f-aliases')), content: val('f-content'),
    });
}

function omitEmpty(obj) {
    const out = {};
    Object.keys(obj).forEach(function (k) {
        const v = obj[k];
        if (v === '' || v === undefined || v === null) return;
        if (Array.isArray(v) && v.length === 0) return;
        out[k] = v;
    });
    return out;
}

// ===== 面板三：批量导入 =====
function renderAdminBatchPanel() {
    const el = document.getElementById('admin-panel-batch');
    el.innerHTML = `
        <div class="card" style="padding:1rem;">
            <div class="card-title">批量导入（JSON）</div>
            <div style="font-size:0.75rem;color:var(--color-text-muted);margin-bottom:0.5rem;">格式：[{"data_type":"rec","data":{...}}, ...]</div>
            <textarea id="admin-batch-json" class="textarea" style="width:100%;height:260px;font-family:var(--font-mono);font-size:0.75rem;" placeholder='[{"data_type":"rec","data":{"rec_id":"R1","doc_id":"D1","cancer_type":"lung","content":"..."}}]'></textarea>
            <button class="btn btn-primary btn-sm" style="margin-top:0.5rem;" onclick="adminBatchImport()">导入</button>
            <div id="admin-batch-result" style="margin-top:0.5rem;"></div>
        </div>`;
}

window.adminBatchImport = function () {
    const resultEl = document.getElementById('admin-batch-result');
    let payload;
    try {
        payload = JSON.parse(document.getElementById('admin-batch-json').value);
        if (!Array.isArray(payload)) throw new Error('顶层必须是数组');
    } catch (e) {
        resultEl.innerHTML = '<div class="alert alert-error">JSON 格式错误：' + escapeHtml(e.message) + '</div>';
        return;
    }
    adminPost('/admin/items/batch', payload).then(function (resp) {
        if (resp && resp.success) {
            const d = resp.data || {};
            let html = '<div class="alert alert-success">导入完成：成功 ' + (d.success_count || 0) + ' 条，失败 ' + (d.failed_count || 0) + ' 条</div>';
            if ((d.failed || []).length) {
                html += '<div class="alert alert-warning" style="font-size:0.75rem;">失败明细：' + escapeHtml(JSON.stringify(d.failed)) + '</div>';
            }
            resultEl.innerHTML = html;
        } else {
            resultEl.innerHTML = '<div class="alert alert-error">导入失败：' + escapeHtml((resp && resp.message) || '未知错误') + '</div>';
        }
    }).catch(function (err) {
        resultEl.innerHTML = '<div class="alert alert-error">导入失败：' + escapeHtml(err.message) + '</div>';
    });
};

// ===== 面板四：文档目录 =====
function renderAdminCatalogPanel() {
    const el = document.getElementById('admin-panel-catalog');
    el.innerHTML = `
        <div class="card" style="padding:1rem;">
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">
                <button class="btn btn-primary btn-sm" onclick="adminLoadCatalog()">加载目录</button>
                <button class="btn btn-secondary btn-sm" onclick="adminSyncCatalog()">从 ES 重建目录</button>
            </div>
        </div>
        <div id="admin-catalog-list" style="margin-top:0.75rem;"></div>`;
}

window.adminLoadCatalog = function () {
    const box = document.getElementById('admin-catalog-list');
    showLoading(box);
    adminGet('/admin/catalog').then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '加载失败'); return; }
        const docs = (resp.data && resp.data.docs) || [];
        let html = '<div class="card" style="padding:1rem;"><div class="card-title">文档目录（' + docs.length + ' 篇）</div>';
        if (!docs.length) {
            html += '<div class="alert alert-info">目录为空（可先运行 ingest.py 入库）</div>';
        } else {
            html += '<div class="table-wrap"><table>';
            html += '<tr>' + ['文档 ID', '标题', '类型', '癌种', '条目数', '状态'].map(function (h) {
                return '<th style="border:1px solid var(--color-border);padding:6px 10px;text-align:left;background:var(--color-bg);">' + h + '</th>';
            }).join('') + '</tr>';
            docs.forEach(function (d) {
                html += '<tr>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;font-family:var(--font-mono);font-size:0.75rem;">' + escapeHtml(d.doc_id || '') + '</td>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + escapeHtml(d.title || '') + '</td>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + escapeHtml(d.doc_type || '') + '</td>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + escapeHtml((d.cancer_types || []).join('、')) + '</td>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + (d.item_count || 0) + '</td>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + escapeHtml(d.status || '') + '</td>';
                html += '</tr>';
            });
            html += '</table></div>';
        }
        html += '</div>';
        box.innerHTML = html;
    }).catch(function (err) { showError(box, err.message); });
};

window.adminSyncCatalog = function () {
    const box = document.getElementById('admin-catalog-list');
    showLoading(box);
    adminPost('/admin/sync').then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '重建失败'); return; }
        box.innerHTML = '<div class="alert alert-success">目录已从 ES 重建：' +
            escapeHtml(JSON.stringify(resp.data.statistics || {})) + '</div>';
    }).catch(function (err) { showError(box, err.message); });
};
