/**
 * 癌种对比分析页面（医疗，BE-08）
 *
 * 轻量对比：分别检索两个癌种在固定临床维度（症状 / 病理分子 / 诊断 / 治疗 / 预后）上的
 * 推荐条目，按维度聚合展示；可选生成 AI 深度对比报告（流式）。
 */
registerPage('compare', function (container) {
    container.innerHTML = `
        <h1 class="page-title">癌种对比</h1>
        <p class="page-desc">选择两个癌种，按临床维度对照其循证推荐要点；可进一步生成 AI 深度对比报告。</p>
        <hr class="divider">

        <!-- 选择面板 -->
        <div style="margin-bottom:1.5rem;">
            <div class="grid-2" style="margin-bottom:0.75rem;">
                <div>
                    <label style="font-size:0.8125rem;font-weight:600;color:var(--color-text-secondary);display:block;margin-bottom:0.25rem;">癌种 A</label>
                    <select id="cmp-cancer-a" class="select"></select>
                </div>
                <div>
                    <label style="font-size:0.8125rem;font-weight:600;color:var(--color-text-secondary);display:block;margin-bottom:0.25rem;">癌种 B</label>
                    <select id="cmp-cancer-b" class="select"></select>
                </div>
            </div>
            <div class="grid-2" style="margin-bottom:0.75rem;">
                <div>
                    <label style="font-size:0.8125rem;font-weight:600;color:var(--color-text-secondary);display:block;margin-bottom:0.25rem;">对比主题（可选）</label>
                    <input type="text" id="cmp-topic" class="input" placeholder="例如：免疫治疗、靶向治疗">
                </div>
                <div>
                    <label style="font-size:0.8125rem;font-weight:600;color:var(--color-text-secondary);display:block;margin-bottom:0.25rem;">每维度每癌种条目数: <span id="cmp-topk-val">5</span></label>
                    <input type="range" id="cmp-topk" min="1" max="20" value="5" style="width:100%;">
                </div>
            </div>
            <button id="cmp-run" class="btn btn-primary">开始对比</button>
        </div>

        <!-- 状态提示 -->
        <div id="cmp-status"></div>

        <!-- 结果区 -->
        <div id="cmp-result"></div>
    `;

    // 加载癌种（受控词表，value=code）
    api.get('/search/cancer_types').then(function (data) {
        const list = (data && data.data) || [];
        const selA = document.getElementById('cmp-cancer-a');
        const selB = document.getElementById('cmp-cancer-b');
        list.forEach(function (c) {
            const label = c.label_zh || c.code;
            [selA, selB].forEach(function (sel) {
                const opt = document.createElement('option');
                opt.value = c.code;
                opt.textContent = label;
                sel.appendChild(opt);
            });
        });
        if (list.length > 1) selB.selectedIndex = 1;
    }).catch(function () {});

    document.getElementById('cmp-topk').addEventListener('input', function () {
        document.getElementById('cmp-topk-val').textContent = this.value;
    });
    document.getElementById('cmp-run').addEventListener('click', runCompare);
});

function runCompare() {
    const cancerA = document.getElementById('cmp-cancer-a').value;
    const cancerB = document.getElementById('cmp-cancer-b').value;
    const topic = document.getElementById('cmp-topic').value.trim();
    const topK = parseInt(document.getElementById('cmp-topk').value);

    if (!cancerA || !cancerB) { alert('请选择两个癌种'); return; }
    if (cancerA === cancerB) { alert('请选择不同的癌种'); return; }

    const statusEl = document.getElementById('cmp-status');
    const resultEl = document.getElementById('cmp-result');
    statusEl.innerHTML = '<div class="alert alert-info">正在检索两癌种推荐条目...</div>';
    resultEl.innerHTML = '<div class="loading"><div class="spinner"></div>对比中...</div>';

    const params = { cancer_type_a: cancerA, cancer_type_b: cancerB, top_k: topK };
    if (topic) params.topic = topic;

    api.get('/compare', params).then(function (data) {
        if (!data || !data.success) {
            statusEl.innerHTML = '<div class="alert alert-error">对比失败：' + (data ? data.message : '未知错误') + '</div>';
            resultEl.innerHTML = '';
            return;
        }
        statusEl.innerHTML = '<div class="alert alert-success">对比完成' + (data.data._cache_hit ? '（缓存命中）' : '') + '</div>';
        window._compareLastResult = data.data;
        renderCompareResult(resultEl, data.data);
    }).catch(function (err) {
        statusEl.innerHTML = '<div class="alert alert-error">请求失败：' + err.message + '</div>';
        resultEl.innerHTML = '';
    });
}

const CMP_EVIDENCE_LABELS = { high: '高', moderate: '中', low: '低', very_low: '极低' };
const CMP_STRENGTH_LABELS = { strong: '强', weak: '弱', not_graded: '未分级' };

function renderCompareResult(container, r) {
    const nameA = r.cancer_name_a || r.cancer_type_a || '癌种A';
    const nameB = r.cancer_name_b || r.cancer_type_b || '癌种B';
    const resultsA = r.results_a || [];
    const resultsB = r.results_b || [];

    let html = '';

    // 自动总结
    if (r.auto_summary) {
        html += '<div class="card" style="padding:0.875rem 1rem;margin-bottom:1rem;">';
        html += '<div style="font-size:0.875rem;line-height:1.75;color:var(--color-text-secondary);">' + escapeHtml(r.auto_summary) + '</div>';
        html += '</div>';
    }

    // 逐维度对照表
    html += '<h2 class="section-title">逐维度对照</h2>';
    html += '<div style="overflow-x:auto;">';
    html += '<table style="width:100%;border-collapse:collapse;font-size:0.8125rem;">';
    html += '<thead><tr>';
    html += '<th style="border:1px solid var(--color-border);padding:8px 10px;text-align:left;background:var(--color-bg);width:15%;">维度</th>';
    html += '<th style="border:1px solid var(--color-border);padding:8px 10px;text-align:left;background:var(--color-bg);width:42.5%;">' + escapeHtml(nameA) + '</th>';
    html += '<th style="border:1px solid var(--color-border);padding:8px 10px;text-align:left;background:var(--color-bg);width:42.5%;">' + escapeHtml(nameB) + '</th>';
    html += '</tr></thead><tbody>';

    const count = Math.max(resultsA.length, resultsB.length);
    for (let i = 0; i < count; i++) {
        const ba = resultsA[i] || {};
        const bb = resultsB[i] || {};
        const label = ba.dimension_label || bb.dimension_label || '';
        html += '<tr>';
        html += '<td style="border:1px solid var(--color-border);padding:8px 10px;vertical-align:top;font-weight:600;color:var(--color-text);">' + escapeHtml(label) + '</td>';
        html += '<td style="border:1px solid var(--color-border);padding:8px 10px;vertical-align:top;">' + renderDimensionItems(ba.items) + '</td>';
        html += '<td style="border:1px solid var(--color-border);padding:8px 10px;vertical-align:top;">' + renderDimensionItems(bb.items) + '</td>';
        html += '</tr>';
    }
    html += '</tbody></table></div>';

    // AI 深度对比
    html += '<hr class="divider" style="margin-top:2rem;">';
    html += '<h2 class="section-title">AI 深度对比报告</h2>';
    html += '<div style="display:flex;gap:0.5rem;align-items:center;margin-bottom:0.75rem;">';
    html += '<button id="cmp-ai-btn" class="btn btn-primary">生成 AI 深度对比报告</button>';
    html += '<span style="font-size:0.75rem;color:var(--color-text-muted);">基于两癌种检索到的推荐条目生成，需调用 AI（约 20-40 秒）</span>';
    html += '</div>';
    html += '<div id="cmp-ai-result" class="card markdown-body" style="padding:1rem;display:none;"></div>';

    container.innerHTML = html;

    const aiBtn = document.getElementById('cmp-ai-btn');
    if (aiBtn) aiBtn.addEventListener('click', function () { runDeepAnalysis(r); });
}

function renderDimensionItems(items) {
    if (!items || !items.length) {
        return '<span style="color:var(--color-text-muted);">未检索到相关推荐</span>';
    }
    let html = '';
    items.forEach(function (it, idx) {
        html += '<div style="' + (idx ? 'margin-top:0.625rem;padding-top:0.625rem;border-top:1px dashed var(--color-border);' : '') + '">';
        // 徽标
        const badges = [];
        if (it.evidence_level) badges.push('<span class="badge badge-info">证据 ' + escapeHtml(CMP_EVIDENCE_LABELS[it.evidence_level] || it.evidence_level) + '</span>');
        if (it.rec_strength) badges.push('<span class="badge badge-warning">推荐 ' + escapeHtml(CMP_STRENGTH_LABELS[it.rec_strength] || it.rec_strength) + '</span>');
        if (badges.length) html += '<div style="display:flex;gap:0.25rem;flex-wrap:wrap;margin-bottom:0.25rem;">' + badges.join('') + '</div>';
        // 溯源
        if (it.breadcrumb) html += '<div style="font-size:0.7rem;color:var(--color-text-muted);margin-bottom:0.2rem;">' + escapeHtml(it.breadcrumb) + '</div>';
        // 正文
        html += '<div style="line-height:1.6;color:var(--color-text-secondary);">' + escapeHtml(it.content || '') + '</div>';
        html += '</div>';
    });
    return html;
}

function runDeepAnalysis(r) {
    const aiResult = document.getElementById('cmp-ai-result');
    const btn = document.getElementById('cmp-ai-btn');
    if (!aiResult) return;

    // 组装两癌种上下文（各维度条目正文拼接）
    const contextA = buildContext(r.results_a || []);
    const contextB = buildContext(r.results_b || []);

    aiResult.style.display = 'block';
    aiResult.innerHTML = '<div class="loading"><div class="spinner"></div>AI 生成中...</div>';
    if (btn) btn.disabled = true;

    const payload = {
        cancer_type_a: r.cancer_type_a,
        cancer_type_b: r.cancer_type_b,
        topic: r.topic || '',
        context_a: contextA,
        context_b: contextB
    };

    let buffer = '';
    api.streamPost('/compare/deep-analysis', payload,
        function (chunk) {
            if (chunk.type === 'chunk') {
                buffer += chunk.data || '';
                aiResult.innerHTML = renderMarkdown(buffer);
            } else if (chunk.type === 'error') {
                aiResult.innerHTML = '<div class="alert alert-error">' + escapeHtml(chunk.data || 'AI 分析失败') + '</div>';
            }
        },
        function () {
            if (btn) btn.disabled = false;
            // 回写缓存（异步，失败不影响展示）
            api.post('/compare/cache-ai', {
                cancer_type_a: r.cancer_type_a,
                cancer_type_b: r.cancer_type_b,
                topic: r.topic || '',
                ai_analysis: buffer
            }).catch(function () {});
        },
        function (err) {
            if (btn) btn.disabled = false;
            aiResult.innerHTML = '<div class="alert alert-error">AI 分析失败：' + escapeHtml(err) + '</div>';
        }
    );
}

function buildContext(dimensionBlocks) {
    const parts = [];
    dimensionBlocks.forEach(function (b) {
        const items = b.items || [];
        if (!items.length) return;
        parts.push('【' + (b.dimension_label || '') + '】');
        items.forEach(function (it) {
            parts.push('- ' + (it.content || ''));
        });
    });
    return parts.join('\n');
}
