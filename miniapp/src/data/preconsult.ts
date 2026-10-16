import type {
  PreconsultMessageData,
  PreconsultQuestion,
  PreconsultSessionData
} from '@/types/api';

/**
 * 预问诊 mock 数据（后端 B1/B2/B3 未就绪时的兜底演示）。
 *
 * 说明：真实链路为「LLM 抽取槽位 + B1 红旗征规则 + B3 分诊映射」；
 * 此处用脚本化的问答流程模拟多轮对话，仅用于界面预览，
 * 返回结构严格对齐 `POST /preconsult/session`、`POST /preconsult/message`。
 */

/** 脚本化提问序列 */
const SCRIPT: { slot: string; prompt: string; type: string; key: string }[] = [
  { slot: 'duration', prompt: '这个问题大概持续多久了？', type: 'string', key: 'duration' },
  {
    slot: 'associated_symptoms',
    prompt: '除了刚才说的，还有别的不舒服吗？比如咯血、明显消瘦、发热。',
    type: 'string',
    key: 'associated_symptoms'
  },
  { slot: 'weight_change', prompt: '近半年体重有没有明显变化？', type: 'string', key: 'weight_change' },
  { slot: 'past_history', prompt: '以前得过什么病吗？比如高血压、糖尿病，或者以前有过肿瘤。', type: 'string', key: 'past_history' }
];

/** 红旗征关键词 → 风险等级与处置方向（示例口径） */
const RED_FLAGS: { keywords: string[]; level: 'emergency' | 'urgent'; action: string; department: string }[] = [
  {
    keywords: ['咯血', '痰中带血', '痰里带血', '咳血'],
    level: 'urgent',
    action: '您提到痰中带血或咯血，建议尽快到呼吸内科或胸外科就诊，完善影像检查。',
    department: '呼吸内科'
  },
  {
    keywords: ['气促', '呼吸困难', '喘不上气'],
    level: 'emergency',
    action: '您提到明显气促或呼吸困难，属于需要尽快处理的情况，请立即前往急诊。',
    department: '急诊科'
  },
  {
    keywords: ['意识', '抽搐', '剧烈头痛', '呕吐'],
    level: 'emergency',
    action: '出现抽搐、意识改变或剧烈头痛伴呕吐，请立即急诊，注意防跌倒误吸。',
    department: '急诊科'
  },
  {
    keywords: ['发热', '发烧', '38'],
    level: 'urgent',
    action: '化疗后出现发热需要重视，建议尽快查血常规并就诊，勿自行服用退热药掩盖。',
    department: '急诊科'
  },
  {
    keywords: ['消瘦', '体重下降', '瘦了很多'],
    level: 'urgent',
    action: '不明原因的进行性消瘦建议尽快到肿瘤内科或全科门诊就诊。',
    department: '肿瘤内科'
  }
];

let turn = 0;
let sessionId = '';
let collected: Record<string, string> = {};
let detectedSymptoms: string[] = [];
let sessionText = '';

function detectSymptoms(text: string): string[] {
  const found: string[] = [];
  RED_FLAGS.forEach((rf) => {
    rf.keywords.forEach((kw) => {
      if (text.indexOf(kw) >= 0 && found.indexOf(kw) < 0) {
        found.push(kw);
      }
    });
  });
  return found;
}

function buildRedFlags(): PreconsultMessageData['red_flags'] {
  const hits: PreconsultMessageData['red_flags'] = [];
  RED_FLAGS.forEach((rf, idx) => {
    if (rf.keywords.some((kw) => sessionText.indexOf(kw) >= 0)) {
      hits.push({
        rule_id: `RF-DEMO-${idx + 1}`,
        risk_level: rf.level,
        action: rf.action,
        department: rf.department
      });
    }
  });
  return hits;
}

function riskOf(flags: PreconsultMessageData['red_flags']): string {
  if (flags.some((f) => f.risk_level === 'emergency')) {
    return 'emergency';
  }
  if (flags.some((f) => f.risk_level === 'urgent')) {
    return 'urgent';
  }
  return 'routine';
}

const RISK_LABEL: Record<string, string> = {
  emergency: '高风险（立即就医）',
  urgent: '中风险（尽快就诊）',
  routine: '低风险（常规）'
};

const VISIT_PREP: Record<string, string[]> = {
  emergency: [
    '保持镇静，立即前往急诊或拨打 120。',
    '携带既往病历、影像与检验报告。',
    '如咯血或呼吸困难，保持侧卧或半卧位，避免误吸。',
    '勿自行驾车前往。'
  ],
  urgent: ['尽快（数日内）到相应专科门诊就诊。', '携带既往检查报告与用药清单。', '记录症状出现时间与变化。'],
  routine: ['可通过门诊预约就诊。', '整理症状描述与既往病史。', '如有新的不适，及时就医。']
};

/** 创建会话（重置脚本状态） */
export function mockPreconsultSession(): PreconsultSessionData {
  turn = 0;
  sessionId = `mock-${Date.now()}`;
  collected = {};
  detectedSymptoms = [];
  sessionText = '';
  return {
    session_id: sessionId,
    next_question: { slot: 'chief_complaint', prompt: '请描述您主要的不适。', type: 'string', required: true },
    risk_level: 'routine',
    disclaimer: '本预问诊仅作就医方向参考，不构成诊断，具体请遵医嘱。'
  };
}

/** 提交一轮描述 */
export function mockPreconsultMessage(text: string): PreconsultMessageData {
  sessionText += ` ${text}`;
  detectedSymptoms = Array.from(new Set([...detectedSymptoms, ...detectSymptoms(text)]));

  if (turn === 0) {
    collected.chief_complaint = text;
  } else {
    const prev = SCRIPT[turn - 1];
    if (prev) {
      collected[prev.key] = text;
    }
  }

  const flags = buildRedFlags();
  const risk = riskOf(flags);
  const next: PreconsultQuestion | null =
    turn < SCRIPT.length
      ? {
          slot: SCRIPT[turn].slot,
          prompt: SCRIPT[turn].prompt,
          type: SCRIPT[turn].type,
          required: true
        }
      : null;
  turn += 1;

  const departments = flags.map((f) => f.department).filter((d) => !!d);
  const primary = departments[0] || '肿瘤内科';

  return {
    session_id: sessionId,
    slots: { ...collected },
    symptoms: detectedSymptoms,
    next_question: next,
    red_flags: flags,
    risk_level: risk,
    risk_label: RISK_LABEL[risk],
    department: { primary, alt: departments.slice(1), source: 'mock' },
    visit_prep: VISIT_PREP[risk],
    complete: next === null,
    disclaimer: '本预问诊仅作就医方向参考，不构成诊断，具体请遵医嘱。'
  };
}
