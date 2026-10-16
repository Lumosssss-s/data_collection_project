import type { FollowupAlert, FollowupRecordData, FollowupTasksData } from '@/types/api';

/**
 * 随访 mock 数据（后端 B4 随访模板 / B5 消息未就绪时的兜底演示）。
 * 结构对齐 `GET /followup/tasks`、`POST /followup/record`，仅用于界面预览。
 */

export const mockFollowupTasks: FollowupTasksData = {
  total: 4,
  due_count: 1,
  tasks: [
    {
      task_id: 'TASK-DEMO-001',
      plan_id: 'PLAN-DEMO-001',
      case_id: 'CASE-DEMO-001',
      patient_id: 'PT-DEMO-001',
      tpl_id: 'TPL-LUNG-001',
      timepoint: '术后 3 个月',
      interval_days: 90,
      items: ['胸部 CT', '肿瘤标志物', '症状评估'],
      due_date: '2026-10-20',
      status: 'pending',
      due: true,
      phase_label: '术后'
    },
    {
      task_id: 'TASK-DEMO-002',
      plan_id: 'PLAN-DEMO-001',
      case_id: 'CASE-DEMO-001',
      patient_id: 'PT-DEMO-001',
      tpl_id: 'TPL-LUNG-001',
      timepoint: '术后 6 个月',
      interval_days: 180,
      items: ['胸部 CT', '肿瘤标志物'],
      due_date: '2026-12-20',
      status: 'pending',
      due: false,
      phase_label: '术后'
    },
    {
      task_id: 'TASK-DEMO-003',
      plan_id: 'PLAN-DEMO-001',
      case_id: 'CASE-DEMO-001',
      patient_id: 'PT-DEMO-001',
      tpl_id: 'TPL-LUNG-001',
      timepoint: '术后 12 个月',
      interval_days: 365,
      items: ['胸部 CT', '腹部超声', '肿瘤标志物'],
      due_date: '2027-06-20',
      status: 'pending',
      due: false,
      phase_label: '术后'
    },
    {
      task_id: 'TASK-DEMO-004',
      plan_id: 'PLAN-DEMO-001',
      case_id: 'CASE-DEMO-001',
      patient_id: 'PT-DEMO-001',
      tpl_id: 'TPL-LUNG-001',
      timepoint: '术后 2~3 年（每 6 个月）',
      interval_days: 180,
      items: ['胸部 CT', '肿瘤标志物'],
      due_date: '2026-09-01',
      status: 'done',
      due: false,
      phase_label: '术后'
    }
  ]
};

/** 反馈提交结果：按严重度判定 CTCAE 等级（演示口径，≥3 级触发提醒） */
export function mockFollowupRecord(severity: string, hasText: boolean): FollowupRecordData {
  let grade = 1;
  if (severity === '危及生命') {
    grade = 4;
  } else if (severity === '重度') {
    grade = 3;
  } else if (severity === '中度') {
    grade = 2;
  } else if (!severity && hasText) {
    grade = 2;
  }

  const alerts: FollowupAlert[] =
    grade >= 3
      ? [
          {
            alert_id: `ALERT-DEMO-${Date.now()}`,
            term: '不良反应',
            grade,
            grade_label: grade >= 4 ? '4 级（危及生命）' : '3 级（重度）',
            level: grade >= 4 ? 'emergency' : 'urgent',
            level_label: grade >= 4 ? '立即就医' : '尽快就诊',
            timepoint: '本次反馈',
            created_at: '2026-10-15 10:00:00'
          }
        ]
      : [];

  return {
    task_id: 'TASK-DEMO-001',
    max_grade: grade,
    grade_label:
      { 1: '1 级（轻度）', 2: '2 级（中度）', 3: '3 级（重度）', 4: '4 级（危及生命）' }[grade] || '未分级',
    alerts,
    alert_level: alerts.length ? alerts[0].level : '',
    disclaimer: '本条信息仅供参考，不构成诊断，具体请遵医嘱。'
  };
}
