/**
 * 知识库管理页面（BE-13）
 * 路由: #/admin
 *
 * 管理员通过 Token 访问知识库管理接口：文档目录 / 条目浏览。
 * Token 存于 localStorage，随请求头 X-Admin-Token 之外统一用 Authorization: Bearer。
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

        <div class="card" style="margin-top:0.75rem;padding:1rem;">
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;">
                <button class="btn btn-primary" onclick="adminLoadCatalog()">加载文档目录</button>
                <button class="btn" onclick="adminLoadItems()">加载条目</button>
                <select id="admin-data-type" class="select" style="width:auto;">
                    <option value="">全部类型</option>
                    <option value="doc">doc 指南</option>
                    <option value="rec">rec 推荐条目</option>
                    <option value="drug">drug 药品说明书</option>
                    <option value="term">term 术语</option>
                </select>
                <button class="btn" onclick="adminSyncCatalog()">从 ES 重建目录</button>
            </div>
        </div>

        <div id="admin-content" style="margin-top:0.75rem;"></div>
    `;

    adminRefreshTokenHint();
});

// ===== Token 管理 =====
function adminToken() {
    return localStorage.getItem('medicalAdminToken') || '';
}

window.adminSaveToken = function () {
    const val = (document.getElementById('admin-token').value || '').trim();
    localStorage.setItem('medicalAdminToken', val);
    adminRefreshTokenHint();
};

function adminRefreshTokenHint() {
    const hint = document.getElementById('admin-token-hint');
    const input = document.getElementById('admin-token');
    if (!hint || !input) return;
    const t = adminToken();
    if (t) {
        hint.textContent = '已保存令牌（已按浏览器本地存储保留）';
        input.value = t;
    } else {
        hint.textContent = '尚未保存令牌，管理操作将返回 401/403';
    }
}

// 管理接口请求（带 Authorization 头）
async function adminGet(path, params) {
    const url = new URL(API_BASE + path, window.location.origin);
    if (params) {
        Object.entries(params).forEach(([k, v]) => {
            if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
        });
    }
    const resp = await fetch(url.toString(), {
        headers: { 'Authorization': 'Bearer ' + adminToken() }
    });
    if (resp.status === 401 || resp.status === 403) {
        throw new Error('认证失败：请检查管理员令牌');
    }
    if (!resp.ok) throw new Error('API错误: ' + resp.status);
    return resp.json();
}

async function adminPost(path, body) {
    const resp = await fetch(API_BASE + path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + adminToken() },
        body: body ? JSON.stringify(body) : undefined
    });
    if (resp.status === 401 || resp.status === 403) {
        throw new Error('认证失败：请检查管理员令牌');
    }
    if (!resp.ok) throw new Error('API错误: ' + resp.status);
    return resp.json();
}

// ===== 文档目录 =====
window.adminLoadCatalog = function () {
    const box = document.getElementById('admin-content');
    showLoading(box);
    adminGet('/admin/catalog').then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '加载失败'); return; }
        const docs = resp.data.docs || [];
        const stats = resp.data.statistics || {};
        let html = '<div class="card" style="padding:1rem;">';
        html += '<div style="font-weight:600;margin-bottom:0.5rem;">文档目录（' + docs.length + ' 篇）'
              + '<span style="font-weight:400;color:var(--color-text-muted);font-size:0.8125rem;">｜总条目 ' + (stats.total_items || 0) + '</span></div>';
        if (!docs.length) {
            html += '<div class="alert alert-info">目录为空（可先运行 ingest.py 入库）</div>';
        } else {
            html += '<table class="markdown-table" style="border-collapse:collapse;width:100%;font-size:0.8125rem;">';
            html += '<tr>' + ['文档 ID', '标题', '类型', '癌种', '条目数', '状态'].map(function (h) {
                return '<th style="border:1px solid var(--color-border);padding:6px 10px;text-align:left;background:var(--color-bg);">' + h + '</th>';
            }).join('') + '</tr>';
            docs.forEach(function (d) {
                html += '<tr>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + escapeHtml(d.doc_id || '') + '</td>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + escapeHtml(d.title || '') + '</td>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + escapeHtml(d.doc_type || '') + '</td>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + escapeHtml((d.cancer_types || []).join('、')) + '</td>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + (d.item_count || 0) + '</td>';
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + escapeHtml(d.status || '') + '</td>';
                html += '</tr>';
            });
            html += '</table>';
        }
        html += '</div>';
        box.innerHTML = html;
    }).catch(function (err) { showError(box, err.message); });
};

// ===== 条目列表 =====
window.adminLoadItems = function () {
    const box = document.getElementById('admin-content');
    const dataType = document.getElementById('admin-data-type').value;
    showLoading(box);
    adminGet('/admin/items', { data_type: dataType, page_size: 100 }).then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '加载失败'); return; }
        const items = (resp.data && resp.data.items) || [];
        let html = '<div class="card" style="padding:1rem;">';
        html += '<div style="font-weight:600;margin-bottom:0.5rem;">条目（' + items.length + ' 条'
              + (dataType ? '，类型 ' + escapeHtml(dataType) : '') + '）</div>';
        if (!items.length) {
            html += '<div class="alert alert-info">暂无条目</div>';
        } else {
            html += '<div style="display:flex;flex-direction:column;gap:0.375rem;max-height:520px;overflow-y:auto;">';
            items.forEach(function (it) {
                const id = it._id || it.doc_id || it.rec_id || it.drug_id || it.term_id || '';
                const title = it.title || it.canonical || it.generic_name || it.breadcrumb || '';
                html += '<div style="padding:0.4rem 0.6rem;border:1px solid var(--color-border);border-radius:6px;font-size:0.8125rem;display:flex;justify-content:space-between;gap:0.5rem;">';
                html += '<span>' + escapeHtml(id) + '</span>';
                html += '<span style="color:var(--color-text-muted);">' + escapeHtml((it.data_type || '') + ' · ' + title) + '</span>';
                html += '</div>';
            });
            html += '</div>';
        }
        html += '</div>';
        box.innerHTML = html;
    }).catch(function (err) { showError(box, err.message); });
};

// ===== 目录重建 =====
window.adminSyncCatalog = function () {
    const box = document.getElementById('admin-content');
    showLoading(box);
    adminPost('/admin/sync').then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '重建失败'); return; }
        box.innerHTML = '<div class="alert alert-success">目录已从 ES 重建完成：' +
            escapeHtml(JSON.stringify(resp.data.statistics || {})) + '</div>';
    }).catch(function (err) { showError(box, err.message); });
};
