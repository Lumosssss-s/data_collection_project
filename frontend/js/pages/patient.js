/**
 * 患者端 H5（NM-06）
 * 路由：#/patient（首页）、#/patient/preconsult、#/patient/disease/{id}、
 *       #/patient/followup、#/patient/drug（药品搜索；详情已迁 #/drugs/{drug_id}，旧 hash 重定向）
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
.pt-wrap { max-width: var(--content-max); margin: 0 auto; }
.pt-title { font-size: var(--text-xl); font-weight: 700; margin-bottom: var(--gap-item); }
.pt-sub { color: var(--color-text-muted); font-size: var(--text-base); margin-bottom: var(--gap-section); line-height: 1.7; }
/* ===== 首页四个同款入口块（左 6px 主色条 + 文案 + CTA + 右侧真实统计）=====
   同款判据：四块共用同一组规则，标签 12px、标题 18px/600、说明 13px、内边距与行高完全一致；
   任何块都不得出现大面积实色（首块仅用 --color-primary-soft 作底色区分）。 */
.pt-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; }
.pt-row { position: relative; display: flex; align-items: center; gap: var(--space-4); min-height: 160px;
  padding: 0 var(--space-5) 0 0; overflow: hidden;
  border: 1px solid var(--color-border); border-radius: var(--radius-md);
  background: var(--color-surface); color: inherit; text-decoration: none;
  transition: border-color var(--dur-fast) ease, box-shadow var(--dur-fast) ease, transform var(--dur-fast) ease; }
.pt-row:hover { border-color: var(--color-primary); box-shadow: var(--shadow-raised); }
.pt-row:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { .pt-row { transition: none; } }
/* 首块只换底色，不改任何排版属性 */
.pt-row.is-primary { background: var(--color-primary-soft); }
.pt-row-bar { flex: 0 0 6px; align-self: stretch; background: var(--color-primary); }
.pt-row-copy { flex: 0 1 46em; min-width: 0; display: flex; flex-direction: column; gap: 3px;
  padding: var(--space-4) 0; }
.pt-row-label { font-size: var(--text-xs); line-height: 1.5; color: var(--color-text-muted); }
.pt-row-title { font-size: var(--text-lg); font-weight: 600; line-height: 1.4; color: var(--color-text); }
/* 说明统一 secondary（muted 压 soft 仅 4.15:1，不达 AA）；46em ≈ 46 个中文字宽 */
.pt-row-desc { font-size: var(--text-sm); line-height: 1.65; color: var(--color-text-secondary);
  max-width: 46em; }
/* CTA：显式 flex 双轴居中，高度写死 44px，不靠 line-height；R1 起固定在文案正下方 */
.pt-row-cta { align-self: flex-start; display: inline-flex; align-items: center; justify-content: center;
  min-height: 44px; margin-top: 10px; padding: 0 var(--space-4); border-radius: var(--radius-md);
  font-size: var(--text-base); font-weight: 600; white-space: nowrap; }
.pt-row.is-primary .pt-row-cta { background: var(--color-primary); color: var(--color-on-primary); }
.pt-row:not(.is-primary) .pt-row-cta { background: var(--color-surface);
  color: var(--color-primary-text); border: 1px solid var(--color-primary); }
.pt-row-stats { flex: 0 0 auto; display: flex; align-items: center; gap: var(--space-4);
  min-width: 220px; margin-left: auto; padding-left: var(--space-4);
  border-left: 1px solid var(--color-border); }
.pt-row-stat { display: flex; flex-direction: column; gap: 2px; min-width: 64px; }
.pt-row-stat .n { font-size: 1.375rem; font-weight: 600; font-variant-numeric: tabular-nums;
  line-height: 1.2; color: var(--color-text); }
.pt-row-stat .l { font-size: var(--text-xs); line-height: 1.4; color: var(--color-text-muted); }
.pt-row-note { font-size: var(--text-xs); line-height: 1.55; color: var(--color-text-muted);
  max-width: 200px; }

/* ===== 区段编号 + 索引概览带（常显，不随配色变化）===== */
.pt-section-head { display: flex; align-items: baseline; gap: var(--space-2); margin: 0 0 var(--space-3); }
.pt-section-no { font-family: var(--font-mono); font-size: var(--text-xs); color: var(--color-text-muted); }
.pt-section-name { font-size: var(--text-sm); font-weight: 600; color: var(--color-text-secondary); }

.pt-overview { margin-bottom: var(--gap-block); }
.pt-overview-head { display: flex; align-items: baseline; justify-content: space-between;
  margin-bottom: var(--space-2); }
.pt-overview-title { font-size: var(--text-sm); font-weight: 600; color: var(--color-text-secondary); }
.pt-overview-total { font-family: var(--font-mono); font-size: var(--text-xs); color: var(--color-text-muted); }
.pt-band { display: flex; height: 10px; border-radius: 3px; overflow: hidden;
  background: var(--color-bg); }
.pt-band-seg { height: 100%; }
/* 术语段不用第 5 种颜色，改用斜纹：形状区分，避免与数据类型色混淆 */
.pt-band-seg.is-hatch { background: repeating-linear-gradient(45deg,
  var(--dtype-term) 0, var(--dtype-term) 2px,
  var(--dtype-term-bg) 2px, var(--dtype-term-bg) 4px); }
.pt-legend { display: flex; flex-wrap: wrap; gap: var(--space-3); margin-top: var(--space-2); }
.pt-legend-item { display: inline-flex; align-items: center; gap: 6px;
  font-size: var(--text-xs); color: var(--color-text-muted); }
.pt-legend-swatch { width: 8px; height: 8px; border-radius: 2px; }
.pt-legend-swatch.is-hatch { background: repeating-linear-gradient(45deg,
  var(--dtype-term) 0, var(--dtype-term) 1px,
  var(--dtype-term-bg) 1px, var(--dtype-term-bg) 3px); }
@media (max-width: 1023px) {
  /* 窄屏：文案独占一行，统计落到底部一行 */
  .pt-row { flex-wrap: wrap; align-items: flex-start; padding: var(--space-4) var(--space-4) var(--space-4) 0; }
  .pt-row-copy { flex: 1 1 60%; padding: 0; }
  .pt-row-cta { margin: var(--space-3) 0 0 0; }
  .pt-row-stats { flex: 1 1 100%; min-width: 0; margin-top: var(--space-3);
    padding: var(--space-3) 0 0 0; border-left: 0; border-top: 1px solid var(--color-border); }
}
.pt-card { display: block; text-decoration: none; color: inherit; min-height: 140px;
  padding: var(--space-5) var(--space-4); border-radius: var(--radius-md);
  border: 1px solid var(--color-border); background: var(--color-surface);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease; }
.pt-card:hover { border-color: var(--color-primary); transform: translateY(-2px); box-shadow: var(--shadow-raised); }
.pt-card:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { .pt-card { transition: none; } .pt-card:hover { transform: none; } }
/* 图标加底衬（四色取既有语义色板），图标尺寸放大到 44 底衬 / 20 图形 */
.pt-card-icon { width: 44px; height: 44px; border-radius: var(--radius-md); margin-bottom: var(--space-3);
  display: flex; align-items: center; justify-content: center; }
.pt-ico-primary { background: var(--color-primary-soft); color: var(--color-primary); }
.pt-ico-info { background: var(--color-info-bg); color: var(--color-info); }
.pt-ico-success { background: var(--color-success-bg); color: var(--color-success); }
.pt-ico-warning { background: var(--color-warning-bg); color: var(--color-warning); }
/* 标题/说明两级字号：18px 标题 vs 13px 说明，拉开层级 */
.pt-card h3 { font-size: var(--text-lg); font-weight: 600; margin-bottom: var(--space-2); line-height: 1.35; }
.pt-card p { font-size: var(--text-sm); color: var(--color-text-muted); line-height: 1.65; margin: 0; }
.pt-btn { display: block; width: 100%; padding: 0.875rem 1rem; text-align: center; font-size: var(--text-md); border-radius: var(--radius-md);
  border: none; background: var(--color-primary); color: var(--color-on-primary); cursor: pointer; margin-bottom: var(--space-2); }
.pt-btn.pt-ghost { background: var(--color-surface); color: var(--color-text); border: 1px solid var(--color-border); }
.pt-input, .pt-textarea { width: 100%; padding: 0.875rem 1rem; font-size: var(--text-md); border-radius: var(--radius-md);
  border: 1px solid var(--color-border); background: var(--color-surface); color: var(--color-text); }
.pt-textarea { min-height: 120px; resize: vertical; }
.pt-chat { border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: var(--space-4); min-height: 260px;
  max-height: 60vh; overflow-y: auto; background: var(--color-surface); }
.pt-msg { font-size: var(--text-md); line-height: 1.7; padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); margin-bottom: 0.625rem; }
.pt-msg.user { background: var(--color-primary); color: var(--color-on-primary); margin-left: 12%; }
.pt-msg.bot { background: var(--color-bg); margin-right: 12%; }
.pt-msg.warn { background: var(--color-warning-bg); color: var(--color-warning); font-size: 0.9375rem; }
.pt-msg.tip { background: transparent; border: 1px dashed var(--color-border); color: var(--color-text-muted); font-size: var(--text-sm); }
/* 免责声明：13px + muted + 上方细分隔线，可见但不抢焦点（不删合规文案） */
.pt-notice { margin-top: var(--gap-section); padding: var(--space-3) 0 0;
  border-top: 1px solid var(--color-border);
  background: transparent; color: var(--color-text-muted); font-size: var(--text-sm); line-height: 1.7; }
.pt-back { display: inline-block; margin-bottom: var(--gap-item); font-size: 0.9375rem; color: var(--color-primary); cursor: pointer; }
.pt-section { border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: 0.875rem 1rem; margin-bottom: var(--gap-item); }
.pt-section h4 { font-size: var(--text-md); margin-bottom: var(--space-1); }
.pt-section p { font-size: 0.9375rem; line-height: 1.8; color: var(--color-text-secondary); margin: 0; white-space: pre-wrap; }
/* 说明书原文相互作用折叠块：默认收起，原生 details 无额外依赖 */
.pt-rawix { border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: 0.875rem 1rem; margin-bottom: var(--gap-item); background: var(--color-surface); }
.pt-rawix summary { cursor: pointer; font-size: var(--text-md); font-weight: 600; color: var(--color-primary-text); line-height: 1.6; }
.pt-rawix summary:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.pt-rawix-list { margin: var(--space-3) 0 0; padding-left: 1.5rem; }
.pt-rawix-list li { font-size: 0.875rem; line-height: 1.7; color: var(--color-text-secondary); margin-bottom: var(--space-2); }
.pt-rawix-note { margin: var(--space-3) 0 0; padding-top: var(--space-2); border-top: 1px dashed var(--color-border); font-size: var(--text-xs); color: var(--color-text-muted); line-height: 1.7; }
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
    // 药品详情已迁至 #/drugs/{id}（归属疾病知识库组）；旧 hash 重定向兼容，
    // 不再在此渲染，避免页面 key 被截断为 patient 导致高亮跳「患者概览」。
    else if (seg[0] === 'drug' && seg[1]) { window.location.replace('#/drugs/' + seg[1]); }
    else if (seg[0] === 'drug') renderPatientDrug(container, '');
    else renderPatientHome(container);
});

// ============================================================
//  患者概览：随访任务 + 预警（零 token 接口）
//  GET /followup/tasks · GET /followup/alerts · GET /stats/full_dashboard
// ============================================================
function renderPatientHome(container) {
    const today = new Date();
    const todayText = today.getFullYear() + ' 年 ' + (today.getMonth() + 1) + ' 月 ' + today.getDate() + ' 日';

    container.innerHTML = ptShell(
        '<section class="d2-hero"><div class="d2-hero-inner">'
        + '<p class="d2-kicker">患者概览 · ' + todayText + '</p>'
        + '<h1 class="d2-h1" id="pt-hero-h1">正在读取随访安排…</h1>'
        + '<p class="d2-sub" id="pt-hero-sub">数据来自随访任务与预警接口。</p>'
        + '<div class="meter" style="margin-top:1rem;"><i id="pt-hero-meter" style="width:0%"></i></div>'
        + '<p class="d2-kicker" id="pt-hero-progress" style="margin-top:0.5rem;">—</p>'
        + '</div></section>'

        + '<div class="d2-today-grid">'
        + '<div>'
        +   '<div class="card"><div class="card-title">接下来的随访节点</div>'
        +     '<div id="pt-nodes" style="margin-top:0.5rem;">'
        +       '<p class="d2-sub">读取中…</p>'
        +     '</div></div>'
        +   '<div class="card"><div class="card-title">现在可以做什么</div>'
        +     '<div class="d2-quick" style="margin-top:0.75rem;">'
        +       '<a class="d2-quick-item" href="#/qa"><div><div class="d2-quick-title">问一句</div>'
        +         '<div class="d2-quick-desc">把担心的事说清楚，答案标注出处</div></div></a>'
        +       '<a class="d2-quick-item" data-tone="info" href="#/search"><div><div class="d2-quick-title">查一查</div>'
        +         '<div class="d2-quick-desc">指南原文与推荐条目</div></div></a>'
        +       '<a class="d2-quick-item" data-tone="accent" href="#/disease/DIS-LUNG-001"><div><div class="d2-quick-title">我的病</div>'
        +         '<div class="d2-quick-desc">疾病档案、相关药品</div></div></a>'
        +       '<a class="d2-quick-item" data-tone="warn" href="#/report"><div><div class="d2-quick-title">看报告</div>'
        +         '<div class="d2-quick-desc">粘贴报告文字，整理关键指标</div></div></a>'
        +     '</div></div>'
        +   '<div class="card"><div class="card-title">知识库规模</div>'
        +     '<div id="pt-overview"></div></div>'
        + '</div>'

        + '<aside>'
        +   '<div class="card"><div class="card-title">需要留意</div><div id="pt-alerts" style="margin-top:0.5rem;"></div></div>'
        +   '<div class="card"><div class="card-title">当前随访计划</div>'
        +     '<div class="d2-quick" style="grid-template-columns:repeat(2,minmax(0,1fr));margin-top:0.75rem;">'
        +       '<div class="d2-metric"><div class="v" id="pt-m-total">—</div><div class="k">节点总数</div></div>'
        +       '<div class="d2-metric"><div class="v" id="pt-m-done">—</div><div class="k">已完成</div></div>'
        +       '<div class="d2-metric"><div class="v" id="pt-m-due">—</div><div class="k">已到期</div></div>'
        +       '<div class="d2-metric"><div class="v" id="pt-m-alert">—</div><div class="k">预警条数</div></div>'
        +     '</div>'
        +   '</div>'
        + '</aside>'
        + '</div>'
    );

    loadToday(container);
    loadHomeStats(container);
}

// 随访任务 + 预警：两路并行，任一失败不影响另一块渲染
function loadToday(container) {
    const nodesEl = container.querySelector('#pt-nodes');
    const alertsEl = container.querySelector('#pt-alerts');

    Promise.all([
        api.get('/followup/tasks').catch(function (e) { return { __err: e.message }; }),
        api.get('/followup/alerts').catch(function (e) { return { __err: e.message }; })
    ]).then(function (res) {
        const tResp = res[0] || {};
        const aResp = res[1] || {};

        // ---- 任务 ----
        const tasks = (tResp.data && tResp.data.tasks) || [];
        const total = (tResp.data && tResp.data.total) || 0;
        const dueCount = (tResp.data && tResp.data.due_count) || 0;
        const doneCount = tasks.filter(function (t) { return t.status === 'done'; }).length;

        const hero = container.querySelector('#pt-hero-h1');
        const sub = container.querySelector('#pt-hero-sub');
        const meter = container.querySelector('#pt-hero-meter');
        const prog = container.querySelector('#pt-hero-progress');

        if (tResp.__err) {
            hero.textContent = '随访任务暂时读不到';
            sub.textContent = '接口错误：' + tResp.__err;
            nodesEl.innerHTML = '<p class="d2-sub">暂时无法读取随访安排，请稍后重试。</p>';
        } else if (!tasks.length) {
            hero.innerHTML = '今天没有到期的随访任务。';
            sub.textContent = '当前病例尚未生成随访计划，可在「随访」页按癌种与阶段生成。';
            nodesEl.innerHTML = emptyState('还没有随访节点');
        } else {
            hero.innerHTML = dueCount > 0
                ? '今天有 <em>' + dueCount + '</em> 件事需要处理，其余按计划进行。'
                : '今天没有到期的随访任务，按计划继续即可。';
            sub.textContent = '当前计划共 ' + total + ' 个节点，数据来自随访任务接口。';

            const pct = total ? Math.round(doneCount / total * 100) : 0;
            meter.style.width = pct + '%';
            prog.textContent = '已完成 ' + doneCount + ' / ' + total + '（' + pct + '%）';

            nodesEl.innerHTML = todayNodesHtml(tasks);
        }

        // ---- 指标 ----
        const setTxt = function (id, v) {
            const el = container.querySelector('#' + id);
            if (el) el.textContent = String(v);
        };
        setTxt('pt-m-total', tResp.__err ? '—' : total);
        setTxt('pt-m-done', tResp.__err ? '—' : doneCount);
        setTxt('pt-m-due', tResp.__err ? '—' : dueCount);

        // ---- 预警 ----
        const alerts = (aResp.data && aResp.data.alerts) || [];
        const alertTotal = (aResp.data && aResp.data.total) || 0;
        setTxt('pt-m-alert', aResp.__err ? '—' : alertTotal);

        if (aResp.__err) {
            alertsEl.innerHTML = '<p class="d2-sub">预警接口错误：' + escapeHtml(aResp.__err) + '</p>';
        } else if (!alerts.length) {
            alertsEl.innerHTML = '<div class="alert alert-success">'
                + '<strong>暂无预警</strong>：预警列表为空（0 条）。</div>';
        } else {
            let html = '';
            alerts.slice(0, 3).forEach(function (a) {
                const lv = a.level === 'emergency' ? 'alert-error' : 'alert-warning';
                html += '<div class="' + lv + '" style="margin-bottom:0.5rem;">'
                    + '<strong>' + escapeHtml(a.grade_label || '预警') + '</strong> · '
                    + escapeHtml(a.term || '')
                    + '<br><span style="font-size:0.75rem;">' + escapeHtml(a.level_label || '')
                    + (a.timepoint ? '（' + escapeHtml(a.timepoint) + '）' : '') + '</span></div>';
            });
            alertsEl.innerHTML = html;
        }
    });
}

// 节点列表：日期一律 YYYY-MM-DD（跨度跨年，缺年份无法分辨）
function todayNodesHtml(tasks) {
    const sorted = tasks.slice().sort(function (a, b) {
        return String(a.due_date || '') < String(b.due_date || '') ? -1 : 1;
    });
    let nextId = null;
    for (let i = 0; i < sorted.length; i++) {
        if (sorted[i].status !== 'done') { nextId = sorted[i].task_id; break; }
    }
    let html = '';
    sorted.slice(0, 5).forEach(function (t) {
        const isNext = nextId && t.task_id === nextId;
        const items = (t.items || []).join(' · ') || '（无检查项目）';
        html += '<div class="d2-node' + (isNext ? ' is-next' : '') + '">'
            + '<div class="d2-node-date">' + escapeHtml(t.due_date || '—') + '</div>'
            + '<div class="d2-node-main">'
            + '<div class="d2-node-title">' + escapeHtml(t.timepoint || '随访节点')
            + (isNext ? '<span class="d2-node-tag">下一项</span>' : '')
            + '</div>'
            + '<div class="d2-node-meta">' + escapeHtml(items) + '</div>'
            + '</div></div>';
    });
    if (sorted.length > 5) {
        html += '<p class="d2-sub" style="margin-top:0.5rem;">另有 ' + (sorted.length - 5) + ' 个节点，见「随访」页完整时间轴。</p>';
    }
    return html;
}


/* 比例条 5 段：改用与 D2 同族的青/暖褐阶梯（原 dtype 色为靛蓝族，与暖灰绿底冲突）。
   术语段用斜纹而非第 5 种颜色，形状区分。 */
const PT_TYPES = [
    { key: 'doc', label: '指南文档', color: '#1F4F55' },
    { key: 'rec', label: '推荐条目', color: '#2E6360' },
    { key: 'term', label: '术语', color: '#566B5F', hatch: true },
    { key: 'drug', label: '药品说明书', color: '#6E7F63' },
    { key: 'literature', label: '文献', color: '#8C7A63' },
];
/* 文献条数：无任何接口暴露（/stats 与 /stats/full_dashboard 的 overview 均无 literature 字段，
   nginx 也没有 ES 代理），浏览器无法直连 9201。此处取现场 ES 聚合快照：
   POST /medical_knowledge/_search  {"size":0,"aggs":{"dt":{"terms":{"field":"data_type"}}}}
   → literature 2076 / rec 1816 / term 377 / drug 27 / doc 8。取不到新值时用它，不做估算。 */
const PT_LITERATURE_SNAPSHOT = 2076;

/* 知识库规模只取真实接口：GET /api/v1/stats/full_dashboard → data.overview
   取不到就不画，不写死、不编造 */
function loadHomeStats(container) {
    api.get('/stats/full_dashboard').then(function (resp) {
        const o = resp && resp.data && resp.data.overview;
        if (!o) return;
        renderOverview(container, {
            doc: o.total_docs,
            rec: o.total_recs,
            term: o.total_terms,
            drug: o.total_drugs,
            literature: PT_LITERATURE_SNAPSHOT
        });
    }).catch(function () { /* 统计不可用时保持占位符，比例条留空 */ });
}

/* 构成比例条：值为 0 的类型不画（不出现 0 宽假段） */
function renderOverview(container, vals) {
    const el = container.querySelector('#pt-overview');
    if (!el) return;
    const items = PT_TYPES
        .map(function (t) { return { key: t.key, label: t.label, color: t.color, hatch: t.hatch, v: Number(vals[t.key] || 0) }; })
        .filter(function (t) { return t.v > 0; });
    if (!items.length) return;
    const total = items.reduce(function (a, b) { return a + b.v; }, 0);

    let segs = '';
    let legend = '';
    items.forEach(function (t) {
        const pct = (t.v / total) * 100;
        const swatch = t.hatch
            ? '<span class="pt-legend-swatch is-hatch"></span>'
            : '<span class="pt-legend-swatch" style="background:' + t.color + '"></span>';
        const seg = t.hatch
            ? '<span class="pt-band-seg is-hatch" style="width:' + pct.toFixed(2) + '%" title="' + t.label + ' ' + t.v + '"></span>'
            : '<span class="pt-band-seg" style="width:' + pct.toFixed(2) + '%;background:' + t.color + '" title="' + t.label + ' ' + t.v + '"></span>';
        segs += seg;
        legend += '<span class="pt-legend-item">' + swatch + t.label
            + ' <strong>' + t.v.toLocaleString() + '</strong></span>';
    });

    el.innerHTML = '<div class="pt-overview-head">'
        + '<span class="pt-overview-title">索引构成</span>'
        + '<span class="pt-overview-total">共 ' + total.toLocaleString() + ' 条</span>'
        + '</div>'
        + '<div class="pt-band" role="img" aria-label="索引条目构成比例">' + segs + '</div>'
        + '<div class="pt-legend">' + legend + '</div>';
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
            ptMsg('warn', '注意：' + (f.action || '建议尽快就医'));
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
//  药品库（复用 NM-06）
// ============================================================
function renderPatientDrug(container, drugId) {
    if (!drugId) {
        container.innerHTML = ptShell(
            ptBack('')
            + '<h1 class="pt-title">药品库</h1>'
            + '<p class="pt-sub">说明书适应证、警示与相互作用</p>'
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
    // 两段式：结构化接口零 LLM 立即渲染；白话块占位后异步取 /plain 填充
    api.get('/patient/drug/' + encodeURIComponent(drugId)).then(function (resp) {
        if (!resp || !resp.success) { showError(box, (resp && resp.message) || '未找到该药品'); return; }
        renderPtDrugDetail(box, resp.data);
    }).catch(function (err) { showError(box, err.message); });
}

// 白话块异步填充；失败降级为提示（结构化要点已在下方，不丢内容）
function loadPtDrugPlain(box, drugId) {
    api.get('/patient/drug/' + encodeURIComponent(drugId) + '/plain').then(function (resp) {
        const el = box.querySelector('#pt-plain-box');
        if (!el) return;
        if (resp && resp.success && resp.data && resp.data.plain) {
            el.innerHTML = renderPlainSections(resp.data.plain);
        } else {
            el.innerHTML = '<div class="pt-section"><p>白话暂不可用，以下为说明书要点。</p></div>';
        }
    }).catch(function () {
        const el = box.querySelector('#pt-plain-box');
        if (el) el.innerHTML = '<div class="pt-section"><p>白话暂不可用，以下为说明书要点。</p></div>';
    });
}

function renderPlainSections(p) {
    let html = '';
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
    return html;
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
            html += '<a class="pt-card" style="margin-bottom:0.5rem;" href="#/drugs/' + encodeURIComponent(it.drug_id) + '">';
            html += '<h3>' + escapeHtml(it.generic_name || '') + '</h3>';
            if (it.brand_names && it.brand_names.length) html += '<p>商品名：' + escapeHtml(it.brand_names.join('、')) + '</p>';
            html += '</a>';
        });
        box.innerHTML = html;
    }).catch(function (err) { showError(box, err.message); });
}

function renderPtDrugDetail(box, d) {
    // 结构化渲染（零 LLM 接口数据）：先出要点；白话块占位，由 loadPtDrugPlain 异步填充
    let html = '<h1 class="pt-title">' + escapeHtml(d.generic_name || '') + '</h1>';
    if (d.brand_names && d.brand_names.length) {
        html += '<p class="pt-sub">商品名：' + escapeHtml(d.brand_names.join('、')) + '</p>';
    }

    // 黑框警示：置顶的醒目警示块（结构化字段，非 LLM 生成）
    if (d.has_boxed_warning && d.boxed_warning && d.boxed_warning.length) {
        html += '<div class="pt-section" style="border:1px solid rgba(140,59,46,0.45);background:rgba(140,59,46,0.06);">'
            + '<h4 style="color:#8C3B2E;">黑框警示</h4>'
            + d.boxed_warning.map(function (w) {
                return '<p>' + escapeHtml(((w && w.title) ? w.title + '：' : '') + String((w && w.text) || '').slice(0, 600)) + (String((w && w.text) || '').length > 600 ? '…' : '') + '</p>';
            }).join('')
            + '</div>';
    }

    if (d.indication_note) {
        html += '<div class="pt-section"><h4>适应证限定</h4><p>' + escapeHtml(d.indication_note) + '</p></div>';
    }

    // 白话占位块（异步填充）
    html += '<div id="pt-plain-box"><div class="pt-section"><p>正在生成白话解读…</p></div></div>';

    // 说明书要点（结构化，截断长文本防页面失控）
    if (d.dosage_standard) {
        const ds = String(d.dosage_standard);
        html += '<div class="pt-section"><h4>常规用法（说明书）</h4><p>' + escapeHtml(ds.slice(0, 400)) + (ds.length > 400 ? '…' : '') + '</p></div>';
    }
    if (d.contraindications && d.contraindications.length) {
        html += '<div class="pt-section"><h4>禁忌</h4><p>'
            + d.contraindications.map(function (c) { return escapeHtml(String(c).slice(0, 300)); }).join('<br>') + '</p></div>';
    }
    if (d.adverse_reactions && d.adverse_reactions.length) {
        html += '<div class="pt-section"><h4>不良反应（说明书摘录）</h4>'
            + d.adverse_reactions.slice(0, 5).map(function (a) {
                return '<p style="margin-bottom:0.5rem;"><strong>' + escapeHtml(String(a.term || '').slice(0, 150)) + '</strong>'
                    + (a.frequency ? '（' + escapeHtml(a.frequency) + '）' : '') + '</p>';
            }).join('') + '</div>';
    }

    // 说明书原文相互作用：默认收起的折叠层，逐条英文原文，仅供专业核对
    if (d.raw_interactions && d.raw_interactions.length) {
        html += '<details class="pt-rawix">'
            + '<summary>查看说明书原文相互作用（' + (d.interaction_count || d.raw_interactions.length) + ' 条）</summary>'
            + '<ol class="pt-rawix-list" lang="en">';
        d.raw_interactions.forEach(function (t) {
            html += '<li>' + escapeHtml(String(t == null ? '' : t)) + '</li>';
        });
        html += '</ol>'
            + '<p class="pt-rawix-note">原文为说明书英文法规措辞，仅供专业核对，不作为患者自行用药依据。</p>'
            + '</details>';
    }

    box.innerHTML = html;

    // 白话块异步填充（渲染末尾统一触发，#/patient/drug 与 #/drugs/{id} 两条路径共享）
    if (d.drug_id) loadPtDrugPlain(box, d.drug_id);
}
