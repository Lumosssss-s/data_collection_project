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
        <p class="page-subtitle" style="color:var(--color-text-muted);margin-bottom:1rem;">
            请描述您的不适。系统会逐项询问并按「安全第一」识别需要紧急处理的情况，随后给出就医方向与就诊准备建议。
        </p>

        <div style="display:grid;grid-template-columns:minmax(0,1.4fr) minmax(280px,1fr);gap:1rem;align-items:start;">
            <div>
                <div id="pre-chat" class="card" style="padding:1rem;min-height:320px;max-height:520px;overflow-y:auto;"></div>
                <div class="card" style="padding:0.75rem;margin-top:0.5rem;">
                    <div style="display:flex;gap:0.5rem;">
                        <textarea id="pre-input" class="textarea" rows="2" style="flex:1;"
                                  placeholder="例如：咳嗽两周了，痰里带血"></textarea>
                        <button id="pre-send" class="btn btn-primary" style="align-self:stretch;">发送</button>
                    </div>
                </div>
            </div>
            <div id="pre-panel"></div>
        </div>
    `;

    document.getElementById('pre-send').addEventListener('click', sendPreconsultMsg);
    document.getElementById('pre-input').addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendPreconsultMsg(); }
    });

    initPreconsult();
});

function initPreconsult() {
    const chat = document.getElementById('pre-chat');
    const panel = document.getElementById('pre-panel');
    showLoading(chat);
    panel.innerHTML = '';

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
    let style = 'margin-bottom:0.5rem;padding:0.5rem 0.75rem;border-radius:8px;font-size:0.875rem;line-height:1.6;';
    let label = '';
    if (role === 'user') {
        style += 'background:var(--color-primary);color:#fff;margin-left:15%;';
    } else if (role === 'assistant') {
        style += 'background:var(--color-bg);margin-right:15%;';
        label = '<div style="font-size:0.75rem;color:var(--color-text-muted);margin-bottom:0.25rem;">预问诊助手</div>';
    } else if (role === 'system') {
        style += 'background:var(--color-warning-bg);color:var(--color-warning);font-size:0.8125rem;';
    } else if (role === 'disclaimer') {
        style += 'background:transparent;color:var(--color-text-muted);font-size:0.75rem;border:1px dashed var(--color-border);';
    }
    const div = document.createElement('div');
    div.setAttribute('style', style);
    div.innerHTML = label + escapeHtml(text);
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
}

function sendPreconsultMsg() {
    const input = document.getElementById('pre-input');
    const text = (input.value || '').trim();
    if (!text || !_preSessionId) return;
    input.value = '';
    appendPreMessage('user', text);

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
        html += '<div class="alert alert-warning" style="margin-bottom:0.75rem;">' + escapeHtml(d.note || '部分数据未就绪') + '</div>';
    }

    // 风险分层
    const riskBadge = { emergency: 'badge-warning', urgent: 'badge-warning', routine: 'badge-success' }[d.risk_level] || 'badge-muted';
    html += '<div class="card" style="padding:1rem;margin-bottom:0.75rem;">';
    html += '<div style="font-weight:600;margin-bottom:0.5rem;">风险分层</div>';
    html += '<span class="badge ' + riskBadge + '">' + escapeHtml(d.risk_label || d.risk_level || '—') + '</span>';
    html += '</div>';

    // 科室建议
    if (d.department) {
        html += '<div class="card" style="padding:1rem;margin-bottom:0.75rem;">';
        html += '<div style="font-weight:600;margin-bottom:0.5rem;">建议科室</div>';
        if (d.department.primary) {
            html += '<div style="font-size:0.9375rem;">' + escapeHtml(d.department.primary) + '</div>';
            if (d.department.alt && d.department.alt.length) {
                html += '<div style="font-size:0.75rem;color:var(--color-text-muted);margin-top:0.25rem;">备选：' + escapeHtml(d.department.alt.join('、')) + '</div>';
            }
        } else {
            html += '<div style="font-size:0.8125rem;color:var(--color-text-muted);">暂无匹配（分诊映射数据未就绪或未命中）</div>';
        }
        html += '</div>';
    }

    // 就诊准备清单
    if (d.visit_prep && d.visit_prep.length) {
        html += '<div class="card" style="padding:1rem;margin-bottom:0.75rem;">';
        html += '<div style="font-weight:600;margin-bottom:0.5rem;">就诊准备</div><ul style="margin:0;padding-left:1.1rem;font-size:0.8125rem;line-height:1.7;">';
        d.visit_prep.forEach(function (t) { html += '<li>' + escapeHtml(t) + '</li>'; });
        html += '</ul></div>';
    }

    // 已采集症状
    if (d.symptoms && d.symptoms.length) {
        html += '<div class="card" style="padding:1rem;margin-bottom:0.75rem;">';
        html += '<div style="font-weight:600;margin-bottom:0.5rem;">已识别症状</div>';
        d.symptoms.forEach(function (s) { html += '<span class="badge badge-muted" style="margin:0 0.25rem 0.25rem 0;">' + escapeHtml(s) + '</span>'; });
        html += '</div>';
    }

    // 已采集槽位
    const slots = d.slots || {};
    const keys = Object.keys(slots);
    if (keys.length) {
        html += '<div class="card" style="padding:1rem;margin-bottom:0.75rem;">';
        html += '<div style="font-weight:600;margin-bottom:0.5rem;">已采集信息</div>';
        keys.forEach(function (k) {
            let v = slots[k];
            if (typeof v === 'object') v = JSON.stringify(v);
            html += '<div style="font-size:0.8125rem;margin-bottom:0.25rem;"><span style="color:var(--color-text-muted);">' + escapeHtml(k) + '</span>：' + escapeHtml(String(v)) + '</div>';
        });
        html += '</div>';
    }

    if (d.disclaimer) {
        html += '<div class="alert alert-warning" style="font-size:0.75rem;">' + escapeHtml(d.disclaimer) + '</div>';
    }

    panel.innerHTML = html;
}
