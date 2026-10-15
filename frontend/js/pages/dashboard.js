/**
 * 知识库运营看板页面（医疗，BE-14）
 *
 * 数据源：GET /stats（BE-14），返回：
 *   overview{total_docs,total_recs,total_terms,disease_profiles,cancer_type_count}
 *   cancer_type[{cancer_type,label_zh,doc_count,item_count}]
 *   topics[{topic,label_zh,count,by_data_type}]
 *   time_trend{group_by,data:[{period,total,by_cancer_type,cumulative_total,docs}]}
 *
 * 说明：「使用分析」（检索量/热门问题/未命中聚类）需检索日志采集，暂不提供。
 */
registerPage('dashboard', function (container) {
    container.innerHTML = `
        <h1 class="page-title">知识库运营看板</h1>
        <p class="page-desc">展示肿瘤循证知识库的整体规模、癌种覆盖、主题分布与指南发布时间趋势</p>
        <div id="dashboard-content"></div>
    `;

    const content = document.getElementById('dashboard-content');
    showLoading(content);

    api.get('/stats').then(function (data) {
        if (!data || !data.data) {
            showError(content, '暂无统计数据');
            return;
        }
        renderDashboard(content, data.data);
    }).catch(function (err) {
        showError(content, '获取统计数据失败: ' + err.message);
    });
});

// 医疗青蓝色板
const CHART_COLORS = ['#0E7490', '#1D7A8C', '#15803D', '#B45309', '#1E5E7A', '#0F766E', '#7C3AED', '#0B5D74'];
// 注意：页面脚本共享全局作用域，此处常量名需与 guideline-detail.js 中的
// DATA_TYPE_LABELS 区分，避免顶层 const 重复声明导致 SyntaxError。
const DASHBOARD_TYPE_LABELS = { doc: '指南', rec: '推荐条目', drug: '说明书', term: '术语' };

function renderDashboard(container, stats) {
    let html = '';

    // 维度一：核心运营指标
    const overview = stats.overview || {};
    html += '<h2 class="section-title">知识库概览</h2>';
    html += '<div class="stat-cards">';
    html += statCard('指南文档', overview.total_docs || 0);
    html += statCard('推荐条目', overview.total_recs || 0);
    html += statCard('术语', overview.total_terms || 0);
    html += statCard('疾病档案', overview.disease_profiles || 0);
    html += statCard('覆盖癌种', overview.cancer_type_count || 0);
    html += '</div>';

    // 维度二：癌种覆盖分布
    html += '<h2 class="section-title">癌种覆盖分布</h2>';
    html += '<div class="grid-2">';
    html += '<div class="card chart-card"><div class="card-title">指南数量分布</div><div style="height:250px;position:relative;"><canvas id="cancer-pie-chart"></canvas></div></div>';
    html += '<div class="card chart-card"><div class="card-title">推荐条目数量分布</div><div class="chart-scroll-wrap" style="height:250px;"><canvas id="cancer-bar-chart"></canvas></div></div>';
    html += '</div>';

    // 维度三：主题分类分布
    const topics = stats.topics || [];
    html += '<h2 class="section-title">主题分类分布</h2>';
    html += '<div class="grid-2">';
    html += '<div class="card chart-card"><div class="card-title">主题词云</div><div id="topic-wordcloud" style="height:350px;position:relative;overflow:hidden;"></div></div>';
    html += '<div class="card chart-card"><div class="card-title">主题 - 数据类型热力图</div><div id="topic-heatmap-wrap" class="chart-scroll-wrap"><canvas id="topic-heatmap"></canvas></div></div>';
    html += '</div>';

    // 维度四：指南发布时间趋势
    const timeTrend = stats.time_trend || {};
    html += '<h2 class="section-title">指南发布时间趋势</h2>';
    html += '<div class="grid-2">';
    html += '<div class="card chart-card"><div class="card-title">发布数量趋势</div><div class="chart-scroll-wrap" style="height:300px;"><canvas id="time-line-chart"></canvas></div></div>';
    html += '<div class="card chart-card"><div class="card-title">各时段癌种分布</div><div class="chart-scroll-wrap" style="height:300px;"><canvas id="time-bar-chart"></canvas></div></div>';
    html += '</div>';

    container.innerHTML = html;

    renderCancerTypeCharts(stats.cancer_type || []);
    renderTopicCharts(topics);
    renderTimeCharts(timeTrend);
}

function statCard(label, value) {
    return '<div class="stat-card"><div class="stat-value">' + value + '</div><div class="stat-label">' + label + '</div></div>';
}

// ===== 癌种覆盖 =====
function renderCancerTypeCharts(cancerTypes) {
    if (!cancerTypes.length) return;

    const labels = cancerTypes.map(function (c) { return c.label_zh || c.cancer_type; });

    const pieEl = document.getElementById('cancer-pie-chart');
    if (pieEl) {
        new Chart(pieEl.getContext('2d'), {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: cancerTypes.map(function (c) { return c.doc_count || 0; }),
                    backgroundColor: CHART_COLORS
                }]
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
        });
    }

    const barEl = document.getElementById('cancer-bar-chart');
    if (barEl) {
        new Chart(barEl.getContext('2d'), {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{ label: '推荐条目数', data: cancerTypes.map(function (c) { return c.item_count || 0; }), backgroundColor: '#0E7490' }]
            },
            options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } }
        });
    }
}

// ===== 主题分布 =====
// 字符级 Jaccard 相似度（用于词云去重）
function topicSimilarity(a, b) {
    const setA = new Set(a.replace(/\s+/g, ''));
    const setB = new Set(b.replace(/\s+/g, ''));
    let intersect = 0;
    const allChars = new Set([...setA, ...setB]);
    allChars.forEach(function (ch) { if (setA.has(ch) && setB.has(ch)) intersect++; });
    return allChars.size > 0 ? intersect / allChars.size : 0;
}

function selectRepresentativeTopics(topics, maxCount) {
    const sorted = topics.slice().sort(function (a, b) { return (b.count || 0) - (a.count || 0); });
    const selected = [];
    sorted.forEach(function (item) {
        const name = item.label_zh || item.topic || '';
        if (!name) return;
        const isSimilar = selected.some(function (s) {
            return topicSimilarity(name, s.label_zh || s.topic || '') >= 0.5;
        });
        if (!isSimilar) selected.push(item);
    });
    return selected.slice(0, maxCount);
}

function renderTopicCharts(topics) {
    const wordcloudEl = document.getElementById('topic-wordcloud');
    if (topics.length > 0) renderWordCloud(wordcloudEl, topics);
    else wordcloudEl.innerHTML = '暂无主题数据';

    // 热力图：主题 × 数据类型（by_data_type）
    const selectedTopics = selectRepresentativeTopics(topics, 10);
    const heatmapData = [];
    const topicsList = [];
    const typesSet = new Set();

    selectedTopics.forEach(function (item) {
        const topicName = item.label_zh || item.topic || '';
        const byType = item.by_data_type || {};
        topicsList.push(topicName);
        Object.keys(byType).forEach(function (t) {
            typesSet.add(t);
            heatmapData.push({ topic: topicName, axis: t, count: byType[t] });
        });
    });

    if (heatmapData.length > 0) {
        const canvas = document.getElementById('topic-heatmap');
        const wrap = document.getElementById('topic-heatmap-wrap');
        const types = Array.from(typesSet).map(function (t) { return DASHBOARD_TYPE_LABELS[t] || t; });
        const dataByDisplay = heatmapData.map(function (d) {
            return { topic: d.topic, axis: DASHBOARD_TYPE_LABELS[d.axis] || d.axis, count: d.count };
        });

        if (canvas && wrap) {
            setupHeatmapCanvas(canvas, wrap, topicsList.length, types.length);
            const ctx = canvas.getContext('2d');
            const width = parseInt(canvas.style.width || wrap.clientWidth, 10);
            const height = parseInt(canvas.style.height || wrap.clientHeight, 10);
            renderHeatmap(ctx, width, height, topicsList, types, dataByDisplay);
        }
    } else {
        const wrap = document.getElementById('topic-heatmap-wrap');
        if (wrap) wrap.innerHTML = '暂无主题数据';
    }
}

// 词云渲染（3D 视差版）
function renderWordCloud(container, topics) {
    container.innerHTML = '';

    const words = topics.slice(0, 30)
        .map(function (item) { return { text: item.label_zh || item.topic || '', weight: item.count || 1 }; })
        .filter(function (w) { return w.text; });
    if (words.length === 0) { container.innerHTML = '暂无主题数据'; return; }

    container.style.perspective = '800px';
    container.style.overflow = 'hidden';
    container.style.cursor = 'grab';
    container.style.position = 'relative';

    const maxWeight = Math.max.apply(null, words.map(function (w) { return w.weight; }));
    const minWeight = Math.min.apply(null, words.map(function (w) { return w.weight; }));
    const maxFontSize = 48;
    const minFontSize = 14;

    const tiltLayer = document.createElement('div');
    tiltLayer.style.cssText = 'position:relative;width:100%;height:100%;transform-style:preserve-3d;transition:transform 0.1s ease-out;';
    container.appendChild(tiltLayer);

    const cw = container.clientWidth || 600;
    const ch = 350;
    tiltLayer.style.height = ch + 'px';

    const centerX = cw / 2;
    const centerY = ch / 2;

    words.forEach(function (word, index) {
        const fontSize = minFontSize + (maxFontSize - minFontSize) * (word.weight - minWeight) / (maxWeight - minWeight || 1);

        const span = document.createElement('span');
        span.textContent = word.text;
        span.style.cssText = [
            'position:absolute', 'left:0', 'top:0',
            'font-size:' + fontSize + 'px',
            'font-weight:' + (word.weight > (maxWeight + minWeight) / 2 ? '700' : '500'),
            'font-family:"Noto Sans SC", "Microsoft YaHei", sans-serif',
            'white-space:nowrap',
            'color:' + CHART_COLORS[index % CHART_COLORS.length],
            'user-select:none',
            'pointer-events:none',
            'transform:translateZ(' + Math.round((fontSize - minFontSize) * 2) + 'px)',
            'text-shadow:0 1px 2px rgba(0,0,0,0.15),0 2px 6px rgba(0,0,0,0.06)',
        ].join(';');

        const temp = document.createElement('span');
        temp.style.cssText = 'visibility:hidden;position:absolute;font-size:' + fontSize + 'px;font-weight:700;font-family:"Noto Sans SC","Microsoft YaHei",sans-serif;white-space:nowrap;';
        temp.textContent = word.text;
        document.body.appendChild(temp);
        const tw = temp.offsetWidth || (word.text.length * fontSize * 0.7);
        document.body.removeChild(temp);
        const th = fontSize;

        let placed = false;
        const existing = tiltLayer.querySelectorAll('span');
        const existingRects = [];
        existing.forEach(function (el) {
            const l = parseFloat(el.style.left) || 0;
            const t = parseFloat(el.style.top) || 0;
            const fs = parseFloat(el.style.fontSize) || 14;
            existingRects.push({ x: l, y: t, w: el.offsetWidth || (el.textContent.length * fs * 0.7), h: fs });
        });

        for (let r = 0; r < 250 && !placed; r += 6) {
            for (let angle = 0; angle < Math.PI * 2 && !placed; angle += Math.PI / 10) {
                const x = centerX + r * Math.cos(angle) - tw / 2;
                const y = centerY + r * Math.sin(angle) - th / 2;
                if (x < 8 || x + tw > cw - 8 || y < 8 || y + th > ch - 8) continue;

                let collision = false;
                for (let i = 0; i < existingRects.length; i++) {
                    const p = existingRects[i];
                    if (x < p.x + p.w + 4 && x + tw + 4 > p.x && y < p.y + p.h + 4 && y + th + 4 > p.y) { collision = true; break; }
                }
                if (!collision) {
                    span.style.left = x + 'px';
                    span.style.top = y + 'px';
                    const distFromCenter = Math.sqrt(Math.pow(x + tw / 2 - centerX, 2) + Math.pow(y + th / 2 - centerY, 2));
                    const zBoost = Math.max(0, 1 - distFromCenter / (cw / 2)) * 20;
                    const zValue = Math.round((fontSize - minFontSize) * 2 + zBoost);
                    span.style.transform = 'rotate(' + (Math.random() * 4 - 2).toFixed(1) + 'deg) translateZ(' + zValue + 'px)';
                    tiltLayer.appendChild(span);
                    existingRects.push({ x: x, y: y, w: tw, h: th });
                    placed = true;
                }
            }
        }
        if (!placed) {
            span.style.left = Math.random() * (cw - tw - 20) + 10 + 'px';
            span.style.top = Math.random() * (ch - th - 20) + 10 + 'px';
            tiltLayer.appendChild(span);
        }
    });

    container.addEventListener('mousemove', function (e) {
        const rect = container.getBoundingClientRect();
        const x = (e.clientX - rect.left) / rect.width;
        const y = (e.clientY - rect.top) / rect.height;
        tiltLayer.style.transform = 'rotateX(' + ((y - 0.5) * -20).toFixed(1) + 'deg) rotateY(' + ((x - 0.5) * 20).toFixed(1) + 'deg)';
    });
    container.addEventListener('mouseleave', function () {
        tiltLayer.style.transform = 'rotateX(0deg) rotateY(0deg)';
    });
}

// ===== 热力图 Canvas =====
// 颜色阶：医疗青蓝（浅 -> 深）
const HEATMAP_COLOR_STOPS = [
    { threshold: 0.0, bg: '#F1F6F9', text: '#94A3B8' },
    { threshold: 0.2, bg: '#CCE7EE', text: '#0E5B70' },
    { threshold: 0.4, bg: '#8FCFDE', text: '#0A4553' },
    { threshold: 0.6, bg: '#3FA3BC', text: '#FFFFFF' },
    { threshold: 0.8, bg: '#1D7A8C', text: '#FFFFFF' },
    { threshold: 1.0, bg: '#0B4553', text: '#FFFFFF' },
];

function setupHeatmapCanvas(canvas, wrap, rowCount, colCount) {
    const dpr = window.devicePixelRatio || 1;
    const wrapWidth = Math.max(wrap.clientWidth, 300);
    const minCellHeight = 36;
    const minCellWidth = 60;
    const maxPlotWidth = Math.max(wrapWidth - 180, 500);
    const plotWidth = Math.min(Math.max(wrapWidth - 180, minCellWidth * colCount), maxPlotWidth);
    const maxPlotHeight = 600;
    const plotHeight = Math.min(Math.max(minCellHeight * rowCount, 200), maxPlotHeight);
    const width = plotWidth + 180;
    const height = plotHeight + 150;

    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    canvas.getContext('2d').setTransform(dpr, 0, 0, dpr, 0, 0);
}

function getHeatmapColor(ratio) {
    for (let i = HEATMAP_COLOR_STOPS.length - 1; i >= 0; i--) {
        if (ratio >= HEATMAP_COLOR_STOPS[i].threshold) return HEATMAP_COLOR_STOPS[i];
    }
    return HEATMAP_COLOR_STOPS[0];
}

function drawRoundRect(ctx, x, y, w, h, r) {
    const radius = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + w - radius, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
    ctx.lineTo(x + w, y + h - radius);
    ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
    ctx.lineTo(x + radius, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
}

function renderHeatmap(ctx, width, height, rows, cols, data) {
    ctx.clearRect(0, 0, width, height);
    if (rows.length === 0 || cols.length === 0) return;

    const marginLeft = 150;
    const marginTop = 24;
    const marginRight = 24;
    const marginBottom = 120;
    const plotWidth = width - marginLeft - marginRight;
    const plotHeight = height - marginTop - marginBottom;

    const gap = 4;
    const cellWidth = plotWidth / cols.length;
    const cellHeight = plotHeight / rows.length;
    const maxCount = Math.max.apply(null, data.map(function (d) { return d.count; }));

    rows.forEach(function (topic, i) {
        cols.forEach(function (col, j) {
            const item = data.find(function (d) { return d.topic === topic && d.axis === col; });
            const count = item ? item.count : 0;
            const x = marginLeft + j * cellWidth + gap / 2;
            const y = marginTop + i * cellHeight + gap / 2;
            const w = Math.max(cellWidth - gap, 1);
            const h = Math.max(cellHeight - gap, 1);
            const style = getHeatmapColor(maxCount > 0 ? count / maxCount : 0);

            drawRoundRect(ctx, x, y, w, h, 8);
            ctx.fillStyle = style.bg;
            ctx.fill();

            if (cellWidth > 28 && cellHeight > 22) {
                ctx.fillStyle = style.text;
                ctx.font = 'bold 13px "Inter","Noto Sans SC",sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(count > 0 ? count.toString() : '-', x + w / 2, y + h / 2);
            }
        });
    });

    // Y 轴：主题
    ctx.fillStyle = '#475569';
    ctx.font = '13px "Inter","Noto Sans SC",sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    rows.forEach(function (topic, i) {
        const y = marginTop + i * cellHeight + cellHeight / 2;
        const maxChars = Math.max(8, Math.floor(marginLeft / 13));
        ctx.fillText(topic.length > maxChars ? topic.substring(0, maxChars) + '...' : topic, marginLeft - 12, y);
    });

    // X 轴：数据类型
    ctx.fillStyle = '#475569';
    ctx.textBaseline = 'top';
    cols.forEach(function (col, j) {
        const x = marginLeft + j * cellWidth + cellWidth / 2;
        const y = marginTop + rows.length * cellHeight + 16;
        ctx.save();
        ctx.translate(x, y);
        ctx.textAlign = 'center';
        ctx.fillText(col, 0, 0);
        ctx.restore();
    });

    // 图例
    const legendX = marginLeft;
    const legendY = height - 34;
    const legendW = 160;
    const legendH = 10;
    const segmentW = legendW / (HEATMAP_COLOR_STOPS.length - 1);
    HEATMAP_COLOR_STOPS.slice(1).forEach(function (stop, idx) {
        drawRoundRect(ctx, legendX + idx * segmentW, legendY, segmentW - 1, legendH, 2);
        ctx.fillStyle = stop.bg;
        ctx.fill();
    });
    ctx.fillStyle = '#64748b';
    ctx.font = '11px "Inter","Noto Sans SC",sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('低', legendX - 2, legendY + 14);
    ctx.textAlign = 'right';
    ctx.fillText('高', legendX + legendW + 2, legendY + 14);
}

// ===== 时间趋势 =====
function renderTimeCharts(timeTrend) {
    const series = timeTrend.data || [];
    if (series.length === 0) return;

    const periods = series.map(function (item) { return item.period; });

    // 折线：发布数量趋势
    const lineEl = document.getElementById('time-line-chart');
    if (lineEl) {
        new Chart(lineEl.getContext('2d'), {
            type: 'line',
            data: {
                labels: periods,
                datasets: [{
                    label: '发布指南数',
                    data: series.map(function (item) { return item.total || 0; }),
                    borderColor: '#0E7490',
                    backgroundColor: 'rgba(14,116,144,0.12)',
                    tension: 0.3,
                    fill: true,
                }]
            },
            options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } }
        });
    }

    // 堆叠柱：各时段癌种分布
    const barEl = document.getElementById('time-bar-chart');
    if (barEl) {
        const cancerSet = new Set();
        series.forEach(function (item) {
            Object.keys(item.by_cancer_type || {}).forEach(function (c) { cancerSet.add(c); });
        });
        const cancers = Array.from(cancerSet);
        const datasets = cancers.map(function (c, idx) {
            return {
                label: c,
                data: series.map(function (item) { return (item.by_cancer_type || {})[c] || 0; }),
                backgroundColor: CHART_COLORS[idx % CHART_COLORS.length],
            };
        });
        new Chart(barEl.getContext('2d'), {
            type: 'bar',
            data: { labels: periods, datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } },
                plugins: { legend: { position: 'bottom' } }
            }
        });
    }
}
