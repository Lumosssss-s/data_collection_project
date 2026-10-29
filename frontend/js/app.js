/**
 * 肿瘤循证知识中枢 - 共享工具函数
 */

// Docker 环境：使用相对路径，通过 Nginx 反向代理到后端
// 本地开发调试时改为 'http://127.0.0.1:8001/api/v1'
const API_BASE = '/api/v1';

// ===== API 请求封装 =====
const api = {
    async get(path, params = {}) {
        const url = new URL(API_BASE + path, window.location.origin);
        Object.entries(params).forEach(([k, v]) => {
            if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
        });
        const resp = await fetch(url.toString());
        if (!resp.ok) throw new Error(`API错误: ${resp.status}`);
        return resp.json();
    },

    async post(path, body) {
        const resp = await fetch(API_BASE + path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        if (!resp.ok) throw new Error(`API错误: ${resp.status}`);
        return resp.json();
    },

    async streamPost(path, body, onChunk, onDoneOrError, onError) {
        const onDone = onError ? onDoneOrError : null;
        const onErr = onError || onDoneOrError;

        try {
            const resp = await fetch(API_BASE + path, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            if (!resp.ok) throw new Error(`API错误: ${resp.status}`);

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();
                for (const line of lines) {
                    const trimmed = line.trim();
                    if (trimmed.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(trimmed.slice(6));
                            onChunk(data);
                        } catch (e) { /* skip invalid JSON */ }
                    }
                }
            }

            if (onDone) onDone();
        } catch (e) {
            if (onErr) onErr(e.message);
        }
    }
};

// ===== 导航 =====
function navigate(page) {
    window.location.hash = '#/' + page;
}

function getCurrentPage() {
    const hash = window.location.hash.slice(2) || 'patient';
    // 提取页面名称（去掉参数部分，如 guideline/REC-LUNG-xxx -> guideline）
    const slashIndex = hash.indexOf('/');
    return slashIndex > 0 ? hash.substring(0, slashIndex) : hash;
}

// ===== 一级导航分组（侧栏只保留一级入口，组内页面以二级 Tab 切换）=====
const PAGE_GROUPS = {
    patient: {
        label: '患者服务',
        items: [
            { page: 'patient', label: '服务首页', href: '#/patient' },
            { page: 'preconsult', label: '智能预问诊', href: '#/preconsult' },
            { page: 'report', label: '报告解析', href: '#/report' },
            { page: 'followup', label: '智能随访', href: '#/followup' }
        ]
    },
    diseases: {
        label: '疾病知识',
        items: [
            { page: 'diseases', label: '疾病知识库', href: '#/diseases' },
            { page: 'kg', label: '肿瘤图谱', href: '#/kg' }
        ]
    },
    search: {
        label: '循证查询',
        items: [
            { page: 'search', label: '循证检索', href: '#/search' },
            { page: 'qa', label: '循证问答', href: '#/qa' },
            { page: 'topic', label: '跨癌种专题', href: '#/topic' },
            { page: 'compare', label: '癌种对比', href: '#/compare' }
        ]
    }
};

// 页面 → 所属一级分组
const PAGE_GROUP_MAP = {};
Object.keys(PAGE_GROUPS).forEach(function (groupKey) {
    PAGE_GROUPS[groupKey].items.forEach(function (item) {
        PAGE_GROUP_MAP[item.page] = groupKey;
    });
});

// 详情子页 → 所属一级分组
const SUB_PAGE_GROUP = { guideline: 'search', disease: 'diseases' };

// ===== 侧边栏激活状态 =====
function updateSidebarActive(page) {
    const groupKey = PAGE_GROUP_MAP[page] || SUB_PAGE_GROUP[page] || page;
    document.querySelectorAll('.sidebar-nav a').forEach(function (a) {
        a.classList.toggle('active', a.dataset.page === groupKey);
    });
}

// ===== 二级 Tab =====
function createGroupTabs(groupKey, activePage) {
    const group = PAGE_GROUPS[groupKey];
    const nav = document.createElement('nav');
    nav.className = 'group-tabs';
    nav.setAttribute('aria-label', group.label + '栏目');
    group.items.forEach(function (item) {
        const a = document.createElement('a');
        a.className = 'group-tab' + (item.page === activePage ? ' active' : '');
        a.href = item.href;
        a.textContent = item.label;
        if (item.page === activePage) a.setAttribute('aria-current', 'page');
        nav.appendChild(a);
    });
    return nav;
}

// ===== 工具函数 =====
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(dateStr) {
    if (!dateStr) return '-';
    const d = new Date(dateStr);
    return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' });
}

function showLoading(container) {
    container.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';
}

function showError(container, msg) {
    container.innerHTML = `<div class="alert alert-error">${escapeHtml(msg)}</div>`;
}

// 无数据空状态：仅表达「此处为空」；数据未就绪/降级仍用 .alert，两者语义不同
function emptyState(message) {
    return '<div class="empty-state">'
        + '<div class="empty-state-icon"></div>'
        + '<p>' + escapeHtml(message) + '</p>'
        + '</div>';
}

// ===== 简单的 Markdown 渲染 =====
function renderMarkdown(text) {
    if (!text) return '';

    // 1. 提前提取 Markdown 表格，避免被全局转义/换行处理破坏
    var tablePlaceholders = [];
    var placeholderPrefix = '##MARKDOWN_TABLE_';
    text = text.replace(/(^\s*\|[^\n]*\|\n?)+/gm, function(match) {
        var lines = match.trim().split('\n');
        var hasSeparator = lines.some(function(l) {
            return /^\s*\|(?:[-:|\s]+\|)+$/.test(l);
        });
        if (hasSeparator && lines.length >= 2) {
            var idx = tablePlaceholders.length;
            tablePlaceholders.push(renderMarkdownTable(lines));
            return placeholderPrefix + idx + '##';
        }
        return match;
    });

    // 2. 对其余文本进行 Markdown 渲染
    var html = escapeHtml(text);

    // 代码块
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    // 行内代码
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // 粗体
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // 斜体
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // 标题
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    // 无序列表
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
    // 引用
    html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
    // 换行
    html = html.replace(/\n\n/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');

    // 3. 恢复表格占位符
    tablePlaceholders.forEach(function(tableHtml, idx) {
        html = html.replace(placeholderPrefix + idx + '##', tableHtml);
    });

    var out = '<p>' + html + '</p>';
    // 纵深防御：正文已先经 escapeHtml 转义，此处再做一层 DOM 消毒；
    // DOMPurify 未加载（CDN 不可达）时降级为原始结果，行为与改造前一致。
    return (typeof DOMPurify !== 'undefined') ? DOMPurify.sanitize(out) : out;
}

// 将 Markdown 表格行数组渲染为 HTML 表格
function renderMarkdownTable(lines) {
    // 过滤分隔行，保留表头和数据行
    var rows = lines.filter(function(l) {
        return !/^\s*\|(?:[-:|\s]+\|)+$/.test(l);
    });
    if (rows.length === 0) return '';

    // 按首行确定期望列数
    var firstCells = parseMarkdownTableRow(rows[0]);
    var expectedCols = firstCells.length;
    if (expectedCols === 0) return '';

    var html = '<table class="markdown-table" style="border-collapse:collapse;width:100%;margin:1rem 0;font-size:0.875rem;">';
    rows.forEach(function(row, idx) {
        var cells = parseMarkdownTableRow(row, expectedCols);
        var tag = idx === 0 ? 'th' : 'td';
        var cellStyle = 'border:1px solid var(--color-border);padding:8px 12px;text-align:left;vertical-align:top;';
        if (idx === 0) {
            cellStyle += 'background:var(--color-bg);font-weight:600;';
        }
        html += '<tr>';
        cells.forEach(function(cell) {
            html += '<' + tag + ' style="' + cellStyle + '">' + escapeHtml(cell.trim()) + '</' + tag + '>';
        });
        html += '</tr>';
    });
    html += '</table>';
    return html;
}

// 解析单行 Markdown 表格，按期望列数合并多余单元格（处理单元格内容含 | 的情况）
function parseMarkdownTableRow(row, expectedCols) {
    // 去掉首尾 '|'，按 '|' 分割
    var raw = row.replace(/^\s*\|/, '').replace(/\|\s*$/, '');
    // 保护转义的 \|
    var escapedPipePlaceholder = '\x00PIPE\x00';
    raw = raw.replace(/\\\|/g, escapedPipePlaceholder);
    var cells = raw.split('|').map(function(c) { return c.replace(new RegExp(escapedPipePlaceholder, 'g'), '|'); });

    if (!expectedCols || cells.length <= expectedCols) {
        return cells;
    }
    // 单元格数超过期望列数：将多余部分合并到最后一列
    var merged = cells.slice(0, expectedCols - 1);
    merged.push(cells.slice(expectedCols - 1).join('|'));
    return merged;
}

// ===== 页面路由注册 =====
const pages = {};

function registerPage(name, renderFn) {
    pages[name] = renderFn;
}

function renderCurrentPage() {
    const page = getCurrentPage();
    updateSidebarActive(page);
    closeMobileNav();
    const container = document.getElementById('page-content');
    if (!container) return;

    container.innerHTML = '';
    const groupKey = PAGE_GROUP_MAP[page] || SUB_PAGE_GROUP[page];
    if (groupKey) {
        const activePage = PAGE_GROUP_MAP[page] ? page : SUB_PAGE_GROUP[page];
        container.appendChild(createGroupTabs(groupKey, activePage));
    }

    const body = document.createElement('div');
    body.className = 'page-body';
    container.appendChild(body);

    if (pages[page]) {
        pages[page](body);
    } else {
        body.innerHTML = '<div class="alert alert-warning">页面未找到</div>';
    }
}

// ===== 移动端抽屉导航 =====
function openMobileNav() {
    document.body.classList.add('mobile-nav-open');
    const overlay = document.getElementById('mobile-nav-overlay');
    if (overlay) overlay.classList.add('active');
}

function closeMobileNav() {
    document.body.classList.remove('mobile-nav-open');
    const overlay = document.getElementById('mobile-nav-overlay');
    if (overlay) overlay.classList.remove('active');
}

function setupMobileNav() {
    const toggle = document.getElementById('mobile-nav-toggle');
    const overlay = document.getElementById('mobile-nav-overlay');
    if (toggle) toggle.addEventListener('click', openMobileNav);
    if (overlay) overlay.addEventListener('click', closeMobileNav);
    // 点击侧栏内链接后自动收起
    document.querySelectorAll('.sidebar-nav a').forEach(function (a) {
        a.addEventListener('click', closeMobileNav);
    });
}

// 监听路由变化
window.addEventListener('hashchange', renderCurrentPage);
window.addEventListener('DOMContentLoaded', function () {
    setupMobileNav();
    renderCurrentPage();
});
