/**
 * 患者端 H5（NM-06）
 * 路由：#/patient（首页）、#/patient/preconsult、#/patient/disease/{id}、
 *       #/patient/followup、#/patient/drug/{drug_id}
 *
 * 采用单 registerPage('patient') + 内部二级路由：getCurrentPage() 对
 * `#/patient/*` 统一返回 'patient'，故此处按完整 hash 分发子视图。
 *
 * 强制约束：每页免责声明 + 就医指引；不给诊断结论、不给处方。
 * 设计：移动优先，大字 + 大按钮。
 */

// 患者端固定文案
const PT_DISCLAIMER = '本页信息仅供参考，不构成诊断，具体请遵医嘱。';
const PT_SEEK_HELP = '如出现严重不适或症状加重，请及时联系医生或前往医院就诊。';

// 患者端样式（移动优先，大字大按钮）
const PT_CSS = `
.pt-wrap { max-width: 1100px; margin: 0 auto; }
.pt-title { font-size: 1.5rem; font-weight: 700; margin-bottom: 0.5rem; }
.pt-sub { color: var(--color-text-muted); font-size: 0.9375rem; margin-bottom: 1rem; line-height: 1.7; }
.pt-grid { display: grid; grid-template-columns: 1fr; gap: 0.75rem; }
@media (min-width: 560px) { .pt-grid { grid-template-columns: 1fr 1fr; } }
.pt-card { display: block; text-decoration: none; color: inherit; padding: 1.25rem; border-radius: 12px;
  border: 1px solid var(--color-border); background: var(--color-surface);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease; }
.pt-card:hover { border-color: var(--color-primary); transform: translateY(-2px); box-shadow: var(--shadow-raised); }
.pt-card:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { .pt-card { transition: none; } .pt-card:hover { transform: none; } }
/* 服务入口图标底衬：四色均取自既有语义色板，图标深色描边保证对比度 */
.pt-card-icon { width: 40px; height: 40px; border-radius: 10px; margin-bottom: 0.625rem;
  display: flex; align-items: center; justify-content: center; }
.pt-ico-primary { background: var(--color-primary-soft); color: var(--color-primary); }
.pt-ico-info { background: var(--color-info-bg); color: var(--color-info); }
.pt-ico-success { background: var(--color-success-bg); color: var(--color-success); }
.pt-ico-warning { background: var(--color-warning-bg); color: var(--color-warning); }
.pt-card h3 { font-size: 1.125rem; margin-bottom: 0.375rem; }
.pt-card p { font-size: 0.875rem; color: var(--color-text-muted); line-height: 1.6; margin: 0; }
.pt-btn { display: block; width: 100%; padding: 0.875rem 1rem; font-size: 1rem; border-radius: 10px;
  border: none; background: var(--color-primary); color: #fff; cursor: pointer; margin-bottom: 0.5rem; }
.pt-btn.pt-ghost { background: var(--color-surface); color: var(--color-text); border: 1px solid var(--color-border); }
.pt-input, .pt-textarea { width: 100%; padding: 0.875rem 1rem; font-size: 1rem; border-radius: 10px;
  border: 1px solid var(--color-border); background: var(--color-surface); color: var(--color-text); }
.pt-textarea { min-height: 120px; resize: vertical; }
.pt-chat { border: 1px solid var(--color-border); border-radius: 12px; padding: 1rem; min-height: 260px;
  max-height: 60vh; overflow-y: auto; background: var(--color-surface); }
.pt-msg { font-size: 1rem; line-height: 1.7; padding: 0.75rem 1rem; border-radius: 12px; margin-bottom: 0.625rem; }
.pt-msg.user { background: var(--color-primary); color: #fff; margin-left: 12%; }
.pt-msg.bot { background: var(--color-bg); margin-right: 12%; }
.pt-msg.warn { background: var(--color-warning-bg); color: var(--color-warning); font-size: 0.9375rem; }
.pt-msg.tip { background: transparent; border: 1px dashed var(--color-border); color: var(--color-text-muted); font-size: 0.8125rem; }
.pt-notice { margin-top: 1rem; padding: 0.875rem 1rem; border-radius: 10px; background: var(--color-warning-bg);
  color: var(--color-warning); font-size: 0.875rem; line-height: 1.7; }
.pt-back { display: inline-block; margin-bottom: 0.75rem; font-size: 0.9375rem; color: var(--color-primary); cursor: pointer; }
.pt-section { border: 1px solid var(--color-border); border-radius: 10px; padding: 0.875rem 1rem; margin-bottom: 0.5rem; }
.pt-section h4 { font-size: 1rem; margin-bottom: 0.375rem; }
.pt-section p { font-size: 0.9375rem; line-height: 1.8; color: var(--color-text-secondary); margin: 0; white-space: pre-wrap; }
`;

let _ptCssInjected = false;
function ensurePatientCss() {
    if (_ptCssInjected) return;
    const style = document.createElement('style');
    style.textContent = PT_CSS;
    document.head.appendChild(style);
    _ptCssInjected = true;
}

// 患者端页面外壳
function ptShell(innerHtml) {
    ensurePatientCss();
    return '<div class="pt-wrap">' + innerHtml
        + '<div class="pt-notice">' + PT_DISCLAIMER + '<br>' + PT_SEEK_HELP + '</div></div>';
}

function ptBack(to) {
    return '<a class="pt-back" href="#/patient' + (to ? '/' + to : '') + '">← 返回</a>';
}

registerPage('patient', function (container) {
    const hash = window.location.hash.replace('#/', '');
    if (hash === 'patient' || hash === 'patient/') { renderPatientHome(container); return; }

    // 二级路由
    const rest = hash.slice('patient/'.length);
    const seg = rest.split('/');
    if (seg[0] === 'preconsult') renderPatientPreconsult(container);
    else if (seg[0] === 'disease') renderPatientDisease(container, decodeURIComponent(seg[1] || ''));
    else if (seg[0] === 'followup') renderPatientFollowup(container);
    else if (seg[0] === 'drug') renderPatientDrug(container, decodeURIComponent(seg[1] || ''));
    else renderPatientHome(container);
});

// ============================================================
//  首页
// ============================================================
function renderPatientHome(container) {
    container.innerHTML = ptShell(
        '<h1 class="pt-title">患者服务</h1>'
        + '<p class="pt-sub">这里是为您准备的健康服务：可以了解疾病知识、自查症状、查看随访安排、了解用药信息。</p>'
        + '<div class="pt-grid">'
        + ptCard('#/patient/preconsult', '先说症状', '描述您的不适，我们会提示是否需要尽快就医，并给出就诊方向。',
            'pt-ico-primary', '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>')
        + ptCard('#/patient/disease', '了解疾病', '查看疾病的通俗介绍，包括表现、检查和日常注意。',
            'pt-ico-info', '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>')
        + ptCard('#/patient/followup', '我的随访', '查看随访安排，填写近况反馈，异常时会给出提醒。',
            'pt-ico-success', '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/>')
        + ptCard('#/patient/drug', '用药了解', '用通俗的话了解药品是做什么的、注意事项和常见不良反应。',
            'pt-ico-warning', '<path d="m10.5 20.5 10-10a4.95 4.95 0 1 0-7-7l-10 10a4.95 4.95 0 1 0 7 7Z"/><path d="m8.5 8.5 7 7"/>')
        + '</div>'
    );
}

function ptCard(href, title, desc, iconTone, iconPath) {
    const iconHtml = iconPath
        ? '<span class="pt-card-icon ' + iconTone + '"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" '
          + 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
          + 'stroke-linejoin="round">' + iconPath + '</svg></span>'
        : '';
    return '<a class="pt-card" href="' + href + '">' + iconHtml
        + '<h3>' + escapeHtml(title) + '</h3><p>' + escapeHtml(desc) + '</p></a>';
}

// ============================================================
//  患者预问诊（复用 NM-02）
// ============================================================
let _ptPreSessionId = null;

function renderPatientPreconsult(container) {
    _ptPreSessionId = null;
    container.innerHTML = ptShell(
        ptBack('')
        + '<h1 class="pt-title">说说您的不适</h1>'
        + '<p class="pt-sub">请用您自己的话描述。我们会逐项询问，并提示是否需要尽快就医。</p>'
        + '<div id="pt-chat" class="pt-chat"></div>'
        + '<div style="margin-top:0.75rem;">'
        + '<textarea id="pt-input" class="pt-textarea" placeholder="例如：咳嗽两周了，痰里带血"></textarea>'
        + '<button id="pt-send" class="pt-btn" style="margin-top:0.5rem;">发送</button>'
        + '</div>'
        + '<div id="pt-panel"></div>'
    );

    document.getElementById('pt-send').addEventListener('click', sendPtPreconsult);
    initPtPreconsult();
}

function initPtPreconsult() {
    const chat = document.getElementById('pt-chat');
    showLoading(chat);
    api.post('/preconsult/session', {}).then(function (resp) {
        if (!resp || !resp.success) { showError(chat, (resp && resp.message) || '暂时无法连接，请稍后再试'); return; }
        const d = resp.data;
        _ptPreSessionId = d.session_id;
        chat.innerHTML = '';
        if (d.degraded) ptMsg('tip', d.note || '部分服务尚未就绪');
        ptMsg('bot', d.next_question ? d.next_question.prompt : '请描述您的主要不适。');
    }).catch(function (err) { showError(chat, err.message); });
}

function ptMsg(role, text) {
    const chat = document.getElementById('pt-chat');
    if (!chat) return;
    const div = document.createElement('div');
    div.className = 'pt-msg ' + role;
    div.textContent = text;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
}

function sendPtPreconsult() {
    const input = document.getElementById('pt-input');
    const text = (input.value || '').trim();
    if (!text || !_ptPreSessionId) return;
    input.value = '';
    ptMsg('user', text);

    const btn = document.getElementById('pt-send');
    btn.disabled = true;
    api.post('/preconsult/message', { session_id: _ptPreSessionId, text: text }).then(function (resp) {
        btn.disabled = false;
        if (!resp || !resp.success) { ptMsg('warn', (resp && resp.message) || '发送失败'); return; }
        const d = resp.data;
        (d.red_flags || []).forEach(function (f) {
            ptMsg('warn', '⚠️ ' + (f.action || '建议尽快就医'));
        });
        ptMsg('bot', d.next_question ? d.next_question.prompt : '信息已记录，下面是为您整理的建议。');
        renderPtPrePanel(d);
    }).catch(function (err) { btn.disabled = false; ptMsg('warn', err.message); });
}

function renderPtPrePanel(d) {
    const panel = document.getElementById('pt-panel');
    let html = '';

    html += '<div class="pt-section"><h4>目前判断</h4><p>' + escapeHtml(d.risk_label || '—') + '</p></div>';

    if (d.department && d.department.primary) {
        html += '<div class="pt-section"><h4>建议就诊科室</h4><p>' + escapeHtml(d.department.primary);
        if (d.department.alt && d.department.alt.length) html += '（也可考虑：' + escapeHtml(d.department.alt.join('、')) + '）';
        html += '</p></div>';
    }

    if (d.visit_prep && d.visit_prep.length) {
        html += '<div class="pt-section"><h4>就诊前请准备</h4><p>' + d.visit_prep.map(escapeHtml).join('<br>') + '</p></div>';
    }

    if (d.symptoms && d.symptoms.length) {
        html += '<div class="pt-section"><h4>您提到的症状</h4><p>' + escapeHtml(d.symptoms.join('、')) + '</p></div>';
    }

    panel.innerHTML = html;
}

// ============================================================
//  疾病科普（复用 NM-01 患者版）
// ============================================================
function renderPatientDisease(container, diseaseId) {
    if (!diseaseId) {
        container.innerHTML = ptShell(
            ptBack('')
            + '<h1 class="pt-title">了解疾病</h1>'
            + '<p class="pt-sub">输入疾病名称，查看通俗介绍。</p>'
            + '<input id="pt-dis-q" class="pt-input" placeholder="例如：肺癌、乳腺癌">'
            + '<button id="pt-dis-btn" class="pt-btn" style="margin-top:0.5rem;">查询</button>'
            + '<div id="pt-dis-result"></div>'
        );
        document.getElementById('pt-dis-btn').addEventListener('click', ptDiseaseSearch);
        document.getElementById('pt-dis-q').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') ptDiseaseSearch();
        });
        return;
    }

    container.innerHTML = ptShell(ptBack('disease') + '<div id="pt-dis-detail"></div>');
    const box = document.getElementById('pt-dis-detail');
    showLoading(box);
    api.get('/diseases/' + encodeURIComponent(diseaseId), { version: 'patient' }).then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '未找到该疾病'); return; }
        const d = resp.data;
        let html = '<h1 class="pt-title">' + escapeHtml(d.name_canonical || '') + '</h1>';
        if (!d.sections || !d.sections.length) {
            html += '<div class="pt-sub">该疾病暂无内容。</div>';
        } else {
            d.sections.forEach(function (s) {
                html += '<div class="pt-section"><h4>' + escapeHtml(s.label) + '</h4><p>' + escapeHtml(s.text) + '</p></div>';
            });
        }
        box.innerHTML = html;
    }).catch(function (err) { showError(box, err.message); });
}

function ptDiseaseSearch() {
    const q = (document.getElementById('pt-dis-q').value || '').trim();
    const box = document.getElementById('pt-dis-result');
    if (!q) return;
    showLoading(box);
    api.get('/diseases/search', { q: q, mode: 'name' }).then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '查询失败'); return; }
        const d = resp.data;
        if (d.degraded && d.note) { box.innerHTML = '<div class="pt-section"><p>' + escapeHtml(d.note) + '</p></div>'; return; }
        if (!d.items || !d.items.length) { box.innerHTML = '<div class="pt-section"><p>' + escapeHtml(d.note || '未找到相关疾病') + '</p></div>'; return; }
        let html = '';
        d.items.forEach(function (it) {
            html += '<a class="pt-card" style="margin-bottom:0.5rem;" href="#/patient/disease/' + encodeURIComponent(it.disease_id) + '">';
            html += '<h3>' + escapeHtml(it.name_canonical || '') + '</h3>';
            html += '<p>' + escapeHtml((it.overview || '').slice(0, 80)) + '</p></a>';
        });
        box.innerHTML = html;
    }).catch(function (err) { showError(box, err.message); });
}

// ============================================================
//  随访反馈（复用 NM-03）
// ============================================================
function renderPatientFollowup(container) {
    container.innerHTML = ptShell(
        ptBack('')
        + '<h1 class="pt-title">我的随访</h1>'
        + '<p class="pt-sub">输入您的随访编号查看安排；填写近况后，如出现较明显不适会给出提醒。</p>'
        + '<input id="pt-fu-pid" class="pt-input" placeholder="请输入您的随访编号（患者 ID）">'
        + '<button id="pt-fu-btn" class="pt-btn" style="margin-top:0.5rem;">查看随访安排</button>'
        + '<div id="pt-fu-body"></div>'
    );
    document.getElementById('pt-fu-btn').addEventListener('click', loadPtFollowup);
    document.getElementById('pt-fu-pid').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') loadPtFollowup();
    });
}

function loadPtFollowup() {
    const pid = (document.getElementById('pt-fu-pid').value || '').trim();
    const box = document.getElementById('pt-fu-body');
    if (!pid) { alert('请输入随访编号'); return; }

    showLoading(box);
    api.get('/followup/tasks', { patient_id: pid }).then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '加载失败'); return; }
        const d = resp.data;
        if (!d.tasks || !d.tasks.length) {
            box.innerHTML = '<div class="pt-section"><p>暂无随访安排（随访计划数据未就绪，或该编号无任务）。</p></div>';
            return;
        }
        let html = '<div class="pt-section"><h4>随访安排（' + d.total + ' 项，待处理 ' + d.due_count + ' 项）</h4></div>';
        d.tasks.forEach(function (t) {
            html += '<div class="pt-section">';
            html += '<h4>' + escapeHtml(t.timepoint || '') + (t.due ? ' <span class="badge badge-warning">已到期</span>' : '') + '</h4>';
            html += '<p>检查项目：' + escapeHtml((t.items || []).join('、')) + '<br>计划日期：' + escapeHtml(t.due_date || '') + '</p>';
            if (t.status !== 'done') {
                html += '<input class="pt-input" id="pt-fu-text-' + t.task_id + '" placeholder="请描述您目前的情况" style="margin-top:0.5rem;">';
                html += '<select class="pt-input" id="pt-fu-sev-' + t.task_id + '" style="margin-top:0.5rem;">'
                    + '<option value="">不适程度（可选）</option><option value="轻度">轻度</option>'
                    + '<option value="中度">中度</option><option value="重度">重度</option></select>';
                html += '<button class="pt-btn" style="margin-top:0.5rem;" data-pt-fu="' + escapeHtml(t.task_id) + '">提交反馈</button>';
            } else {
                html += '<p><span class="badge badge-success">已反馈</span></p>';
            }
            html += '</div>';
        });
        box.innerHTML = html;
        box.querySelectorAll('button[data-pt-fu]').forEach(function (b) {
            b.addEventListener('click', function () { submitPtFollowup(b.dataset.ptFu, pid); });
        });
    }).catch(function (err) { showError(box, err.message); });
}

function submitPtFollowup(taskId, pid) {
    const textEl = document.getElementById('pt-fu-text-' + taskId);
    const sevEl = document.getElementById('pt-fu-sev-' + taskId);
    const item = {};
    if (textEl && textEl.value.trim()) item.text = textEl.value.trim();
    if (sevEl && sevEl.value) item.severity = sevEl.value;
    if (!item.text && !item.severity) { alert('请填写您的情况'); return; }

    api.post('/followup/record', { task_id: taskId, responses: [item] }).then(function (resp) {
        if (!resp || !resp.success) { alert((resp && resp.message) || '提交失败'); return; }
        const d = resp.data;
        let msg = '已记录。';
        if (d.alerts && d.alerts.length) {
            msg += '\n\n您的描述提示需要关注，建议' + (d.alerts[0].level_label || '尽快就医') + '。';
        }
        alert(msg);
        loadPtFollowup();
    }).catch(function (err) { alert('提交失败：' + err.message); });
}

// ============================================================
//  用药了解（复用 NM-06）
// ============================================================
function renderPatientDrug(container, drugId) {
    if (!drugId) {
        container.innerHTML = ptShell(
            ptBack('')
            + '<h1 class="pt-title">用药了解</h1>'
            + '<p class="pt-sub">输入药名，用通俗的话了解它是做什么的、注意事项和常见不良反应。</p>'
            + '<input id="pt-drug-q" class="pt-input" placeholder="例如：奥希替尼">'
            + '<button id="pt-drug-btn" class="pt-btn" style="margin-top:0.5rem;">搜索</button>'
            + '<div id="pt-drug-result"></div>'
        );
        document.getElementById('pt-drug-btn').addEventListener('click', ptDrugSearch);
        document.getElementById('pt-drug-q').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') ptDrugSearch();
        });
        return;
    }

    container.innerHTML = ptShell(ptBack('drug') + '<div id="pt-drug-detail"></div>');
    const box = document.getElementById('pt-drug-detail');
    showLoading(box);
    api.get('/patient/drug/' + encodeURIComponent(drugId)).then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '未找到该药品'); return; }
        renderPtDrugDetail(box, resp.data);
    }).catch(function (err) { showError(box, err.message); });
}

function ptDrugSearch() {
    const q = (document.getElementById('pt-drug-q').value || '').trim();
    const box = document.getElementById('pt-drug-result');
    showLoading(box);
    api.get('/patient/drugs', { q: q }).then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '搜索失败'); return; }
        const d = resp.data;
        if (d.degraded) { box.innerHTML = '<div class="pt-section"><p>' + escapeHtml(d.note || '药品数据未就绪') + '</p></div>'; return; }
        if (!d.items || !d.items.length) { box.innerHTML = '<div class="pt-section"><p>未找到相关药品。</p></div>'; return; }
        let html = '';
        d.items.forEach(function (it) {
            html += '<a class="pt-card" style="margin-bottom:0.5rem;" href="#/patient/drug/' + encodeURIComponent(it.drug_id) + '">';
            html += '<h3>' + escapeHtml(it.generic_name || '') + '</h3>';
            if (it.brand_names && it.brand_names.length) html += '<p>商品名：' + escapeHtml(it.brand_names.join('、')) + '</p>';
            html += '</a>';
        });
        box.innerHTML = html;
    }).catch(function (err) { showError(box, err.message); });
}

function renderPtDrugDetail(box, d) {
    const p = d.plain || {};
    let html = '<h1 class="pt-title">' + escapeHtml(d.generic_name || '') + '</h1>';
    if (d.brand_names && d.brand_names.length) {
        html += '<p class="pt-sub">商品名：' + escapeHtml(d.brand_names.join('、')) + '</p>';
    }
    if (d.degraded && d.note) html += '<div class="pt-section"><p>' + escapeHtml(d.note) + '</p></div>';

    if (p.what_is_it) html += '<div class="pt-section"><h4>这个药是做什么的</h4><p>' + escapeHtml(p.what_is_it) + '</p></div>';
    if (p.how_to_use) html += '<div class="pt-section"><h4>说明书中的用法</h4><p>' + escapeHtml(p.how_to_use) + '</p></div>';
    if (p.cautions && p.cautions.length) {
        html += '<div class="pt-section"><h4>注意事项</h4><p>' + p.cautions.map(escapeHtml).join('<br>') + '</p></div>';
    }
    if (p.side_effects && p.side_effects.length) {
        html += '<div class="pt-section"><h4>可能出现的不良反应</h4>';
        p.side_effects.forEach(function (s) {
            html += '<p style="margin-bottom:0.5rem;"><strong>' + escapeHtml(s.term) + '</strong>：'
                + escapeHtml(s.plain || '') + (s.when_to_seek_help ? '<br><span style="color:var(--color-warning);">' + escapeHtml(s.when_to_seek_help) + '</span>' : '') + '</p>';
        });
        html += '</div>';
    }
    if (p.seek_help) html += '<div class="pt-section"><h4>出现这些情况请及时就医</h4><p>' + escapeHtml(p.seek_help) + '</p></div>';

    box.innerHTML = html;
}
