/**
 * 病历质控页（NM-04）
 * 路由：#/qc
 * 功能：病历文本审查（评分 + 四类问题清单）+ 质控规则目录（B6）
 */
let _qcTab = 'review';
let _qcReport = null;

registerPage('qc', function (container) {
    _qcTab = 'review';
    _qcReport = null;

    container.innerHTML = `
        <h1 class="page-title">病历质控</h1>
        <p class="page-desc">
            对病历文本做完整性 / 一致性 / 规范性 / 时限性四类质控，输出评分、问题清单与修改建议。
        </p>
        <div style="display:flex;gap:0.5rem;margin-bottom:1rem;">
            <button class="btn btn-primary btn-sm" data-qc-tab="review">病历审查</button>
            <button class="btn btn-secondary btn-sm" data-qc-tab="rules">质控规则</button>
        </div>
        <div id="qc-body"></div>
    `;

    container.querySelectorAll('button[data-qc-tab]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            _qcTab = btn.dataset.qcTab;
            container.querySelectorAll('button[data-qc-tab]').forEach(function (b) {
                b.className = 'btn btn-sm ' + (b.dataset.qcTab === _qcTab ? 'btn-primary' : 'btn-secondary');
            });
            if (_qcTab === 'review') renderQcReview();
            else renderQcRules();
        });
    });

    renderQcReview();
});

// ===== 病历审查 =====
function renderQcReview() {
    const body = document.getElementById('qc-body');
    body.innerHTML = `
        <div class="card" style="padding:1rem;margin-bottom:1rem;">
            <div class="card-title">病历文本</div>
            <textarea id="qc-text" class="textarea" rows="10" style="width:100%;font-family:var(--font-sans);"
                placeholder="粘贴或输入病历文本。示例结构：&#10;主诉：咳嗽两周&#10;现病史：……&#10;既往史：……&#10;性别：男&#10;诊断：肺CA"></textarea>
            <div style="margin-top:0.5rem;display:flex;gap:0.5rem;">
                <button id="qc-submit" class="btn btn-primary">提交质控</button>
                <span style="align-self:center;font-size:0.75rem;color:var(--color-text-muted);">质控结果供病历质量改进参考，最终以人工复核为准。</span>
            </div>
        </div>
        <div id="qc-result"></div>
    `;
    document.getElementById('qc-submit').addEventListener('click', submitQcReview);
    if (_qcReport) renderQcReport(_qcReport);
}

function submitQcReview() {
    const text = (document.getElementById('qc-text').value || '').trim();
    const box = document.getElementById('qc-result');
    if (!text) { alert('请输入病历文本'); return; }

    showLoading(box);
    api.post('/qc/review', { record_text: text }).then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '审查失败'); return; }
        _qcReport = resp.data;
        renderQcReport(_qcReport);
    }).catch(function (err) { showError(box, err.message); });
}

function renderQcReport(r) {
    const box = document.getElementById('qc-result');
    let html = '';

    if (r.degraded && r.note) {
        html += '<div class="alert alert-warning">' + escapeHtml(r.note) + '</div>';
    }

    // 评分卡
    const gradeColor = { '优': 'badge-success', '良': 'badge-info', '中': 'badge-warning', '差': 'badge-warning' }[r.grade] || 'badge-muted';
    html += '<div class="card" style="padding:1rem;margin-bottom:1rem;">';
    html += '<div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap;">';
    html += '<div><span style="font-size:2rem;font-weight:700;">' + (r.score != null ? r.score : '—') + '</span><span style="color:var(--color-text-muted);"> 分</span></div>';
    html += '<span class="badge ' + gradeColor + '">等级：' + escapeHtml(r.grade || '—') + '</span>';
    html += '<span style="font-size:0.8125rem;color:var(--color-text-muted);">问题 ' + (r.issue_count || 0) + ' 项</span>';
    html += '<span style="font-size:0.8125rem;color:var(--color-text-muted);">校验规则 ' + (r.rule_count || 0) + ' 条</span>';
    html += '</div>';

    // 严重度 / 类别分布
    const sev = r.severity_stats || {};
    html += '<div style="margin-top:0.75rem;font-size:0.8125rem;">';
    html += '<span class="badge badge-warning">高 ' + (sev.high || 0) + '</span> ';
    html += '<span class="badge badge-info">中 ' + (sev.medium || 0) + '</span> ';
    html += '<span class="badge badge-muted">低 ' + (sev.low || 0) + '</span>';
    html += '</div>';
    html += '</div>';

    // 问题清单（按类别分组）
    if (!r.issues || !r.issues.length) {
        html += '<div class="alert alert-success">未检出问题。</div>';
    } else {
        const byCat = {};
        r.issues.forEach(function (it) {
            const k = it.category_label || it.category || '其他';
            (byCat[k] = byCat[k] || []).push(it);
        });
        Object.keys(byCat).forEach(function (cat) {
            html += '<div class="card" style="padding:1rem;margin-bottom:0.75rem;">';
            html += '<div class="card-title">' + escapeHtml(cat) + '（' + byCat[cat].length + '）</div>';
            byCat[cat].forEach(function (it) {
                const sb = it.severity === 'high' ? 'badge-warning' : (it.severity === 'medium' ? 'badge-info' : 'badge-muted');
                html += '<div style="font-size:0.8125rem;margin-bottom:0.5rem;padding:0.5rem;background:var(--color-bg);border-radius:6px;">';
                html += '<div><span class="badge ' + sb + '">' + escapeHtml(it.severity_label || it.severity) + '</span> ';
                html += '<strong>' + escapeHtml(it.field_target || '') + '</strong>：' + escapeHtml(it.message || '') + '</div>';
                if (it.evidence) html += '<div style="color:var(--color-text-muted);margin-top:0.25rem;">原文片段：' + escapeHtml(it.evidence) + '</div>';
                html += '<div style="color:var(--color-text-muted);font-size:0.75rem;margin-top:0.25rem;">规则：' + escapeHtml(it.rule_id || '') + '</div>';
                html += '</div>';
            });
            html += '</div>';
        });
    }

    html += '<div class="alert alert-warning" style="margin-top:0.75rem;">' + escapeHtml(r.disclaimer || '') + '</div>';
    box.innerHTML = html;
}

// ===== 规则目录 =====
function renderQcRules() {
    const body = document.getElementById('qc-body');
    showLoading(body);
    api.get('/qc/rules').then(function (resp) {
        if (!resp || !resp.success) { showError(body, (resp && resp.message) || '加载失败'); return; }
        const d = resp.data;
        let html = '';
        if (d.degraded && d.note) html += '<div class="alert alert-warning">' + escapeHtml(d.note) + '</div>';
        html += '<div style="font-size:0.875rem;color:var(--color-text-muted);margin-bottom:0.5rem;">共 ' + (d.total || 0) + ' 条质控规则</div>';

        if (d.categories && d.categories.length) {
            html += '<div style="margin-bottom:0.75rem;">';
            d.categories.forEach(function (c) {
                html += '<span class="badge badge-muted" style="margin-right:0.375rem;">' + escapeHtml(c.label) + ' (' + c.count + ')</span>';
            });
            html += '</div>';
        }

        if (!d.items || !d.items.length) {
            if (!d.degraded) html += emptyState('暂无规则');
        } else {
            d.items.forEach(function (r) {
                const sb = r.severity === 'high' ? 'badge-warning' : (r.severity === 'medium' ? 'badge-info' : 'badge-muted');
                html += '<div class="card" style="padding:0.875rem 1rem;margin-bottom:0.5rem;">';
                html += '<div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;margin-bottom:0.375rem;">';
                html += '<span class="badge badge-muted">' + escapeHtml(r.rule_id) + '</span> ';
                html += '<span class="badge badge-info">' + escapeHtml(r.category_label || r.category) + '</span> ';
                html += '<span class="badge ' + sb + '">' + escapeHtml(r.severity_label || r.severity) + '</span> ';
                if (r.field_target) html += '<span style="font-size:0.75rem;color:var(--color-text-muted);">字段：' + escapeHtml(r.field_target) + '</span>';
                html += '</div>';
                if (r.logic) html += '<div style="font-size:0.8125rem;line-height:1.6;color:var(--color-text-secondary);">' + escapeHtml(r.logic) + '</div>';
                if (r.reference) html += '<div style="font-size:0.75rem;color:var(--color-text-muted);margin-top:0.25rem;">依据：' + escapeHtml(r.reference) + '</div>';
                html += '</div>';
            });
        }
        body.innerHTML = html;
    }).catch(function (err) { showError(body, err.message); });
}
