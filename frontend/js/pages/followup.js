/**
 * 智能随访页（NM-03）
 * 路由：#/followup
 * 流程：生成随访计划（模板驱动）→ 任务列表 → 反馈（CTCAE 分级）→ 异常预警
 */
const FU_PHASES = [
    { value: 'postoperative', label: '术后' },
    { value: 'on_treatment', label: '治疗中' },
    { value: 'rehabilitation', label: '康复期' },
    { value: 'survivorship', label: '长期生存' }
];

let _fuState = { plan: null };

registerPage('followup', function (container) {
    _fuState = { plan: null };

    container.innerHTML = `
        <h1 class="page-title">智能随访</h1>
        <p class="page-subtitle" style="color:var(--color-text-muted);margin-bottom:1rem;">
            按「癌种 × 阶段」生成随访计划，跟踪随访任务并依据 CTCAE 5.0 对反馈分级，3 级及以上自动预警。
        </p>

        <div class="card" style="padding:1rem;margin-bottom:1rem;">
            <div style="font-weight:600;margin-bottom:0.75rem;">生成随访计划</div>
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:flex-end;">
                <div><div style="font-size:0.75rem;color:var(--color-text-muted);margin-bottom:0.25rem;">病例 ID</div>
                    <input id="fu-case" class="input" style="width:160px;" placeholder="CASE-001"></div>
                <div><div style="font-size:0.75rem;color:var(--color-text-muted);margin-bottom:0.25rem;">癌种</div>
                    <select id="fu-cancer" class="select" style="width:auto;"><option value="">加载中…</option></select></div>
                <div><div style="font-size:0.75rem;color:var(--color-text-muted);margin-bottom:0.25rem;">阶段</div>
                    <select id="fu-phase" class="select" style="width:auto;">
                        ${FU_PHASES.map(p => '<option value="' + p.value + '">' + p.label + '</option>').join('')}
                    </select></div>
                <button id="fu-plan-btn" class="btn btn-primary">生成计划</button>
            </div>
        </div>

        <div id="fu-body"></div>
    `;

    // 癌种选项（受控词表，与检索/问答同源）
    api.get('/search/cancer_types').then(function (resp) {
        const sel = document.getElementById('fu-cancer');
        const items = (resp && resp.data && (resp.data.cancer_types || resp.data.items || resp.data)) || [];
        let html = '<option value="">请选择</option>';
        (Array.isArray(items) ? items : []).forEach(function (c) {
            const val = c.value || c.cancer_type || c.code || '';
            const label = c.label || c.label_zh || val;
            if (val) html += '<option value="' + escapeHtml(val) + '">' + escapeHtml(label) + '</option>';
        });
        sel.innerHTML = html;
    }).catch(function () {
        document.getElementById('fu-cancer').innerHTML = '<option value="">加载失败</option>';
    });

    document.getElementById('fu-plan-btn').addEventListener('click', createFollowupPlan);
    renderFollowup();
});

function createFollowupPlan() {
    const caseId = (document.getElementById('fu-case').value || '').trim() || 'CASE-DEMO';
    const cancerType = document.getElementById('fu-cancer').value;
    const phase = document.getElementById('fu-phase').value;
    const body = document.getElementById('fu-body');

    if (!cancerType) { alert('请选择癌种'); return; }

    showLoading(body);
    api.post('/followup/plan', { case_id: caseId, cancer_type: cancerType, phase: phase })
        .then(function (resp) {
            if (!resp || !resp.success) { showError(body, (resp && resp.message) || '生成失败'); return; }
            _fuState.plan = resp.data;
            renderFollowup();
        }).catch(function (err) { showError(body, err.message); });
}

function renderFollowup() {
    const body = document.getElementById('fu-body');
    const plan = _fuState.plan;
    let html = '';

    if (!plan) {
        body.innerHTML = '<div class="alert alert-info">请选择癌种与阶段后生成随访计划。</div>';
        return;
    }

    if (plan.degraded && plan.note) {
        html += '<div class="alert alert-warning">' + escapeHtml(plan.note) + '</div>';
    }

    if (!plan.tasks || !plan.tasks.length) {
        html += '<div class="alert alert-info">该条件下暂无随访任务（模板未匹配或数据未就绪）。</div>';
        body.innerHTML = html;
        return;
    }

    // 计划概要
    html += '<div class="card" style="padding:0.875rem 1rem;margin-bottom:0.75rem;">';
    html += '<div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;">';
    html += '<span class="badge badge-info">' + escapeHtml(plan.phase_label || plan.phase) + '</span>';
    if (plan.tpl_id) html += '<span class="badge badge-muted">' + escapeHtml(plan.tpl_id) + '</span>';
    if (plan.stage && plan.stage.length) html += '<span class="badge badge-muted">分期 ' + escapeHtml(plan.stage.join('/')) + '</span>';
    html += '<span style="font-size:0.8125rem;color:var(--color-text-muted);">共 ' + plan.tasks.length + ' 个随访任务</span>';
    html += '</div></div>';

    // 任务列表
    html += '<div class="card" style="padding:1rem;margin-bottom:0.75rem;"><div style="font-weight:600;margin-bottom:0.5rem;">随访任务</div>';
    html += '<table style="width:100%;border-collapse:collapse;font-size:0.8125rem;">';
    html += '<tr>' + ['时间点', '检查项目', '计划日期', '状态', '操作'].map(function (h) {
        return '<th style="border:1px solid var(--color-border);padding:6px 10px;text-align:left;background:var(--color-bg);">' + h + '</th>';
    }).join('') + '</tr>';
    plan.tasks.forEach(function (t) {
        const statusBadge = t.status === 'done'
            ? '<span class="badge badge-success">已反馈</span>'
            : '<span class="badge badge-info">待反馈</span>';
        html += '<tr data-task="' + escapeHtml(t.task_id) + '">';
        html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + escapeHtml(t.timepoint || '') + '</td>';
        html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + escapeHtml((t.items || []).join('、')) + '</td>';
        html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + escapeHtml(t.due_date || '') + '</td>';
        html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">' + statusBadge + '</td>';
        html += '<td style="border:1px solid var(--color-border);padding:6px 10px;">'
            + '<button class="btn btn-ghost btn-sm" data-feedback="' + escapeHtml(t.task_id) + '">填写反馈</button></td>';
        html += '</tr>';
        html += '<tr data-fbrow="' + escapeHtml(t.task_id) + '" style="display:none;"><td colspan="5" style="border:1px solid var(--color-border);padding:0.75rem;background:var(--color-bg);">'
            + feedbackFormHtml(t) + '</td></tr>';
    });
    html += '</table></div>';

    // CTCAE 监测项
    if (plan.ae_monitoring && plan.ae_monitoring.length) {
        html += '<div class="card" style="padding:1rem;margin-bottom:0.75rem;"><div style="font-weight:600;margin-bottom:0.5rem;">不良反应监测（CTCAE 5.0）</div>';
        plan.ae_monitoring.forEach(function (ae) {
            const ga = ae.grade_action || {};
            html += '<div style="font-size:0.8125rem;margin-bottom:0.375rem;"><strong>' + escapeHtml(ae.ctcae_term || '') + '</strong>：';
            html += '1-2 级 ' + escapeHtml(ga['1-2'] || '—') + '；3 级 ' + escapeHtml(ga['3'] || '—') + '；4 级 ' + escapeHtml(ga['4'] || '—') + '</div>';
        });
        html += '</div>';
    }

    // 提醒消息模板
    if (plan.messages && plan.messages.length) {
        html += '<div class="card" style="padding:1rem;margin-bottom:0.75rem;"><div style="font-weight:600;margin-bottom:0.5rem;">提醒消息模板（B5）</div>';
        plan.messages.forEach(function (m) {
            html += '<div style="font-size:0.8125rem;margin-bottom:0.5rem;padding:0.5rem;background:var(--color-bg);border-radius:6px;">';
            html += '<span class="badge badge-muted">' + escapeHtml(m.msg_type_label || m.msg_type) + '</span> ';
            html += escapeHtml(m.template || '');
            html += '</div>';
        });
        html += '</div>';
    }

    // 预警区
    html += '<div id="fu-alerts"></div>';
    html += '<div class="alert alert-warning" style="margin-top:0.75rem;">' + escapeHtml(plan.disclaimer || '') + '</div>';

    body.innerHTML = html;

    body.querySelectorAll('button[data-feedback]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const row = body.querySelector('tr[data-fbrow="' + btn.dataset.feedback + '"]');
            if (row) row.style.display = row.style.display === 'none' ? '' : 'none';
        });
    });
    body.querySelectorAll('button[data-submit]').forEach(function (btn) {
        btn.addEventListener('click', function () { submitFollowupRecord(btn.dataset.submit); });
    });

    loadFollowupAlerts();
}

function feedbackFormHtml(task) {
    const terms = (task.items || []).map(function (x) { return String(x).trim(); }).filter(Boolean);
    let opts = terms.map(function (t) { return '<option value="' + escapeHtml(t) + '">' + escapeHtml(t) + '</option>'; }).join('');
    return ''
        + '<div style="font-size:0.75rem;color:var(--color-text-muted);margin-bottom:0.375rem;">填写反馈（CTCAE 分级：显式等级优先，其次严重度）</div>'
        + '<div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;">'
        + '<select class="select" id="fu-term-' + task.task_id + '" style="width:auto;">' + (opts || '<option value="不良反应">不良反应</option>') + '</select>'
        + '<select class="select" id="fu-grade-' + task.task_id + '" style="width:auto;">'
        + '<option value="">按严重度判定</option>'
        + '<option value="1">1 级</option><option value="2">2 级</option>'
        + '<option value="3">3 级</option><option value="4">4 级</option><option value="5">5 级</option>'
        + '</select>'
        + '<select class="select" id="fu-sev-' + task.task_id + '" style="width:auto;">'
        + '<option value="">严重度</option><option value="轻度">轻度</option><option value="中度">中度</option>'
        + '<option value="重度">重度</option><option value="危及生命">危及生命</option>'
        + '</select>'
        + '<input class="input" id="fu-text-' + task.task_id + '" style="flex:1;min-width:160px;" placeholder="补充描述（可选）">'
        + '<button class="btn btn-primary btn-sm" data-submit="' + escapeHtml(task.task_id) + '">提交</button>'
        + '</div>';
}

function submitFollowupRecord(taskId) {
    const termSel = document.getElementById('fu-term-' + taskId);
    const gradeSel = document.getElementById('fu-grade-' + taskId);
    const sevSel = document.getElementById('fu-sev-' + taskId);
    const textInput = document.getElementById('fu-text-' + taskId);

    const item = { term: termSel ? termSel.value : '' };
    if (gradeSel && gradeSel.value) item.grade = parseInt(gradeSel.value, 10);
    if (sevSel && sevSel.value) item.severity = sevSel.value;
    if (textInput && textInput.value.trim()) item.text = textInput.value.trim();

    api.post('/followup/record', { task_id: taskId, responses: [item] }).then(function (resp) {
        if (!resp || !resp.success) { alert((resp && resp.message) || '提交失败'); return; }
        const d = resp.data;
        let msg = '已记录，CTCAE 等级：' + (d.grade_label || '未分级');
        if (d.alerts && d.alerts.length) {
            msg += '\n⚠️ 触发预警：' + d.alerts.map(function (a) { return a.term + '（' + a.level_label + '）'; }).join('、');
        }
        alert(msg);
        refreshFollowupTasks();
    }).catch(function (err) { alert('提交失败：' + err.message); });
}

// 提交反馈后刷新任务状态（并同步到期标记），避免用旧状态渲染
function refreshFollowupTasks() {
    const plan = _fuState.plan;
    if (!plan || !plan.case_id) { renderFollowup(); return; }
    api.get('/followup/tasks', { case_id: plan.case_id }).then(function (resp) {
        if (resp && resp.success && resp.data && resp.data.tasks && resp.data.tasks.length) {
            _fuState.plan.tasks = resp.data.tasks;
        }
        renderFollowup();
    }).catch(function () { renderFollowup(); });
}

function loadFollowupAlerts() {
    const box = document.getElementById('fu-alerts');
    if (!box) return;
    api.get('/followup/alerts').then(function (resp) {
        if (!resp || !resp.success) return;
        const d = resp.data;
        if (!d || !d.total) { box.innerHTML = '<div class="card" style="padding:1rem;"><div style="font-weight:600;">异常预警</div><div style="font-size:0.8125rem;color:var(--color-text-muted);margin-top:0.375rem;">暂无预警</div></div>'; return; }
        let html = '<div class="card" style="padding:1rem;"><div style="font-weight:600;margin-bottom:0.5rem;">异常预警（' + d.total + '）</div>';
        d.alerts.forEach(function (a) {
            const badge = a.level === 'emergency' ? 'badge-warning' : 'badge-info';
            html += '<div style="font-size:0.8125rem;margin-bottom:0.375rem;">';
            html += '<span class="badge ' + badge + '">' + escapeHtml(a.grade_label || '') + '</span> ';
            html += escapeHtml(a.term || '') + ' — ' + escapeHtml(a.level_label || '');
            html += '<span style="color:var(--color-text-muted);">（' + escapeHtml(a.timepoint || '') + '，' + escapeHtml(a.created_at || '') + '）</span>';
            html += '</div>';
        });
        html += '</div>';
        box.innerHTML = html;
    }).catch(function () { /* 静默 */ });
}
