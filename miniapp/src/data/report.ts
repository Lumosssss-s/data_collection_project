import type { ReportParseData } from '@/types/api';

/**
 * 报告解读 mock 数据（后端循证条目未就绪 / 未命中时的兜底演示）。
 * 结构与 `POST /report/parse` 一致；内容为示例，仅用于界面预览。
 */

export function mockReportParse(text: string): ReportParseData {
  const hasPrev = text.indexOf('较前') >= 0 || text.indexOf('增大') >= 0;
  return {
    findings: [
      {
        site: '右肺上叶',
        size: hasPrev ? '15mm×12mm' : '12mm×10mm',
        density: '磨玻璃',
        margin: '边界欠清',
        lymph_nodes: '纵隔未见肿大淋巴结',
        label: '部位：右肺上叶；大小：' + (hasPrev ? '15mm×12mm' : '12mm×10mm') + '；密度：磨玻璃；边界：边界欠清'
      }
    ],
    key_signs: ['磨玻璃结节', '边界欠清', '分叶'],
    impression: '右肺上叶磨玻璃结节，边界欠清，可见分叶；纵隔未见肿大淋巴结。（示例数据）',
    followup_suggestions: [
      {
        text: '对于持续存在的磨玻璃结节，建议按专科医生意见定期复查胸部 CT，观察大小与密度的变化。',
        source: '肺结节诊疗相关共识（示例）',
        breadcrumb: '随访与随访间隔',
        evidence_level: 'moderate',
        rec_strength: 'strong'
      },
      {
        text: '如结节增大或出现实性成分增多，应及时就诊进一步评估。',
        source: '肺结节诊疗相关共识（示例）',
        breadcrumb: '随访与随访间隔',
        evidence_level: 'moderate',
        rec_strength: 'weak'
      }
    ],
    followup_evidence: [],
    diff_prev: hasPrev
      ? {
          previous_count: 1,
          current_count: 1,
          added: [],
          removed: [],
          unchanged: ['右肺上叶'],
          size_changes: [{ site: '右肺上叶', before: '12mm×10mm', after: '15mm×12mm' }]
        }
      : null,
    disclaimer:
      '本解析仅对报告文本做结构化整理，不构成影像判读与诊断结论，具体请以报告原文与医生判断为准。'
  };
}
