/**
 * 疾病详情页（NM-01 / FE-08）
 * 路由：#/disease/{disease_id}
 * 功能：14 section 展示 + 专业版/患者版双版本切换 + 图谱关联 + 免责声明
 */
registerPage('disease', function (container) {
    const hash = window.location.hash;
    const diseaseId = decodeURIComponent(hash.replace('#/disease/', ''));

    if (!diseaseId) {
        container.innerHTML = '<div class="alert alert-warning">未选择疾病，请先从疾病知识库选择</div>'
            + '<button class="btn btn-secondary" onclick="goBackToDiseases()">返回疾病知识库</button>';
        return;
    }

    let version = 'pro';
    container.innerHTML = '<div id="disease-detail-body"></div>';
    const body = document.getElementById('disease-detail-body');

    function load() {
        showLoading(body);
        api.get('/diseases/' + encodeURIComponent(diseaseId), { version: version }).then(function (resp) {
            if (!resp || !resp.success) {
                showError(body, (resp && resp.message) || '加载失败（疾病档案可能尚未入库）');
                body.innerHTML += '<button class="btn btn-secondary" onclick="goBackToDiseases()">返回疾病知识库</button>';
                return;
            }
            renderDiseaseDetail(body, resp.data, version, function (v) {
                version = v;
                load();
            });
        }).catch(function (err) { showError(body, err.message); });
    }
    load();
});

function goBackToDiseases() {
    window.location.hash = '#/diseases';
}

function renderDiseaseDetail(container, d, version, onSwitch) {
    const name = d.name_canonical || d.disease_id || '未命名疾病';
    let html = '';

    html += '<button class="btn btn-ghost btn-sm" id="disease-back-btn" style="margin-bottom:0.5rem;">← 返回疾病知识库</button>';
    html += '<h1 class="page-title">' + escapeHtml(name) + '</h1>';

    if (d.name_en) html += '<p style="color:var(--color-text-muted);margin:-0.5rem 0 0.75rem;">' + escapeHtml(d.name_en) + '</p>';

    // 元信息
    html += '<div class="card" style="padding:0.75rem 1rem;margin-bottom:1rem;">';
    html += '<div style="display:flex;flex-wrap:wrap;gap:0.5rem;align-items:center;">';
    if (d.category_label) html += '<span class="badge badge-info">' + escapeHtml(d.category_label) + '</span>';
    if (d.cancer_type) html += '<span class="badge badge-muted">' + escapeHtml(d.cancer_type) + '</span>';
    if (d.icd10) html += '<span class="badge badge-muted">ICD-10: ' + escapeHtml(d.icd10) + '</span>';
    if (d.icd_o3) html += '<span class="badge badge-muted">ICD-O-3: ' + escapeHtml(d.icd_o3) + '</span>';
    html += '</div>';
    if (d.departments && d.departments.length) {
        html += '<div style="font-size:0.8125rem;color:var(--color-text-secondary);margin-top:0.5rem;">就诊科室：' + escapeHtml(d.departments.join('、')) + '</div>';
    }
    if (d.synonyms && d.synonyms.length) {
        html += '<div style="font-size:0.8125rem;color:var(--color-text-muted);margin-top:0.25rem;">别名：' + escapeHtml(d.synonyms.join('、')) + '</div>';
    }
    html += '</div>';

    // 版本切换
    html += '<div style="display:flex;gap:0.5rem;margin-bottom:1rem;">';
    html += '<button class="btn ' + (version === 'pro' ? 'btn-primary' : 'btn-secondary') + ' btn-sm" data-ver="pro">专业版</button>';
    html += '<button class="btn ' + (version === 'patient' ? 'btn-primary' : 'btn-secondary') + ' btn-sm" data-ver="patient">患者版</button>';
    html += '<span style="align-self:center;font-size:0.75rem;color:var(--color-text-muted);">'
        + (version === 'patient' ? '患者版：通俗表述，句均 ≤40 字' : '专业版：面向临床的结构化描述') + '</span>';
    html += '</div>';

    if (!d.sections || !d.sections.length) {
        html += '<div class="alert alert-info">该疾病暂无可用内容（章节待入库）。</div>';
    } else {
        let lastGroup = '';
        d.sections.forEach(function (s) {
            if (s.group && s.group !== lastGroup) {
                html += '<h2 style="font-size:1rem;margin:1rem 0 0.5rem;color:var(--color-text-secondary);">' + escapeHtml(s.group) + '</h2>';
                lastGroup = s.group;
            }
            html += '<div class="card" style="padding:0.875rem 1rem;margin-bottom:0.5rem;">';
            html += '<div style="font-weight:600;margin-bottom:0.375rem;">' + escapeHtml(s.label) + '</div>';
            html += '<div style="font-size:0.875rem;line-height:1.7;color:var(--color-text-secondary);white-space:pre-wrap;">' + escapeHtml(s.text) + '</div>';
            html += '</div>';
        });
    }

    // 图谱关联
    const links = d.links || {};
    const linkKeys = Object.keys(links).filter(function (k) { return links[k] && (!Array.isArray(links[k]) || links[k].length); });
    if (linkKeys.length) {
        html += '<h2 style="font-size:1rem;margin:1rem 0 0.5rem;color:var(--color-text-secondary);">图谱关联</h2>';
        html += '<div class="card" style="padding:0.875rem 1rem;margin-bottom:0.5rem;">';
        linkKeys.forEach(function (k) {
            const v = Array.isArray(links[k]) ? links[k].join('、') : String(links[k]);
            html += '<div style="font-size:0.8125rem;margin-bottom:0.25rem;"><strong>' + escapeHtml(k) + '</strong>：' + escapeHtml(v) + '</div>';
        });
        html += '</div>';
    }

    // 来源
    if (d.sources && d.sources.length) {
        html += '<div style="font-size:0.75rem;color:var(--color-text-muted);margin-top:0.75rem;">来源：' + escapeHtml(d.sources.join('；')) + '</div>';
    }

    // 免责声明
    html += '<div class="alert alert-warning" style="margin-top:1rem;">' + escapeHtml(d.disclaimer || '') + '</div>';

    container.innerHTML = html;

    document.getElementById('disease-back-btn').addEventListener('click', goBackToDiseases);
    container.querySelectorAll('button[data-ver]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (btn.dataset.ver !== version) onSwitch(btn.dataset.ver);
        });
    });
}
