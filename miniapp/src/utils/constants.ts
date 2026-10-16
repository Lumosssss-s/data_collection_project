// ============================================
// 全局文案常量（患者端统一口径）
// 强制约束：每页免责声明 + 就医指引；不给诊断结论、不给处方。
// ============================================

/** 通用免责声明 */
export const DISCLAIMER = '本页信息仅供参考，不构成诊断，具体请遵医嘱。';

/** 通用就医指引 */
export const SEEK_HELP = '如出现严重不适或症状加重，请及时联系医生或前往医院就诊。';

/** 预问诊免责声明（与后端一致口径） */
export const PRECONSULT_DISCLAIMER = '本预问诊仅作就医方向参考，不构成诊断，具体请遵医嘱。';

/** 报告解析免责声明 */
export const REPORT_DISCLAIMER =
  '本解析仅对报告文本做结构化整理，不构成影像判读与诊断结论，具体请以报告原文与医生判断为准。';

/** mock 兜底提示 */
export const MOCK_NOTICE = '当前展示为示例数据（后端数据尚未就绪），仅供界面预览。';

/** 风险分层展示 */
export const RISK_LABELS: Record<string, string> = {
  emergency: '高风险（立即就医）',
  urgent: '中风险（尽快就诊）',
  routine: '低风险（常规）'
};

/** 知识页 Tab */
export const KNOWLEDGE_TABS = [
  { key: 'disease', label: '疾病科普' },
  { key: 'drug', label: '用药了解' }
] as const;
