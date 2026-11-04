/**
 * 我的病 · 疾病档案页（NM-01 / NM-06）
 * 路由：#/disease/{disease_id}
 * 数据：GET /diseases/{id}?version=patient｜GET /diseases/{id}?version=pro
 *       GET /patient/drugs?cancer_type=lung（相关药品，零 token）
 * 说明：无账号体系，本页展示的是「该疾病」的档案，不绑定任何个人分期/基因结果。
 */

// 疾病档案默认选择：localStorage → 肺癌
// 癌种 → 档案 id 映射必须与 D2_CANCER_LABELS 的键一一对应：
// 缺键会让切换按钮静默 return（2026-11-04 实测：乳腺癌/胃癌点击无响应即此因）。
// 四个档案均已在库（DIS-LUNG/COLORECTAL/BREAST/GASTRIC-001，pro 与 patient 版本均 200）。
const D2_DISEASE_KEY = 'd2_current_disease';
const D2_CANCER_LABELS = { lung: '肺癌', colorectal: '结直肠癌', breast: '乳腺癌', gastric: '胃癌' };
const D2_CANCER_DEFAULTS = { lung: 'DIS-LUNG-001', colorectal: 'DIS-COLORECTAL-001', breast: 'DIS-BREAST-001', gastric: 'DIS-GASTRIC-001' };

function getCurrentDiseaseId() {
    let saved = '';
    try { saved = localStorage.getItem(D2_DISEASE_KEY) || ''; } catch (e) { saved = ''; }
    return saved || D2_CANCER_DEFAULTS.lung;
}
function setCurrentDiseaseId(id) {
    try { localStorage.setItem(D2_DISEASE_KEY, id); } catch (e) { /* ignore */ }
}

// 共用视图：疾病详情（#/disease/{id}）与疾病档案（#/archive）复用同一渲染器，
// 不复制第二套页面；区别仅在 id 来源（hash vs localStorage）。
function renderDiseaseViewById(container, diseaseId) {
    if (!diseaseId) {
        container.innerHTML = '<div class="alert alert-warning">未选择疾病，请先从疾病库选择</div>'
            + '<button class="btn btn-secondary" onclick="goBackToDiseases()">← 返回疾病库</button>';
        return;
    }

    // 患者端入口默认「患者版」；专业版仍可切换
    let version = 'patient';
    container.innerHTML = '<div id="disease-detail-body"></div>';
    const body = document.getElementById('disease-detail-body');
    // 双版本缓存：进入时预取 pro/patient 两版（接口为纯数据装配，零 LLM），
    // 切换视角时直接读缓存重渲染，不再触发任何后端请求。
    const cache = {};

    function fetchVersion(v) {
        return api.get('/diseases/' + encodeURIComponent(diseaseId), { version: v }).then(function (resp) {
            if (resp && resp.success) cache[v] = resp.data;
            return resp;
        });
    }

    function load() {
        if (cache[version]) {
            renderDiseaseDetail(body, cache[version], version, function (v) {
                version = v;
                load();
            });
            return;
        }
        showLoading(body);
        fetchVersion(version).then(function (resp) {
            if (!resp || !resp.success) {
                showError(body, (resp && resp.message) || '加载失败（疾病档案可能尚未入库）');
                body.innerHTML += '<button class="btn btn-secondary" onclick="goBackToDiseases()">← 返回疾病库</button>';
                return;
            }
            renderDiseaseDetail(body, resp.data, version, function (v) {
                version = v;
                load();
            });
        }).catch(function (err) { showError(body, err.message); });
    }
    load();
    // 预取另一版本；失败不阻断（切换时回退为在线拉取）
    fetchVersion(version === 'patient' ? 'pro' : 'patient').catch(function () { /* noop */ });
}

registerPage('disease', function (container) {
    const hash = window.location.hash;
    renderDiseaseViewById(container, decodeURIComponent(hash.replace('#/disease/', '')));
});

// 疾病档案：独立 page key，复用同一视图；档案 id 取 localStorage（切换器行为不变）
registerPage('archive', function (container) {
    renderDiseaseViewById(container, getCurrentDiseaseId());
});

function goBackToDiseases() {
    window.location.hash = '#/diseases';
}

// 患者版溯源标注改写：【来源 …】→ 上标角标 [n]，本节末尾折叠对照表逐字保留原文。
// 同一章节内相同标注文本复用同一序号；跨章节重新计数。只用于患者版；
// 专业版保持就地标注（读者需要就地看到出处）。
// 输入为已 escapeHtml 的文本（【】为中文括号不经转义；标注内部若有 &<>" 已转义，
// 对照表直接使用转义后文本输出，展示上逐字一致且 XSS 安全）。
function renderPatientSectionWithRefs(escapedText) {
    const refMap = new Map();
    const refs = [];
    const body = escapedText.replace(/【来源 ([^】]+)】/g, function (m, inner) {
        let n = refMap.get(inner);
        if (n === undefined) { n = refs.length; refMap.set(inner, n); refs.push(inner); }
        return '<sup class="d2-ref">[' + (n + 1) + ']</sup>';
    });
    return { body, refs };
}

function renderRefsTable(refs) {
    if (!refs.length) return '';
    let html = '<details class="d2-refs"><summary>本节来源对照（' + refs.length + ' 条）</summary><ol>';
    refs.forEach(function (inner) {
        html += '<li>【来源 ' + inner + '】</li>';
    });
    html += '</ol></details>';
    return html;
}

function renderDiseaseDetail(container, d, version, onSwitch) {
    const name = d.name_canonical || d.disease_id || '未命名疾病';
    let html = '';

    // 单列文档流容器：hero 到免责全部纳入，保证左边缘对齐
    html += '<div class="d2-archive">';

    // ── 档案头 ──
    html += '<section class="d2-hero"><div class="d2-hero-inner">';
    html += '<button class="btn btn-ghost btn-sm" id="disease-back-btn" style="margin-bottom:0.75rem;">← 返回疾病库</button>';
    html += '<p class="d2-kicker">疾病档案 · 当前档案：' + escapeHtml(name) + '</p>';
    html += '<h1 class="d2-h1">' + escapeHtml(name) + '</h1>';
    // 视角切换器：桌面端绝对定位于 hero 右上角（见 d2.css .d2-view-switch-wrap），
    // 窄屏下沉为标题下方独立一行；高度 ≤28px，选中态用浅底+描边，不用实心大色块。
    html += '<div class="d2-view-switch-wrap">'
        + '<div class="d2-view-switch" role="group" aria-label="版本切换">'
        + '<button type="button" data-ver="patient"' + (version === 'patient' ? ' class="is-on" aria-pressed="true"' : ' aria-pressed="false"') + '>患者版</button>'
        + '<button type="button" data-ver="pro"' + (version === 'pro' ? ' class="is-on" aria-pressed="true"' : ' aria-pressed="false"') + '>专业版</button>'
        + '</div>'
        + '<p class="d2-view-note">' + (version === 'patient' ? '患者版：通俗表述' : '专业版：面向临床的结构化描述') + '</p>'
        + '</div>';
    if (d.name_en) html += '<p class="d2-sub">' + escapeHtml(d.name_en) + '</p>';
    html += '<div class="d2-profile-meta">';
    if (d.category_label) html += '<span class="badge badge-info">' + escapeHtml(d.category_label) + '</span>';
    if (d.cancer_type) html += '<span class="badge badge-muted">' + escapeHtml(d.cancer_type) + '</span>';
    if (d.icd10) html += '<span class="badge badge-muted">ICD-10 ' + escapeHtml(d.icd10) + '</span>';
    html += '<span class="badge badge-primary">' + (version === 'patient' ? '患者版' : '专业版') + '</span>';
    html += '</div>';
    if (d.departments && d.departments.length) {
        html += '<p class="d2-sub" style="margin-top:0.75rem;">就诊科室：' + escapeHtml(d.departments.join('、')) + '</p>';
    }
    html += '</div></section>';

    // ── 癌种切换器 ──
    html += '<div class="card" style="padding:0.75rem 1rem;">';
    html += '<div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;">';
    html += '<span style="font-size:0.8125rem;color:var(--color-text-secondary);margin-right:0.25rem;">切换档案：</span>';
    Object.keys(D2_CANCER_LABELS).forEach(function (code) {
        const label = D2_CANCER_LABELS[code];
        const active = d.cancer_type === code;
        html += '<button class="btn btn-sm ' + (active ? 'btn-primary' : 'btn-secondary') + '" data-cancer="' + code + '">' + label + '</button>';
    });
    html += '</div></div>';

    // ── 章节 ──
    html += '<div class="card"><div class="card-title">疾病档案</div>';
    if (!d.sections || !d.sections.length) {
        html += '<div style="margin-top:0.5rem;">' + emptyState('该疾病暂无可用内容（章节待入库）') + '</div>';
    } else {
        let lastGroup = '';
        d.sections.forEach(function (s, i) {
            if (s.group && s.group !== lastGroup) {
                html += '<p class="d2-kicker" style="margin-top:1rem;">' + escapeHtml(s.group) + '</p>';
                lastGroup = s.group;
            }
            const n = i + 1;
            let secBody;
            if (version === 'patient') {
                const r = renderPatientSectionWithRefs(escapeHtml(s.text || ''));
                secBody = '<p class="d2-sec-text">' + r.body + '</p>' + renderRefsTable(r.refs);
            } else {
                secBody = '<p class="d2-sec-text">' + escapeHtml(s.text || '') + '</p>';
            }
            html += '<div class="d2-sec">'
                + '<div class="d2-sec-head"><span class="d2-sec-no">' + (n < 10 ? '0' : '') + n + '</span>'
                + '<span class="d2-sec-name">' + escapeHtml(s.label || '（未命名章节）') + '</span></div>'
                + secBody
                + '</div>';
        });
    }
    html += '</div>';

    // ── 相关药品 ──
    html += '<div class="card"><div class="card-title">相关药品</div>'
        + '<p class="d2-sub" style="margin-top:0.25rem;">按当前癌种从药品说明书库匹配，点击查看患者版说明。</p>'
        + '<div id="d2-drug-box" class="d2-drug-list" style="margin-top:0.75rem;"><p class="d2-sub">读取中…</p></div></div>';

    // ── 来源 ──
    if (d.sources && d.sources.length) {
        html += '<div class="card"><div class="card-title">来源</div>'
            + '<div class="d2-src" style="margin-top:0.5rem;">' + escapeHtml(d.sources.join('；')) + '</div></div>';
    }

    // ── 免责声明 ──
    html += '<div class="card"><div class="alert alert-warning" style="margin:0;">'
        + escapeHtml(d.disclaimer || '本页信息仅供参考，不构成诊断，具体请遵医嘱。') + '</div></div>';

    html += '</div>';

    container.innerHTML = html;

    document.getElementById('disease-back-btn').addEventListener('click', goBackToDiseases);
    container.querySelectorAll('button[data-ver]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (btn.dataset.ver !== version) onSwitch(btn.dataset.ver);
        });
    });
    container.querySelectorAll('button[data-cancer]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const code = btn.dataset.cancer;
            const nextId = D2_CANCER_DEFAULTS[code];
            if (!nextId) return;
            setCurrentDiseaseId(nextId);
            if (getCurrentPage() === 'archive') {
                renderCurrentPage();  // 档案页内原地换档案，高亮保持患者服务组
            } else {
                window.location.hash = '#/disease/' + nextId;
            }
        });
    });

    loadDiseaseDrugs(container, d.cancer_type || '');
}

// 相关药品：GET /patient/drugs?cancer_type=xxx（零 token）
function loadDiseaseDrugs(container, cancerType) {
    const box = container.querySelector('#d2-drug-box');
    if (!box) return;
    api.get('/patient/drugs', cancerType ? { cancer_type: cancerType } : {}).then(function (resp) {
        if (!resp || !resp.success) { box.innerHTML = '<p class="d2-sub">药品列表暂时读不到。</p>'; return; }
        const d = resp.data || {};
        const items = (d.items || []).slice(0, 6);
        if (!items.length) {
            box.innerHTML = (d.degraded && d.note)
                ? '<p class="d2-sub">' + escapeHtml(d.note) + '</p>'
                : '<p class="d2-sub">暂无匹配药品。</p>';
            return;
        }
        let html = '';
        items.forEach(function (it) {
            const brands = (it.brand_names || []).filter(Boolean);
            html += '<a class="d2-drug" href="#/drugs/' + encodeURIComponent(it.drug_id) + '">'
                + '<div><div class="d2-drug-name">' + escapeHtml(it.generic_name || it.drug_id || '') + '</div>'
                + '<div class="d2-drug-meta">' + (brands.length ? escapeHtml(brands.join('、')) : '无商品名记录')
                + (it.cancer_type ? ' · ' + escapeHtml(it.cancer_type) : '') + '</div></div></a>';
        });
        if ((d.total || 0) > items.length) {
            html += '<p class="d2-sub" style="margin-top:0.5rem;">共 ' + d.total + ' 条，此处显示前 ' + items.length + ' 条。</p>';
        }
        box.innerHTML = html;
    }).catch(function (err) {
        box.innerHTML = '<p class="d2-sub">药品列表错误：' + escapeHtml(err.message) + '</p>';
    });
}
