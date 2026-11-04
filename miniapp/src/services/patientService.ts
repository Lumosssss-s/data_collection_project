import { api, LONG_TIMEOUT } from '@/services/api';
import { mockDiseaseDetail, mockDiseaseList, mockDiseaseSearch } from '@/data/diseases';
import { mockDrugDetail, mockDrugList, mockDrugSearch } from '@/data/drugs';
import { mockPreconsultMessage, mockPreconsultSession } from '@/data/preconsult';
import { mockFollowupRecord, mockFollowupTasks } from '@/data/followup';
import { mockReportParse } from '@/data/report';
import type {
  DiseaseDetail,
  DiseaseListData,
  DiseaseSearchData,
  DrugListData,
  DrugPatientData,
  DrugPlain,
  FollowupRecordData,
  FollowupTasksData,
  PreconsultMessageData,
  PreconsultSessionData,
  ReportParseData,
  ServiceResult
} from '@/types/api';

/**
 * 患者端业务数据层。
 *
 * 数据源策略（已确认）：**真实后端优先 + mock 兜底**——
 * 请求成功且后端数据就绪（未降级 / 非空）时用真实数据；
 * 请求失败或后端返回 degraded（A/B 组数据未入库）时，回落本地示例数据并置 fromMock=true，
 * 由页面据此展示「示例数据」提示。数据入库后自动切回真实链路，无需改动页面代码。
 */

/** 真实数据是否可用：未标记 degraded */
function notDegraded<T extends { degraded?: boolean }>(d: T): boolean {
  return !d.degraded;
}

/** 真实数据是否可用：非空列表 */
function nonEmpty<T extends { total: number }>(d: T): boolean {
  return d.total > 0;
}

async function withFallback<T>(
  real: () => Promise<T>,
  mock: () => T,
  usable: (d: T) => boolean
): Promise<ServiceResult<T>> {
  try {
    const data = await real();
    if (usable(data)) {
      return { data, fromMock: false };
    }
    console.info('[Service] 后端数据未就绪，使用示例数据');
    return { data: mock(), fromMock: true };
  } catch (e) {
    console.error('[Service] 请求失败，使用示例数据:', e);
    return { data: mock(), fromMock: true };
  }
}

// ---------- 疾病科普 ----------

export function fetchDiseases(params: {
  category?: string;
  cancer_type?: string;
}): Promise<ServiceResult<DiseaseListData>> {
  return withFallback(
    () => api.get<DiseaseListData>('/diseases', { ...params, size: 200 }),
    () => mockDiseaseList,
    notDegraded
  );
}

export function searchDiseases(q: string, mode: 'name' | 'symptom'): Promise<ServiceResult<DiseaseSearchData>> {
  return withFallback(
    () => api.get<DiseaseSearchData>('/diseases/search', { q, mode, size: 20 }),
    () => mockDiseaseSearch(q),
    nonEmpty
  );
}

export function fetchDiseaseDetail(diseaseId: string): Promise<ServiceResult<DiseaseDetail>> {
  return withFallback(
    () => api.get<DiseaseDetail>(`/diseases/${encodeURIComponent(diseaseId)}`, { version: 'patient' }),
    () => mockDiseaseDetail(diseaseId),
    () => true
  );
}

// ---------- 用药了解 ----------

export function fetchDrugs(q: string): Promise<ServiceResult<DrugListData>> {
  return withFallback(
    () => api.get<DrugListData>('/patient/drugs', { q }),
    () => mockDrugSearch(q),
    nonEmpty
  );
}

export function fetchDrugDetail(drugId: string): Promise<ServiceResult<DrugPatientData>> {
  return withFallback(
    async () => {
      // 2026-11-03 后端拆分：结构化字段（零 LLM）与白话解读（/plain，LLM 缓存）两个接口，
      // 此处合并回旧契约；plain 缺失时降级为仅结构化展示，不让页面崩溃
      const id = encodeURIComponent(drugId);
      const base = await api.get<DrugPatientData>(`/patient/drug/${id}`);
      try {
        const p = await api.get<{ plain?: DrugPlain | null }>(`/patient/drug/${id}/plain`, undefined, {
          timeout: LONG_TIMEOUT
        });
        if (p && p.plain) {
          return { ...base, plain: p.plain };
        }
      } catch {
        // plain 生成失败/超时：忽略，仅返回结构化字段
      }
      return base;
    },
    () => mockDrugDetail(drugId),
    () => true
  );
}

// ---------- 预问诊 ----------

/** mock 会话 ID 前缀：据此判断后续轮次是否继续走本地脚本 */
const MOCK_SESSION_PREFIX = 'mock-';

export function isMockSession(sessionId: string): boolean {
  return sessionId.indexOf(MOCK_SESSION_PREFIX) === 0;
}

export function createPreconsultSession(): Promise<ServiceResult<PreconsultSessionData>> {
  return withFallback(
    () => api.post<PreconsultSessionData>('/preconsult/session', {}),
    () => mockPreconsultSession(),
    notDegraded
  );
}

export function sendPreconsultMessage(
  sessionId: string,
  text: string
): Promise<ServiceResult<PreconsultMessageData>> {
  if (isMockSession(sessionId)) {
    return Promise.resolve({ data: mockPreconsultMessage(text), fromMock: true });
  }
  return withFallback(
    () => api.post<PreconsultMessageData>('/preconsult/message', { session_id: sessionId, text }),
    () => mockPreconsultMessage(text),
    () => true
  );
}

// ---------- 随访 ----------

export function fetchFollowupTasks(patientId: string): Promise<ServiceResult<FollowupTasksData>> {
  return withFallback(
    () => api.get<FollowupTasksData>('/followup/tasks', { patient_id: patientId }),
    () => mockFollowupTasks,
    nonEmpty
  );
}

export function submitFollowupRecord(
  taskId: string,
  severity: string,
  text: string
): Promise<ServiceResult<FollowupRecordData>> {
  const responses: Record<string, unknown>[] = [];
  const item: Record<string, unknown> = {};
  if (severity) {
    item.severity = severity;
  }
  if (text) {
    item.text = text;
  }
  responses.push(item);

  return withFallback(
    () => api.post<FollowupRecordData>('/followup/record', { task_id: taskId, responses }),
    () => mockFollowupRecord(severity, !!text),
    () => true
  );
}

// ---------- 报告解读 ----------

/**
 * 报告解析：保留后端 LLM 的真实抽取结果，仅在「循证条目未就绪」（degraded）时
 * 用示例随访建议补齐展示；整条请求失败时才整体回落示例数据。
 * 这样既不丢弃真实抽取，又能保证演示时「随访建议」区块有内容。
 */
export async function parseReport(
  text: string,
  patientId: string
): Promise<ServiceResult<ReportParseData>> {
  try {
    const data = await api.post<ReportParseData>(
      '/report/parse',
      { text, patient_id: patientId },
      { timeout: LONG_TIMEOUT }
    );
    if (!data.degraded) {
      return { data, fromMock: false };
    }
    if (data.findings.length === 0) {
      console.info('[Service] 报告解析无结果且后端已降级，使用示例数据');
      return { data: mockReportParse(text), fromMock: true };
    }
    const mock = mockReportParse(text);
    console.info('[Service] 循证条目未就绪，随访建议使用示例数据');
    return {
      data: { ...data, followup_suggestions: mock.followup_suggestions },
      fromMock: true
    };
  } catch (e) {
    console.error('[Service] 报告解析请求失败，使用示例数据:', e);
    return { data: mockReportParse(text), fromMock: true };
  }
}
