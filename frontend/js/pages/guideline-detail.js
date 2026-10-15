/**
 * 指南 / 条目详情页面（医疗）
 * 路由: #/guideline/{doc_id 或 item_id}
 *
 * 展示：
 *   - 指南速览卡（/search/doc/{doc_id}/summary：概要 / 核心推荐 / 证据特点 / 关键词）
 *   - 条目基本信息（/search/doc/{doc_id}）
 *   - 相关指南推荐（/search/doc/{doc_id}/similar → similar_guides）
 */
registerPage('guideline', function (container) {
    // 从 hash 中提取条目 ID
    const hash = window.location.hash;
    const lawId = hash.replace('#/guideline/', '');

    if (!lawId) {
        container.innerHTML = '<div class="alert alert-warning">未选择条目，请先从检索页面选择</div>';
        container.innerHTML += '<button class="btn btn-secondary" onclick="goBackToSearch()">返回检索</button>';
        return;
    }

    container.innerHTML = `
        <button class="btn btn-ghost btn-sm" onclick="goBackToSearch()" style="margin-bottom:1rem;">← 返回检索</button>
        <div id="guide-detail-content"></div>
    `;

    const contentEl = document.getElementById('guide-detail-content');
    showLoading(contentEl);

    // 并行获取条目详情、指南速览、相似指南
    Promise.all([
        api.get('/search/doc/' + lawId),
        api.get('/search/doc/' + lawId + '/summary').catch(function () { return null; }),
        api.get('/search/doc/' + lawId + '/similar', { top_k: 5 }).catch(function () { return null; })
    ]).then(function (results) {
        const itemData = results[0];
        const summaryData = results[1];
        const similarData = results[2];

        if (!itemData || !itemData.success) {
            showError(contentEl, '获取条目详情失败：' + (itemData ? itemData.message : '未知错误'));
            return;
        }

        renderGuideDetail(
            contentEl,
            itemData.data,
            summaryData && summaryData.success ? summaryData.data : null,
            similarData && similarData.success ? similarData.data : null
        );
    }).catch(function (err) {
        showError(contentEl, '请求失败：' + err.message);
    });
});

// 徽标文案
const DATA_TYPE_LABELS = { doc: '指南', rec: '推荐条目', drug: '药品说明书', term: '术语' };
const EVIDENCE_LABELS = { high: '高', moderate: '中', low: '低', very_low: '极低' };
const STRENGTH_LABELS = { strong: '强', weak: '弱', not_graded: '未分级' };

function renderGuideDetail(container, item, summary, similar) {
    const dataType = item.data_type || '';
    const title = item.title || item.doc_id || item.rec_id || '未命名条目';

    let html = '<h1 class="page-title">' + escapeHtml(title) + '</h1>';

    // ===== 元信息 =====
    const metaParts = [];
    if (dataType) metaParts.push(DATA_TYPE_LABELS[dataType] || dataType);
    const cancers = item.cancer_types || (item.cancer_type ? [item.cancer_type] : []);
    if (cancers.length) metaParts.push('癌种: ' + cancers.join('、'));
    if (item.issuer) metaParts.push('发布机构: ' + item.issuer);
    if (item.publish_date) metaParts.push('发布日期: ' + item.publish_date);
    if (item.version) metaParts.push('版本: ' + item.version);
    if (metaParts.length) {
        html += '<p style="font-size:0.875rem;color:var(--color-text-secondary);margin-bottom:0.5rem;">' + escapeHtml(metaParts.join(' | ')) + '</p>';
    }
    if (item.breadcrumb) {
        html += '<p style="font-size:0.8125rem;color:var(--color-text-muted);margin-bottom:0.5rem;">位置：' + escapeHtml(item.breadcrumb) + '</p>';
    }
    html += '<hr class="divider">';

    // ===== 指南速览卡（doc 类型且摘要可用）=====
    if (summary && (summary.overview || (summary.key_recommendations || []).length)) {
        html += '<h2 class="section-title">指南速览</h2>';
        html += '<div class="card" style="padding:1rem;margin-bottom:1rem;">';

        if (summary.overview) {
            html += '<div style="font-size:0.875rem;line-height:1.75;color:var(--color-text-secondary);margin-bottom:0.75rem;">' + escapeHtml(summary.overview) + '</div>';
        }
        const recs = summary.key_recommendations || [];
        if (recs.length) {
            html += '<div style="font-weight:600;font-size:0.8125rem;color:var(--color-text);margin-bottom:0.375rem;">核心推荐要点</div>';
            html += '<ul style="margin:0 0 0.75rem 1.1rem;padding:0;font-size:0.8125rem;line-height:1.7;color:var(--color-text-secondary);">';
            recs.forEach(function (r) { html += '<li>' + escapeHtml(r) + '</li>'; });
            html += '</ul>';
        }
        if (summary.evidence_notes) {
            html += '<div style="font-weight:600;font-size:0.8125rem;color:var(--color-text);margin-bottom:0.375rem;">证据特点</div>';
            html += '<div style="font-size:0.8125rem;line-height:1.7;color:var(--color-text-secondary);margin-bottom:0.75rem;">' + escapeHtml(summary.evidence_notes) + '</div>';
        }
        const kw = summary.keywords || {};
        const kwGroups = [];
        if ((kw.core || []).length) kwGroups.push('核心：' + kw.core.join('、'));
        if ((kw.cancers || []).length) kwGroups.push('癌种：' + kw.cancers.join('、'));
        if ((kw.scenarios || []).length) kwGroups.push('场景：' + kw.scenarios.join('、'));
        if (kwGroups.length) {
            html += '<div style="font-size:0.75rem;color:var(--color-text-muted);">' + escapeHtml(kwGroups.join('｜')) + '</div>';
        }
        if (summary.basic_info && summary.basic_info.item_count) {
            html += '<div style="font-size:0.75rem;color:var(--color-text-muted);margin-top:0.375rem;">收录推荐条目 ' + summary.basic_info.item_count + ' 条</div>';
        }
        html += '</div>';
    }

    // ===== 条目正文 =====
    if (dataType === 'rec') {
        html += '<h2 class="section-title">推荐条目</h2>';
        const bd = [];
        if (item.scenario) bd.push('场景: ' + item.scenario);
        if ((item.stage || []).length) bd.push('分期: ' + item.stage.join('、'));
        if ((item.biomarker || []).length) bd.push('标志物: ' + item.biomarker.join('、'));
        if (item.evidence_level) bd.push('证据等级: ' + (EVIDENCE_LABELS[item.evidence_level] || item.evidence_level));
        if (item.rec_strength) bd.push('推荐强度: ' + (STRENGTH_LABELS[item.rec_strength] || item.rec_strength));
        if (bd.length) {
            html += '<div style="font-size:0.75rem;color:var(--color-text-muted);margin-bottom:0.5rem;">' + escapeHtml(bd.join(' · ')) + '</div>';
        }
        html += '<div class="card" style="padding:1rem;">';
        html += '<div style="font-size:0.875rem;line-height:1.8;color:var(--color-text-secondary);white-space:pre-wrap;">' + escapeHtml(item.content || '（无正文）') + '</div>';
        if (item.verbatim && item.verbatim !== item.content) {
            html += '<div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px dashed var(--color-border);font-size:0.8125rem;color:var(--color-text-muted);">原文：' + escapeHtml(item.verbatim) + '</div>';
        }
        html += '</div>';
        html += '<hr class="divider">';
    } else if (item.content) {
        html += '<h2 class="section-title">内容</h2>';
        html += '<div class="card" style="padding:1rem;"><div style="font-size:0.875rem;line-height:1.8;color:var(--color-text-secondary);white-space:pre-wrap;">' + escapeHtml(item.content) + '</div></div>';
        html += '<hr class="divider">';
    }

    // ===== 相关指南推荐 =====
    html += '<h2 class="section-title">相关指南推荐</h2>';
    const guides = (similar && similar.similar_guides) || [];
    if (guides.length > 0) {
        html += '<p style="font-size:0.8125rem;color:var(--color-text-muted);margin-bottom:1rem;">基于主题与内容相似度，共 ' + (similar.total_found || guides.length) + ' 篇相关指南：</p>';
        guides.forEach(function (g) {
            const simPercent = Math.round((g.similarity || 0) * 100);
            let barColor = '#B91C1C';
            if (simPercent >= 75) barColor = '#15803D';
            else if (simPercent >= 55) barColor = '#B45309';

            html += '<div style="margin-bottom:1rem;">';
            html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:0.375rem;">';
            html += '<span style="font-size:0.75rem;color:var(--color-text-muted);min-width:42px;">相似度</span>';
            html += '<div style="flex:1;background:var(--color-border);height:8px;border-radius:4px;">';
            html += '<div style="width:' + simPercent + '%;background:' + barColor + ';height:100%;border-radius:4px;"></div>';
            html += '</div>';
            html += '<span style="font-size:0.75rem;font-weight:600;color:' + barColor + ';min-width:38px;text-align:right;">' + simPercent + '%</span>';
            html += '</div>';

            html += '<div style="background:var(--color-bg);border:1px solid var(--color-border);padding:0.75rem 1rem;border-radius:6px;">';
            html += '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:0.75rem;">';
            html += '<div style="flex:1;min-width:0;">';
            html += '<div style="font-weight:600;font-size:0.875rem;color:var(--color-text);margin-bottom:0.25rem;">' + escapeHtml(g.title || g.doc_id || '') + '</div>';
            html += '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:0.25rem;">';
            if (g.cancer_type) html += '<span class="badge badge-info">' + escapeHtml(g.cancer_type) + '</span>';
            html += '<span class="badge badge-warning">' + (g.match_item_count || 0) + ' 条相关推荐</span>';
            if ((g.shared_topics || []).length) {
                html += '<span class="badge badge-muted">共同主题: ' + escapeHtml(g.shared_topics.join('、')) + '</span>';
            }
            html += '</div>';
            html += '</div>';
            html += '<button class="btn btn-secondary btn-sm" onclick="navigate(\'guideline/' + escapeHtml(g.doc_id || '') + '\')">查看</button>';
            html += '</div>';
            html += '</div>';
            html += '</div>';
        });
    } else {
        html += '<div class="alert alert-info">暂未找到相关指南</div>';
    }

    container.innerHTML = html;
}

// 返回检索页，保留之前搜索状态
function goBackToSearch() {
    navigate('search');
}
