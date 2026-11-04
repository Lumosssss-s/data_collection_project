// ============================================
// 后端接口数据类型（与 FastAPI /api/v1 返回结构对齐）
// 说明：字段名严格对应后端契约，mock 数据亦按此结构编写，
//       保证「真实接口 ↔ mock 兜底」切换时页面代码无需改动。
// ============================================

/** 后端统一响应包装 */
export interface ApiEnvelope<T> {
  success: boolean;
  data: T;
  message: string;
  code: number;
}

/** 数据就绪状态：true 表示后端无数据 / 已降级 */
export interface Degradable {
  degraded?: boolean;
  note?: string;
}

/** 疾病列表卡片（/diseases、/diseases/search） */
export interface DiseaseCard {
  disease_id: string;
  name_canonical: string;
  name_en?: string;
  category?: string;
  category_label?: string;
  cancer_type?: string;
  departments?: string[];
  overview?: string;
  symptoms?: string[];
  score?: number | null;
}

/** 疾病分面项 */
export interface FacetItem {
  value: string;
  label?: string;
  count: number;
}

/** 疾病检索 / 浏览响应 */
export interface DiseaseListData extends Degradable {
  total: number;
  items: DiseaseCard[];
  facets?: {
    category: FacetItem[];
    cancer_type: FacetItem[];
  };
}

/** 疾病检索响应（含归一说明） */
export interface DiseaseSearchData extends Degradable {
  mode: string;
  query: string;
  normalized: string | string[] | null;
  total: number;
  items: DiseaseCard[];
}

/** 疾病详情章节 */
export interface DiseaseSection {
  key: string;
  label: string;
  group: string;
  text: string;
}

/** 疾病详情（患者版 /diseases/{id}?version=patient） */
export interface DiseaseDetail {
  disease_id: string;
  name_canonical: string;
  name_en?: string;
  synonyms?: string[];
  category?: string;
  category_label?: string;
  cancer_type?: string;
  departments?: string[];
  version: string;
  sections: DiseaseSection[];
  links?: Record<string, unknown>;
  section_gaps?: string[];
  sources?: string[];
  disclaimer?: string;
}

/** 药品列表项（/patient/drugs） */
export interface DrugItem {
  drug_id: string;
  generic_name: string;
  brand_names?: string[];
  cancer_type?: string;
  /** 中文别名（零 LLM，逐字来自 A4 说明书；空/缺失时前端整行不渲染） */
  aliases_zh?: string[];
}

export interface DrugListData extends Degradable {
  total: number;
  items: DrugItem[];
}

/** 药品不良反应（患者版） */
export interface DrugSideEffect {
  term: string;
  plain: string;
  when_to_seek_help: string;
}

/** 药品说明书白话解读（/patient/drug/{id}/plain 返回；生成失败时为 null） */
export interface DrugPlain {
  what_is_it: string;
  how_to_use: string;
  cautions: string[];
  side_effects: DrugSideEffect[];
  seek_help: string;
}

/** 黑框警示条目（与 PC 端 frontend/js/pages/patient.js 同一份字段：title + text） */
export interface DrugBoxedWarning {
  title?: string;
  text?: string;
}

/** 药品说明书患者版（/patient/drug/{id} 结构化 + /plain 合并） */
export interface DrugPatientData extends Degradable {
  drug_id: string;
  generic_name: string;
  brand_names?: string[];
  /** 中文别名（/patient/drug/{id} 已透传，与列表同一字段源） */
  aliases_zh?: string[];
  /** 黑框警示正文（零 LLM 结构化字段，逐字来自说明书） */
  boxed_warning?: DrugBoxedWarning[];
  /** 是否有黑框警示：后端由 boxed_warning 非空推导，非存储字段 */
  has_boxed_warning?: boolean;
  /** 白话解读：后端 2026-11-03 起拆分为独立接口，缺失时页面降级为仅结构化展示 */
  plain?: DrugPlain;
  disclaimer?: string;
  seek_help?: string;
}

/** 预问诊下一问 */
export interface PreconsultQuestion {
  slot: string;
  prompt: string;
  type?: string;
  required?: boolean;
}

/** 预问诊科室建议 */
export interface PreconsultDepartment {
  primary: string;
  alt: string[];
  source?: string;
}

/** 红旗征命中项 */
export interface RedFlag {
  rule_id: string;
  risk_level: string;
  action: string;
  department: string;
}

/** 预问诊会话创建响应 */
export interface PreconsultSessionData extends Degradable {
  session_id: string;
  next_question: PreconsultQuestion | null;
  risk_level: string;
  disclaimer?: string;
}

/** 预问诊消息响应 */
export interface PreconsultMessageData extends Degradable {
  session_id: string;
  slots?: Record<string, unknown>;
  symptoms?: string[];
  next_question: PreconsultQuestion | null;
  red_flags: RedFlag[];
  risk_level: string;
  risk_label?: string;
  department?: PreconsultDepartment;
  visit_prep?: string[];
  complete?: boolean;
  disclaimer?: string;
}

/** 随访任务 */
export interface FollowupTask {
  task_id: string;
  plan_id?: string;
  case_id?: string;
  patient_id?: string;
  tpl_id?: string;
  timepoint: string;
  interval_days?: number;
  items: string[];
  due_date: string;
  status: string;
  due?: boolean;
  phase_label?: string;
}

/** 随访任务列表（/followup/tasks） */
export interface FollowupTasksData {
  total: number;
  due_count: number;
  tasks: FollowupTask[];
}

/** 随访预警 */
export interface FollowupAlert {
  alert_id: string;
  term: string;
  grade: number;
  grade_label: string;
  level: string;
  level_label: string;
  timepoint?: string;
  created_at?: string;
}

/** 随访反馈提交响应 */
export interface FollowupRecordData {
  task_id: string;
  max_grade: number;
  grade_label: string;
  alerts: FollowupAlert[];
  alert_level?: string;
  disclaimer?: string;
}

/** 报告结构化病灶 */
export interface ReportFinding {
  site: string;
  size: string;
  density: string;
  margin: string;
  lymph_nodes: string;
  label: string;
}

/** 报告随访建议 */
export interface ReportSuggestion {
  text: string;
  source: string;
  breadcrumb?: string;
  evidence_level?: string;
  rec_strength?: string;
}

/** 报告历次对比 */
export interface ReportDiff {
  previous_count: number;
  current_count: number;
  added: string[];
  removed: string[];
  unchanged: string[];
  size_changes?: { site: string; before: string; after: string }[];
}

/** 报告解析结果（/report/parse） */
export interface ReportParseData extends Degradable {
  findings: ReportFinding[];
  key_signs: string[];
  impression: string;
  followup_suggestions: ReportSuggestion[];
  followup_evidence?: Record<string, unknown>[];
  diff_prev: ReportDiff | null;
  disclaimer?: string;
}

/** 服务调用结果：data 为业务数据，fromMock 标识是否走了 mock 兜底 */
export interface ServiceResult<T> {
  data: T;
  fromMock: boolean;
}
