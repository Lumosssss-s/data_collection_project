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
    const docId = hash.replace('#/guideline/', '');
    window.gdDocId = docId;

    if (!docId) {
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

    // 先用单条查询渲染主体（毫秒级），速览与相似指南随后异步回填。
    // 速览接口是同步 LLM 生成（timeout=100s、max_retries=2），不能阻塞首屏。
    api.get('/search/doc/' + docId).then(function (itemData) {
        if (!itemData || !itemData.success) {
            showError(contentEl, '获取条目详情失败：' + (itemData ? itemData.message : '未知错误'));
            return;
        }
        const item = itemData.data;
        renderGuideDetail(contentEl, item);

        // 速览只对指南（doc）有意义，其它类型直接跳过，省一次必然空结果的请求
        if ((item.data_type || '') === 'doc') {
            api.get('/search/doc/' + docId + '/summary')
                .then(function (d) {
                    if (d && d.success) fillSummarySlot('ok', d.data);
                    else fillSummarySlot('error');
                })
                .catch(function () { fillSummarySlot('error'); });
        } else {
            fillSummarySlot('skip');
        }

        api.get('/search/doc/' + docId + '/similar', { top_k: 5 })
            .then(function (d) { fillSimilarSlot(d && d.success ? d.data : null); })
            .catch(function () { fillSimilarSlot(null); });
    }).catch(function (err) {
        showError(contentEl, '请求失败：' + err.message);
    });
});

// 徽标文案
const DATA_TYPE_LABELS = { doc: '指南', rec: '推荐条目', drug: '药品说明书', term: '术语' };
const EVIDENCE_LABELS = { high: '高', moderate: '中', low: '低', very_low: '极低' };
const STRENGTH_LABELS = { strong: '强', weak: '弱', not_graded: '未分级' };

function renderGuideDetail(container, item) {
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

    // ===== 指南速览（占位，内容由 fillSummarySlot 异步回填）=====
    html += '<div id="gd-summary-slot">' + summaryPendingHtml() + '</div>';

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

    // ===== 指南全文（按需解析原始 XML，仅 doc 类型）=====
    if (dataType === 'doc') {
        html += '<div id="gd-fulltext-slot">' + fulltextPendingHtml() + '</div>';
    }

    // ===== 相关指南推荐（占位，内容由 fillSimilarSlot 异步回填）=====
    html += '<div id="gd-similar-slot">' + similarPendingHtml() + '</div>';

    container.innerHTML = html;
}

// ===== 速览 / 相似指南：占位与回填 =====

function summaryPendingHtml() {
    return '<h2 class="section-title">指南速览</h2>'
        + '<div class="alert alert-info">正在生成指南速览…首次访问需要数十秒，之后直接读缓存。</div>';
}

function summaryBlockHtml(summary) {
    let html = '<h2 class="section-title">指南速览</h2>';
    html += '<div class="card" style="padding:1rem;margin-bottom:1rem;">';

    if (summary.overview) {
        html += '<div style="font-size:0.875rem;line-height:1.75;color:var(--color-text-secondary);margin-bottom:0.75rem;">' + escapeHtml(summary.overview) + '</div>';
    }
    const recs = summary.key_recommendations || [];
    if (recs.length) {
        html += '<div class="sub-title">核心推荐要点</div>';
        html += '<ul style="margin:0 0 0.75rem 1.1rem;padding:0;font-size:0.8125rem;line-height:1.7;color:var(--color-text-secondary);">';
        recs.forEach(function (r) { html += '<li>' + escapeHtml(r) + '</li>'; });
        html += '</ul>';
    }
    if (summary.evidence_notes) {
        html += '<div class="sub-title">证据特点</div>';
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
    return html;
}

function similarPendingHtml() {
    return '<h2 class="section-title">相关指南推荐</h2>'
        + '<div class="alert alert-info">正在匹配相关指南…</div>';
}

function similarBlockHtml(similar) {
    let html = '<h2 class="section-title">相关指南推荐</h2>';
    const guides = (similar && similar.similar_guides) || [];
    if (!guides.length) {
        return html + emptyState('暂未找到相关指南');
    }
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
        html += '<div class="item-title">' + escapeHtml(g.title || g.doc_id || '') + '</div>';
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
    return html;
}

function fillSummarySlot(state, data) {
    const slot = document.getElementById('gd-summary-slot');
    if (!slot) return;
    if (state === 'skip') {
        slot.innerHTML = '';
        return;
    }
    if (state === 'error' || !data) {
        slot.innerHTML = '<h2 class="section-title">指南速览</h2>'
            + '<div class="alert alert-info">指南速览暂不可用（生成失败，可稍后重试）。</div>';
        return;
    }
    slot.innerHTML = summaryBlockHtml(data);
}

function fillSimilarSlot(data) {
    const slot = document.getElementById('gd-similar-slot');
    if (!slot) return;
    slot.innerHTML = similarBlockHtml(data);
}

// ===== 指南全文（只读解析原始 XML，不入检索索引）=====

function fulltextPendingHtml() {
    return '<h2 class="section-title">指南全文</h2>'
        + '<div class="card" style="padding:1rem;">'
        + '<p style="font-size:0.8125rem;color:var(--color-text-muted);margin:0 0 0.75rem;">直接解析指南原始 XML（Europe PMC 全文），不影响检索索引；已排除参考文献、致谢与利益冲突等后置部分。</p>'
        + '<button class="btn btn-secondary btn-sm" onclick="loadGuideFulltext()">展开全文</button>'
        + '</div>';
}

function fulltextSectionHtml(sec) {
    let html = '<details style="margin:0.35rem 0;">';
    html += '<summary class="sub-title" style="cursor:pointer;">'
        + escapeHtml(sec.heading || '（未命名章节）') + '</summary>';
    (sec.paragraphs || []).forEach(function (p) {
        html += '<p style="font-size:0.8125rem;line-height:1.75;color:var(--color-text-secondary);margin:0.45rem 0;">'
            + escapeHtml(p) + '</p>';
    });
    (sec.children || []).forEach(function (child) {
        html += '<div style="margin-left:0.85rem;">' + fulltextSectionHtml(child) + '</div>';
    });
    html += '</details>';
    return html;
}

function fulltextHtml(data) {
    let html = '<h2 class="section-title">指南全文</h2>';
    if (data.abstract) {
        html += '<div class="card" style="padding:1rem;margin-bottom:1rem;">';
        html += '<div class="sub-title">摘要</div>';
        html += '<div style="font-size:0.8125rem;line-height:1.75;color:var(--color-text-secondary);">'
            + escapeHtml(data.abstract) + '</div>';
        html += '</div>';
    }
    html += '<div class="card" style="padding:1rem;">';
    (data.sections || []).forEach(function (s) { html += fulltextSectionHtml(s); });
    html += '</div>';
    const st = data.stats || {};
    html += '<p style="font-size:0.75rem;color:var(--color-text-muted);margin-top:0.5rem;">'
        + '来源：原始 XML（Europe PMC）｜一级章节 ' + (st.section_count || 0)
        + ' 个｜正文 ' + (st.char_count || 0).toLocaleString() + ' 字符</p>';
    return html;
}

window.loadGuideFulltext = function () {
    const slot = document.getElementById('gd-fulltext-slot');
    const docId = window.gdDocId;
    if (!slot || !docId) return;
    slot.innerHTML = '<h2 class="section-title">指南全文</h2>'
        + '<div class="alert alert-info">正在解析全文…</div>';
    api.get('/search/doc/' + docId + '/fulltext')
        .then(function (d) {
            if (d && d.success) {
                slot.innerHTML = fulltextHtml(d.data);
            } else {
                slot.innerHTML = '<h2 class="section-title">指南全文</h2>'
                    + emptyState('该指南暂无可用全文。');
            }
        })
        .catch(function () {
            slot.innerHTML = '<h2 class="section-title">指南全文</h2>'
                + '<div class="alert alert-info">全文加载失败，请稍后重试。</div>';
        });
};

// 返回检索页，保留之前搜索状态
function goBackToSearch() {
    navigate('search');
}
