/**
 * 跨癌种专题分析页面（医疗，BE-09）
 *
 * 针对一个临床专题，分别检索两个癌种的推荐条目并聚合，由 LLM 生成专题分析报告；
 * 支持基于报告的继续追问。
 */
const TOPIC_EXAMPLE = 'PD-1 抑制剂的适应证与证据';

registerPage('topic', function (container) {
    container.innerHTML = `
        <h1 class="page-title">跨癌种专题</h1>
        <p class="page-desc">输入一个临床专题，对比两个癌种在适应证、疗效证据、用药方案与安全性等方面的异同。</p>
        <hr class="divider">

        <!-- 选择面板 -->
        <div style="margin-bottom:1.5rem;">
            <div style="margin-bottom:0.75rem;">
                <label style="font-size:0.8125rem;font-weight:600;color:var(--color-text-secondary);display:block;margin-bottom:0.25rem;">专题主题</label>
                <input type="text" id="topic-query" class="input" placeholder="例如：${TOPIC_EXAMPLE}">
            </div>
            <div class="grid-2" style="margin-bottom:0.75rem;">
                <div>
                    <label style="font-size:0.8125rem;font-weight:600;color:var(--color-text-secondary);display:block;margin-bottom:0.25rem;">癌种 A</label>
                    <select id="topic-cancer-a" class="select"></select>
                </div>
                <div>
                    <label style="font-size:0.8125rem;font-weight:600;color:var(--color-text-secondary);display:block;margin-bottom:0.25rem;">癌种 B</label>
                    <select id="topic-cancer-b" class="select"></select>
                </div>
            </div>
            <div style="margin-bottom:0.75rem;">
                <label style="font-size:0.8125rem;font-weight:600;color:var(--color-text-secondary);display:block;margin-bottom:0.25rem;">每癌种检索条目数: <span id="topic-topn-val">8</span></label>
                <input type="range" id="topic-topn" min="3" max="20" value="8" style="width:260px;">
            </div>
            <button id="topic-run" class="btn btn-primary">生成专题分析</button>
        </div>

        <!-- 状态提示 -->
        <div id="topic-status"></div>

        <!-- 结果区 -->
        <div id="topic-result"></div>
    `;

    // 加载癌种（受控词表，value=code）
    api.get('/search/cancer_types').then(function (data) {
        const list = (data && data.data) || [];
        const selA = document.getElementById('topic-cancer-a');
        const selB = document.getElementById('topic-cancer-b');
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

    document.getElementById('topic-topn').addEventListener('input', function () {
        document.getElementById('topic-topn-val').textContent = this.value;
    });
    document.getElementById('topic-run').addEventListener('click', runTopicAnalysis);
    document.getElementById('topic-query').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') runTopicAnalysis();
    });
});

function runTopicAnalysis() {
    const query = document.getElementById('topic-query').value.trim();
    const cancerA = document.getElementById('topic-cancer-a').value;
    const cancerB = document.getElementById('topic-cancer-b').value;
    const topN = parseInt(document.getElementById('topic-topn').value);

    if (!query) { alert('请输入专题主题'); return; }
    if (!cancerA || !cancerB) { alert('请选择两个癌种'); return; }
    if (cancerA === cancerB) { alert('请选择不同的癌种'); return; }

    const statusEl = document.getElementById('topic-status');
    const resultEl = document.getElementById('topic-result');
    statusEl.innerHTML = '<div class="alert alert-info">正在检索两癌种推荐条目并生成专题分析，请稍候（约 20-60 秒）…</div>';
    resultEl.innerHTML = '<div class="loading"><div class="spinner"></div>分析中...</div>';

    const params = {
        query: query,
        cancer_type_a: cancerA,
        cancer_type_b: cancerB,
        top_n: topN
    };

    api.post('/topic-analysis?' + toQuery(params), null).then(function (data) {
        if (!data || !data.success) {
            statusEl.innerHTML = '<div class="alert alert-error">专题分析失败：' + (data ? data.message : '未知错误') + '</div>';
            resultEl.innerHTML = '';
            return;
        }
        statusEl.innerHTML = '<div class="alert alert-success">专题分析完成</div>';
        window._topicLastResult = data.data;
        renderTopicResult(resultEl, data.data);
        bindTopicFollowUp();
    }).catch(function (err) {
        statusEl.innerHTML = '<div class="alert alert-error">请求失败：' + err.message + '</div>';
        resultEl.innerHTML = '';
    });
}

function renderTopicResult(container, r) {
    const nameA = r.cancer_name_a || r.cancer_type_a || '癌种A';
    const nameB = r.cancer_name_b || r.cancer_type_b || '癌种B';

    let html = '';

    // 概览
    const agg = r.aggregated || {};
    const ret = r.retrieval || {};
    html += '<div class="card" style="padding:0.875rem 1rem;margin-bottom:1rem;">';
    html += '<div style="font-size:0.875rem;color:var(--color-text-secondary);">';
    html += '专题「' + escapeHtml(r.query || '') + '」：' + escapeHtml(nameA) + ' 检索到 ' + (ret.recs_a_count || 0) + ' 条推荐（' + (agg.guides_a_count || 0) + ' 篇指南），'
          + escapeHtml(nameB) + ' 检索到 ' + (ret.recs_b_count || 0) + ' 条推荐（' + (agg.guides_b_count || 0) + ' 篇指南）。';
    html += '</div></div>';

    // 报告
    html += '<h2 class="section-title">专题分析报告</h2>';
    html += '<div class="card markdown-body" style="padding:1rem;">' + renderMarkdown(r.analysis_report || '（无报告）') + '</div>';

    // 检索到的指南
    html += '<hr class="divider">';
    html += '<h2 class="section-title">检索到的指南</h2>';
    html += '<div class="grid-2">';
    html += renderGuideGroup(nameA, (agg.guides_a || []));
    html += renderGuideGroup(nameB, (agg.guides_b || []));
    html += '</div>';

    // 追问
    if (r.timing) {
        html += '<div style="margin-top:0.75rem;font-size:0.75rem;color:var(--color-text-muted);">'
              + '检索 ' + escapeHtml(r.timing.retrieval || '-') + ' · 聚合 ' + escapeHtml(r.timing.aggregation || '-')
              + ' · LLM ' + escapeHtml(r.timing.llm_generation || '-') + ' · 总计 ' + escapeHtml(r.timing.total || '-') + '</div>';
    }
    html += '<hr class="divider" style="margin-top:2rem;">';
    html += '<h2 class="section-title">继续追问 AI</h2>';
    html += '<div class="card" style="margin-bottom:1rem;">';
    html += '<div style="display:flex;gap:0.5rem;margin-bottom:0.75rem;">';
    html += '<input type="text" id="topic-followup-input" class="input" placeholder="例如：两癌种在证据等级上还有什么差异？" style="flex:1;">';
    html += '<button id="topic-followup-btn" class="btn btn-primary">追问</button>';
    html += '</div>';
    html += '<div id="topic-followup-history"></div>';
    html += '</div>';

    container.innerHTML = html;
}

function renderGuideGroup(cancerName, guides) {
    let html = '<div class="card" style="padding:0.875rem 1rem;">';
    html += '<div style="font-weight:600;font-size:0.8125rem;color:var(--color-text);margin-bottom:0.5rem;">' + escapeHtml(cancerName) + '</div>';
    if (!guides.length) {
        html += '<div style="font-size:0.8125rem;color:var(--color-text-muted);">未检索到相关指南</div>';
    } else {
        guides.forEach(function (g) {
            html += '<div style="padding:0.375rem 0;border-bottom:1px solid var(--color-border);">';
            html += '<div style="font-size:0.8125rem;color:var(--color-text);">' + escapeHtml(g.title || g.doc_id || '') + '</div>';
            html += '<div style="font-size:0.75rem;color:var(--color-text-muted);">'
                  + (g.rec_count || 0) + ' 条推荐 · 最高相似度 ' + Math.round((g.max_similarity || 0) * 100) + '%</div>';
            html += '</div>';
        });
    }
    html += '</div>';
    return html;
}

function bindTopicFollowUp() {
    const btn = document.getElementById('topic-followup-btn');
    if (!btn) return;
    btn.addEventListener('click', function () {
        const input = document.getElementById('topic-followup-input');
        const q = (input.value || '').trim();
        if (!q) return;
        const historyEl = document.getElementById('topic-followup-history');
        historyEl.innerHTML += '<div style="font-size:0.8125rem;color:var(--color-text);margin-bottom:0.375rem;"><strong>问：</strong>' + escapeHtml(q) + '</div>';
        historyEl.innerHTML += '<div id="topic-followup-wait" style="font-size:0.8125rem;color:var(--color-text-muted);margin-bottom:0.75rem;">思考中...</div>';
        input.value = '';

        api.post('/topic-analysis/follow-up?' + toQuery({ follow_up_question: q }), window._topicLastResult).then(function (data) {
            const wait = document.getElementById('topic-followup-wait');
            if (wait) wait.remove();
            if (data && data.success) {
                historyEl.innerHTML += '<div class="markdown-body" style="font-size:0.8125rem;color:var(--color-text-secondary);margin-bottom:0.75rem;"><strong>答：</strong>' + renderMarkdown(data.data.answer || '') + '</div>';
            } else {
                historyEl.innerHTML += '<div class="alert alert-error" style="margin-bottom:0.75rem;">追问失败：' + escapeHtml((data && data.message) || '未知错误') + '</div>';
            }
        }).catch(function (err) {
            const wait = document.getElementById('topic-followup-wait');
            if (wait) wait.remove();
            historyEl.innerHTML += '<div class="alert alert-error" style="margin-bottom:0.75rem;">请求失败：' + escapeHtml(err.message) + '</div>';
        });
    });
}

// 把对象转成 querystring（跳过空值）
function toQuery(obj) {
    return Object.entries(obj || {})
        .filter(function (kv) { return kv[1] !== undefined && kv[1] !== null && kv[1] !== ''; })
        .map(function (kv) { return encodeURIComponent(kv[0]) + '=' + encodeURIComponent(kv[1]); })
        .join('&');
}
