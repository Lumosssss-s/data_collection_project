/**
 * 报告智能解析页（NM-05，演示级）
 * 路由：#/report
 * 边界：仅报告文本解析，不做影像判读、不做 OCR
 */
registerPage('report', function (container) {
    container.innerHTML = `
        <h1 class="page-title">报告智能解析</h1>
        <p class="page-subtitle" style="color:var(--color-text-muted);margin-bottom:1rem;">
            对报告<b>文本</b>做结构化整理：抽取部位 / 大小 / 密度 / 边界 / 淋巴结，提取关键征象，
            给出循证随访建议，并与同一患者上次解析对比。仅文本解析，不做影像判读与 OCR。
        </p>

        <div class="card" style="padding:1rem;margin-bottom:1rem;">
            <div style="font-weight:600;margin-bottom:0.5rem;">报告文本</div>
            <textarea id="rp-text" class="textarea" rows="8" style="width:100%;"
                placeholder="粘贴报告文本。示例：&#10;右肺上叶见磨玻璃结节，大小约 12mm×10mm，边界欠清，可见分叶；纵隔未见肿大淋巴结。"></textarea>
            <div style="margin-top:0.5rem;display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap;">
                <input id="rp-patient" class="input" style="width:180px;" placeholder="患者 ID（可选，用于历次对比）">
                <button id="rp-submit" class="btn btn-primary">解析报告</button>
                <span style="font-size:0.75rem;color:var(--color-text-muted);">本解析不构成影像判读与诊断结论。</span>
            </div>
        </div>

        <div id="rp-result"></div>
    `;

    document.getElementById('rp-submit').addEventListener('click', submitReportParse);
});

function submitReportParse() {
    const text = (document.getElementById('rp-text').value || '').trim();
    const patientId = (document.getElementById('rp-patient').value || '').trim();
    const box = document.getElementById('rp-result');
    if (!text) { alert('请输入报告文本'); return; }

    showLoading(box);
    api.post('/report/parse', { text: text, patient_id: patientId }).then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '解析失败'); return; }
        renderReportResult(box, resp.data);
    }).catch(function (err) { showError(box, err.message); });
}

function renderReportResult(box, r) {
    let html = '';

    if (r.degraded && r.note) {
        html += '<div class="alert alert-warning">' + escapeHtml(r.note) + '</div>';
    }

    // 结构化字段
    html += '<div class="card" style="padding:1rem;margin-bottom:0.75rem;">';
    html += '<div style="font-weight:600;margin-bottom:0.5rem;">结构化字段（' + ((r.findings || []).length) + ' 处病灶）</div>';
    if (!r.findings || !r.findings.length) {
        html += '<div style="font-size:0.8125rem;color:var(--color-text-muted);">未抽取到结构化病灶描述。</div>';
    } else {
        html += '<table style="width:100%;border-collapse:collapse;font-size:0.8125rem;">';
        html += '<tr>' + ['部位', '大小', '密度', '边界', '淋巴结'].map(function (h) {
            return '<th style="border:1px solid var(--color-border);padding:6px 10px;text-align:left;background:var(--color-bg);">' + h + '</th>';
        }).join('') + '</tr>';
        r.findings.forEach(function (f) {
            html += '<tr>';
            ['site', 'size', 'density', 'margin', 'lymph_nodes'].forEach(function (k) {
                html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + escapeHtml(f[k] || '—') + '</td>';
            });
            html += '</tr>';
        });
        html += '</table>';
    }
    html += '</div>';

    // 关键征象
    if (r.key_signs && r.key_signs.length) {
        html += '<div class="card" style="padding:1rem;margin-bottom:0.75rem;">';
        html += '<div style="font-weight:600;margin-bottom:0.5rem;">关键征象</div>';
        r.key_signs.forEach(function (s) {
            html += '<span class="badge badge-warning" style="margin:0 0.25rem 0.25rem 0;">' + escapeHtml(s) + '</span>';
        });
        html += '</div>';
    }

    // 报告印象
    if (r.impression) {
        html += '<div class="card" style="padding:1rem;margin-bottom:0.75rem;">';
        html += '<div style="font-weight:600;margin-bottom:0.5rem;">报告印象（原报告复述）</div>';
        html += '<div style="font-size:0.875rem;line-height:1.7;">' + escapeHtml(r.impression) + '</div>';
        html += '</div>';
    }

    // 随访建议（循证）
    html += '<div class="card" style="padding:1rem;margin-bottom:0.75rem;">';
    html += '<div style="font-weight:600;margin-bottom:0.5rem;">循证随访建议</div>';
    if (r.followup_suggestions && r.followup_suggestions.length) {
        r.followup_suggestions.forEach(function (s) {
            html += '<div style="font-size:0.8125rem;margin-bottom:0.625rem;padding:0.5rem;background:var(--color-bg);border-radius:6px;">';
            html += '<div style="line-height:1.6;">' + escapeHtml(s.text) + '</div>';
            html += '<div style="margin-top:0.375rem;color:var(--color-text-muted);font-size:0.75rem;">';
            html += '来源：' + escapeHtml(s.source || '—');
            if (s.breadcrumb) html += ' · ' + escapeHtml(s.breadcrumb);
            html += '</div><div style="margin-top:0.25rem;">';
            if (s.evidence_level) html += '<span class="badge badge-info">证据 ' + escapeHtml(s.evidence_level) + '</span> ';
            if (s.rec_strength) html += '<span class="badge badge-muted">推荐 ' + escapeHtml(s.rec_strength) + '</span>';
            html += '</div></div>';
        });
    } else {
        html += '<div style="font-size:0.8125rem;color:var(--color-text-muted);">暂无匹配的循证随访条目。</div>';
    }
    html += '</div>';

    // 历次对比
    if (r.diff_prev) {
        const d = r.diff_prev;
        html += '<div class="card" style="padding:1rem;margin-bottom:0.75rem;">';
        html += '<div style="font-weight:600;margin-bottom:0.5rem;">历次对比</div>';
        html += '<div style="font-size:0.8125rem;margin-bottom:0.5rem;">上次 ' + d.previous_count + ' 处 → 本次 ' + d.current_count + ' 处（按部位对比）</div>';
        if (d.size_changes && d.size_changes.length) {
            d.size_changes.forEach(function (c) {
                html += '<div style="font-size:0.8125rem;margin-bottom:0.375rem;"><span class="badge badge-warning">大小变化</span> '
                    + escapeHtml(c.site) + '：' + escapeHtml(c.before) + ' → ' + escapeHtml(c.after) + '</div>';
            });
        }
        if (d.added && d.added.length) html += '<div style="font-size:0.8125rem;margin-bottom:0.25rem;"><span class="badge badge-warning">新增</span> ' + escapeHtml(d.added.join('；')) + '</div>';
        if (d.removed && d.removed.length) html += '<div style="font-size:0.8125rem;margin-bottom:0.25rem;"><span class="badge badge-muted">消失</span> ' + escapeHtml(d.removed.join('；')) + '</div>';
        if (d.unchanged && d.unchanged.length) html += '<div style="font-size:0.8125rem;"><span class="badge badge-info">无变化</span> ' + escapeHtml(d.unchanged.join('；')) + '</div>';
        html += '</div>';
    }

    html += '<div class="alert alert-warning" style="margin-top:0.75rem;">' + escapeHtml(r.disclaimer || '') + '</div>';
    box.innerHTML = html;
}
