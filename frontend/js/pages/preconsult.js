/**
 * 智能预问诊页（NM-02）
 * 路由：#/preconsult
 * 功能：多轮症状采集 → 红旗征识别 → 风险分层 → 科室建议 → 就诊准备清单
 * 安全：红旗征宁高敏感；不给诊断结论。
 */
let _preSessionId = null;
let _preMessages = [];

registerPage('preconsult', function (container) {
    _preSessionId = null;
    _preMessages = [];

    container.innerHTML = `
        <h1 class="page-title">智能预问诊</h1>
        <p class="page-desc">请描述您的不适。系统会逐项询问并按「安全第一」识别需要紧急处理的情况，随后给出就医方向与就诊准备建议。</p>

        <ol class="pre-steps">
            <li class="pre-step active" data-step="1"><span class="pre-step-index">1</span>描述不适</li>
            <li class="pre-step" data-step="2"><span class="pre-step-index">2</span>风险识别</li>
            <li class="pre-step" data-step="3"><span class="pre-step-index">3</span>就医建议</li>
        </ol>

        <div class="pre-layout">
            <section class="card pre-chat-card">
                <div class="pre-chat-head">
                    <span class="pre-chat-dot"></span>
                    <span class="pre-chat-title">预问诊助手</span>
                    <span class="pre-chat-hint">仅作就医方向参考</span>
                </div>
                <div id="pre-chat" class="pre-chat"></div>
                <div class="pre-input-bar">
                    <textarea id="pre-input" class="textarea pre-input" rows="2"
                              placeholder="例如：咳嗽两周了，痰里带血"></textarea>
                    <button id="pre-send" class="btn btn-primary pre-send">发送</button>
                </div>
            </section>

            <aside id="pre-panel" class="pre-panel">
                <div class="pre-empty">
                    <div class="pre-empty-title">预问诊摘要</div>
                    <p class="pre-empty-text">对话开始后，这里会显示：</p>
                    <ul class="pre-empty-list">
                        <li>风险分层与就医紧迫程度</li>
                        <li>建议就诊科室</li>
                        <li>就诊前准备清单</li>
                        <li>已识别的症状与信息</li>
                    </ul>
                </div>
            </aside>
        </div>
    `;

    document.getElementById('pre-send').addEventListener('click', sendPreconsultMsg);
    document.getElementById('pre-input').addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendPreconsultMsg(); }
    });

    initPreconsult();
});

// 步骤指示：1 描述不适 → 2 风险识别 → 3 就医建议
function setPreStep(step) {
    document.querySelectorAll('.pre-step').forEach(function (el) {
        const n = Number(el.dataset.step);
        el.classList.toggle('active', n === step);
        el.classList.toggle('done', n < step);
    });
}

function initPreconsult() {
    const chat = document.getElementById('pre-chat');
    showLoading(chat);
    setPreStep(1);

    api.post('/preconsult/session', {}).then(function (resp) {
        if (!resp || !resp.success) { showError(chat, (resp && resp.message) || '会话创建失败'); return; }
        const d = resp.data;
        _preSessionId = d.session_id;
        chat.innerHTML = '';
        if (d.degraded) {
            appendPreMessage('system', d.note || '数据未就绪');
        }
        appendPreMessage('assistant', d.next_question ? d.next_question.prompt
            : '请描述您的主要不适，我会据此进一步询问。');
        if (d.disclaimer) appendPreMessage('disclaimer', d.disclaimer);
    }).catch(function (err) { showError(chat, err.message); });
}

function appendPreMessage(role, text) {
    const chat = document.getElementById('pre-chat');
    if (!chat) return;

    const div = document.createElement('div');
    div.className = 'pre-msg pre-msg-' + role;

    let html = '';
    if (role === 'assistant') {
        html += '<span class="pre-msg-label">预问诊助手</span>';
    }
    html += escapeHtml(text);
    div.innerHTML = html;

    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
}

function sendPreconsultMsg() {
    const input = document.getElementById('pre-input');
    const text = (input.value || '').trim();
    if (!text || !_preSessionId) return;
    input.value = '';
    appendPreMessage('user', text);
    setPreStep(2);

    const sendBtn = document.getElementById('pre-send');
    sendBtn.disabled = true;
    api.post('/preconsult/message', { session_id: _preSessionId, text: text }).then(function (resp) {
        sendBtn.disabled = false;
        if (!resp || !resp.success) {
            appendPreMessage('system', (resp && resp.message) || '发送失败');
            return;
        }
        const d = resp.data;

        // 红旗征优先播报（安全第一）
        if (d.red_flags && d.red_flags.length) {
            d.red_flags.forEach(function (f) {
                appendPreMessage('system', '⚠️ ' + (f.action || '检测到需要及时处理的情况'));
            });
        }
        if (d.next_question) {
            appendPreMessage('assistant', d.next_question.prompt);
        } else {
            appendPreMessage('assistant', '信息采集已完成，右侧已生成预问诊摘要，请携带就诊。');
        }
        renderPreconsultPanel(d);
    }).catch(function (err) {
        sendBtn.disabled = false;
        appendPreMessage('system', err.message);
    });
}

function renderPreconsultPanel(d) {
    const panel = document.getElementById('pre-panel');
    let html = '';

    if (d.degraded) {
        html += '<div class="alert alert-warning">' + escapeHtml(d.note || '部分数据未就绪') + '</div>';
    }

    // 风险分层：颜色 + 图标 + 文字，三者同时表达
    const riskClass = {
        emergency: 'pre-risk-high',
        urgent: 'pre-risk-mid',
        routine: 'pre-risk-low'
    }[d.risk_level] || '';
    html += '<div class="card">';
    html += '<div class="card-title">风险分层</div>';
    html += '<div class="pre-risk ' + riskClass + '">'
          + '<span class="pre-risk-mark">!</span>'
          + '<span>' + escapeHtml(d.risk_label || d.risk_level || '—') + '</span>'
          + '</div>';
    html += '</div>';

    // 科室建议
    if (d.department) {
        html += '<div class="card">';
        html += '<div class="card-title">建议科室</div>';
        if (d.department.primary) {
            html += '<div class="pre-dept-primary">' + escapeHtml(d.department.primary) + '</div>';
            if (d.department.alt && d.department.alt.length) {
                html += '<div class="pre-dept-alt">备选：' + escapeHtml(d.department.alt.join('、')) + '</div>';
            }
        } else {
            html += '<div class="pre-dept-alt">暂无匹配（分诊映射数据未就绪或未命中）</div>';
        }
        html += '</div>';
    }

    // 就诊准备清单（编号）
    if (d.visit_prep && d.visit_prep.length) {
        html += '<div class="card">';
        html += '<div class="card-title">就诊准备</div>';
        html += '<ol class="pre-prep">';
        d.visit_prep.forEach(function (t, i) {
            html += '<li><span class="pre-prep-index">' + (i + 1) + '</span><span>' + escapeHtml(t) + '</span></li>';
        });
        html += '</ol></div>';
    }

    // 已采集症状
    if (d.symptoms && d.symptoms.length) {
        html += '<div class="card">';
        html += '<div class="card-title">已识别症状</div>';
        html += '<div>';
        d.symptoms.forEach(function (s) {
            html += '<span class="badge badge-muted" style="margin:0 0.25rem 0.25rem 0;">' + escapeHtml(s) + '</span>';
        });
        html += '</div></div>';
    }

    // 已采集槽位（键值行）
    const slots = d.slots || {};
    const keys = Object.keys(slots);
    if (keys.length) {
        html += '<div class="card">';
        html += '<div class="card-title">已采集信息</div>';
        keys.forEach(function (k) {
            let v = slots[k];
            if (typeof v === 'object') v = JSON.stringify(v);
            html += '<div class="pre-kv">'
                  + '<span class="pre-kv-key">' + escapeHtml(k) + '</span>'
                  + '<span class="pre-kv-val">' + escapeHtml(String(v)) + '</span>'
                  + '</div>';
        });
        html += '</div>';
    }

    if (d.disclaimer) {
        html += '<div class="alert alert-warning pre-disclaimer">' + escapeHtml(d.disclaimer) + '</div>';
    }

    panel.innerHTML = html;
    setPreStep(3);
}
