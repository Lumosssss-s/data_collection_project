import type { DiseaseCard, DiseaseDetail, DiseaseListData, DiseaseSearchData } from '@/types/api';

/**
 * 疾病科普 mock 数据（后端 A3 疾病档案未就绪时的兜底展示）。
 * 字段结构与 `GET /diseases`、`GET /diseases/search`、`GET /diseases/{id}?version=patient` 一致。
 */

export const mockDiseaseCards: DiseaseCard[] = [
  {
    disease_id: 'DIS-DEMO-LUNG',
    name_canonical: '肺癌',
    name_en: 'Lung Cancer',
    category: 'primary_cancer',
    category_label: '原发恶性肿瘤',
    cancer_type: '肺癌',
    departments: ['肿瘤内科', '胸外科', '放疗科'],
    overview: '肺癌是起源于支气管黏膜或腺体的恶性肿瘤，是我国发病与死亡人数最多的恶性肿瘤之一。',
    symptoms: ['咳嗽', '痰中带血', '胸痛', '气促', '消瘦'],
    score: null
  },
  {
    disease_id: 'DIS-DEMO-NSCLC',
    name_canonical: '非小细胞肺癌',
    name_en: 'Non-small Cell Lung Cancer',
    category: 'primary_cancer',
    category_label: '原发恶性肿瘤',
    cancer_type: '肺癌',
    departments: ['肿瘤内科', '胸外科'],
    overview: '非小细胞肺癌约占肺癌的 85%，包括腺癌、鳞癌等类型，常与 EGFR 等驱动基因突变相关。',
    symptoms: ['刺激性干咳', '咯血', '胸痛', '声音嘶哑'],
    score: null
  },
  {
    disease_id: 'DIS-DEMO-BREAST',
    name_canonical: '乳腺癌',
    name_en: 'Breast Cancer',
    category: 'primary_cancer',
    category_label: '原发恶性肿瘤',
    cancer_type: '乳腺癌',
    departments: ['乳腺外科', '肿瘤内科', '放疗科'],
    overview: '乳腺癌是发生在乳腺上皮组织的恶性肿瘤，早期常表现为无痛性肿块，规范筛查有助于早期发现。',
    symptoms: ['无痛性肿块', '乳头溢液', '皮肤凹陷', '腋窝淋巴结肿大'],
    score: null
  },
  {
    disease_id: 'DIS-DEMO-COLORECTAL',
    name_canonical: '结直肠癌',
    name_en: 'Colorectal Cancer',
    category: 'primary_cancer',
    category_label: '原发恶性肿瘤',
    cancer_type: '结直肠癌',
    departments: ['胃肠外科', '肿瘤内科', '消化内科'],
    overview: '结直肠癌是发生在结肠或直肠的恶性肿瘤，多由腺瘤性息肉逐步演变而来，早期筛查可显著降低风险。',
    symptoms: ['便血', '排便习惯改变', '腹痛', '消瘦'],
    score: null
  },
  {
    disease_id: 'DIS-DEMO-GASTRIC',
    name_canonical: '胃癌',
    name_en: 'Gastric Cancer',
    category: 'primary_cancer',
    category_label: '原发恶性肿瘤',
    cancer_type: '胃癌',
    departments: ['胃肠外科', '肿瘤内科'],
    overview: '胃癌是起源于胃黏膜上皮的恶性肿瘤，与幽门螺杆菌感染、饮食习惯等因素相关。',
    symptoms: ['上腹不适', '饱胀感', '进行性消瘦', '黑便'],
    score: null
  },
  {
    disease_id: 'DIS-DEMO-THYROID',
    name_canonical: '甲状腺乳头状癌',
    name_en: 'Papillary Thyroid Carcinoma',
    category: 'primary_cancer',
    category_label: '原发恶性肿瘤',
    cancer_type: '甲状腺癌',
    departments: ['甲状腺外科', '头颈外科'],
    overview: '甲状腺乳头状癌是最常见的甲状腺癌类型，总体预后较好，规范手术与随访可获得良好疗效。',
    symptoms: ['颈部无痛性结节', '声音嘶哑', '吞咽不适'],
    score: null
  },
  {
    disease_id: 'DIS-DEMO-MPE',
    name_canonical: '恶性胸腔积液',
    name_en: 'Malignant Pleural Effusion',
    category: 'tumor_complication',
    category_label: '肿瘤并发症/相关疾病',
    cancer_type: '肺癌',
    departments: ['肿瘤内科', '呼吸内科'],
    overview: '恶性胸腔积液是肿瘤累及胸膜导致的胸腔内液体潴留，常见于肺癌，可表现为进行性气促。',
    symptoms: ['进行性气促', '患侧胸痛', '平卧加重', '干咳'],
    score: null
  },
  {
    disease_id: 'DIS-DEMO-DCIS',
    name_canonical: '乳腺导管原位癌',
    name_en: 'Ductal Carcinoma In Situ',
    category: 'precancerous_lesion',
    category_label: '癌前病变',
    cancer_type: '乳腺癌',
    departments: ['乳腺外科'],
    overview: '乳腺导管原位癌是癌细胞局限于乳腺导管内、尚未突破基底膜的早期病变，及时处理预后良好。',
    symptoms: ['多无明显症状', '影像学钙化', '偶见乳头溢液'],
    score: null
  }
];

export const mockDiseaseList: DiseaseListData = {
  total: mockDiseaseCards.length,
  items: mockDiseaseCards,
  facets: {
    category: [
      { value: 'primary_cancer', label: '原发恶性肿瘤', count: 6 },
      { value: 'tumor_complication', label: '肿瘤并发症/相关疾病', count: 1 },
      { value: 'precancerous_lesion', label: '癌前病变', count: 1 }
    ],
    cancer_type: [
      { value: '肺癌', count: 3 },
      { value: '乳腺癌', count: 2 },
      { value: '结直肠癌', count: 1 },
      { value: '胃癌', count: 1 },
      { value: '甲状腺癌', count: 1 }
    ]
  }
};

/** 疾病列表（按关键词过滤，模拟名称检索） */
export function mockDiseaseSearch(q: string): DiseaseSearchData {
  const key = (q || '').trim();
  const items = key
    ? mockDiseaseCards.filter(
        (d) => d.name_canonical.indexOf(key) >= 0 || (d.name_en || '').toLowerCase().indexOf(key.toLowerCase()) >= 0
      )
    : mockDiseaseCards;
  return {
    mode: 'name',
    query: key,
    normalized: key === '肺CA' ? '肺癌' : key,
    total: items.length,
    items
  };
}

/** 各疾病患者版正文（演示内容，仅用于界面预览；真实内容以 A3 疾病档案为准） */
const SECTIONS: Record<string, DiseaseDetail['sections']> = {
  'DIS-DEMO-LUNG': [
    { key: 'overview', label: '这是什么病', group: '基础认识', text: '肺癌是起源于支气管和肺组织的恶性肿瘤。它并不是一种病，而是一大类疾病的统称，不同类型的治疗方式差别较大。' },
    { key: 'symptoms_early', label: '早期可能的表现', group: '常见表现', text: '早期往往没有明显不适，常在体检做胸部影像时发现。部分人会有持续咳嗽、痰中带血等表现。' },
    { key: 'workup', label: '通常需要做哪些检查', group: '检查与诊断', text: '常见检查包括胸部 CT、支气管镜、病理活检以及基因检测。具体项目由医生根据情况安排。' },
    { key: 'treatment', label: '治疗方式概述', group: '治疗', text: '治疗可能包括手术、放疗、化疗、靶向治疗和免疫治疗等，医生会根据分期与身体情况综合制定方案。' },
    { key: 'patient_education', label: '日常注意', group: '日常生活', text: '戒烟、均衡饮食、适度活动、保证休息。治疗期间按医嘱复查，出现新的不适及时告诉医生。' },
    { key: 'care_seeking', label: '就医指引', group: '就医', text: '如出现大咯血、明显气促、面颈部肿胀、剧烈头痛等情况，请立即就医或拨打 120。' }
  ],
  'DIS-DEMO-NSCLC': [
    { key: 'overview', label: '这是什么病', group: '基础认识', text: '非小细胞肺癌是肺癌中最常见的一类，包括腺癌、鳞癌等。很多患者会发现特定的基因改变。' },
    { key: 'pathology_subtypes', label: '常见分型', group: '基础认识', text: '腺癌和鳞癌最常见。部分患者存在 EGFR、ALK 等基因改变，可能适合靶向治疗。' },
    { key: 'treatment', label: '治疗方式概述', group: '治疗', text: '早期以手术为主；中晚期常联合化疗、靶向或免疫治疗。是否做基因检测对方案选择很重要。' },
    { key: 'care_seeking', label: '就医指引', group: '就医', text: '出现咯血加重、呼吸困难、剧烈骨痛等情况请尽快就医。' }
  ],
  'DIS-DEMO-BREAST': [
    { key: 'overview', label: '这是什么病', group: '基础认识', text: '乳腺癌是发生在乳腺的恶性肿瘤。早期发现并规范治疗，整体预后较好。' },
    { key: 'symptoms_early', label: '早期可能的表现', group: '常见表现', text: '常见为乳房无痛性肿块，也可能有乳头溢液、皮肤凹陷或腋窝淋巴结肿大。' },
    { key: 'workup', label: '通常需要做哪些检查', group: '检查与诊断', text: '常做乳腺超声、钼靶、穿刺活检，并检测激素受体与 HER2 等指标。' },
    { key: 'patient_education', label: '日常注意', group: '日常生活', text: '保持规律作息与适度运动，按医嘱完成治疗与复查，注意患侧上肢保护。' },
    { key: 'care_seeking', label: '就医指引', group: '就医', text: '发现新的乳房肿块、皮肤改变或明显疼痛，请及时到乳腺外科就诊。' }
  ],
  'DIS-DEMO-COLORECTAL': [
    { key: 'overview', label: '这是什么病', group: '基础认识', text: '结直肠癌是发生在大肠的恶性肿瘤，很多由肠息肉逐步演变而来，早期筛查很有价值。' },
    { key: 'symptoms_early', label: '早期可能的表现', group: '常见表现', text: '可能有便血、排便习惯改变、腹部不适等，也可能没有任何症状，靠肠镜发现。' },
    { key: 'prevention', label: '如何预防与筛查', group: '预防', text: '建议按医生建议进行肠镜筛查，注意膳食纤维摄入，减少加工肉类。' },
    { key: 'care_seeking', label: '就医指引', group: '就医', text: '出现持续便血、明显腹胀或停止排气排便，请尽快就诊或急诊。' }
  ],
  'DIS-DEMO-GASTRIC': [
    { key: 'overview', label: '这是什么病', group: '基础认识', text: '胃癌是起源于胃黏膜的恶性肿瘤，与幽门螺杆菌感染和饮食习惯有关。' },
    { key: 'symptoms_early', label: '早期可能的表现', group: '常见表现', text: '早期常无特异表现，可能有上腹不适、饱胀、食欲下降。' },
    { key: 'workup', label: '通常需要做哪些检查', group: '检查与诊断', text: '主要依靠胃镜及活检，必要时做 CT 等影像评估分期。' },
    { key: 'care_seeking', label: '就医指引', group: '就医', text: '出现呕血、黑便、明显消瘦或进食梗阻，请及时就医。' }
  ],
  'DIS-DEMO-THYROID': [
    { key: 'overview', label: '这是什么病', group: '基础认识', text: '甲状腺乳头状癌是最常见的甲状腺癌，生长相对缓慢，总体治疗效果较好。' },
    { key: 'symptoms_early', label: '早期可能的表现', group: '常见表现', text: '多表现为颈部无痛性结节，常在体检超声时发现。' },
    { key: 'treatment', label: '治疗方式概述', group: '治疗', text: '以手术为主，部分患者术后需要甲状腺素抑制治疗或碘治疗。' },
    { key: 'followup', label: '随访', group: '随访', text: '需要定期复查甲状腺功能与颈部超声，按医生安排调整用药。' }
  ],
  'DIS-DEMO-MPE': [
    { key: 'overview', label: '这是什么病', group: '基础认识', text: '恶性胸腔积液是肿瘤累及胸膜后，胸腔内出现较多液体，常常导致气促。' },
    { key: 'symptoms_early', label: '常见表现', group: '常见表现', text: '主要表现为进行性气促、患侧胸痛，平卧时可能加重。' },
    { key: 'care_seeking', label: '就医指引', group: '就医', text: '如气促明显加重，请立即就医；等待期间可采取半卧位并吸氧。' }
  ],
  'DIS-DEMO-DCIS': [
    { key: 'overview', label: '这是什么病', group: '基础认识', text: '乳腺导管原位癌属于早期病变，异常细胞局限在导管内，尚未向外侵犯。' },
    { key: 'treatment', label: '治疗方式概述', group: '治疗', text: '常采用保乳手术或全乳切除，部分患者需配合放疗，具体由医生评估。' },
    { key: 'followup', label: '随访', group: '随访', text: '需按医嘱定期复查乳腺影像，关注对侧乳房情况。' }
  ]
};

const DEFAULT_SECTIONS: DiseaseDetail['sections'] = [
  { key: 'overview', label: '这是什么病', group: '基础认识', text: '该疾病的科普内容正在整理中。' },
  { key: 'care_seeking', label: '就医指引', group: '就医', text: '如有不适，请及时到相应专科就诊。' }
];

/** 疾病详情（患者版） */
export function mockDiseaseDetail(diseaseId: string): DiseaseDetail {
  const card = mockDiseaseCards.find((d) => d.disease_id === diseaseId);
  return {
    disease_id: diseaseId,
    name_canonical: card ? card.name_canonical : '疾病详情',
    name_en: card ? card.name_en : '',
    synonyms: [],
    category: card ? card.category : '',
    category_label: card ? card.category_label : '',
    cancer_type: card ? card.cancer_type : '',
    departments: card ? card.departments : [],
    version: 'patient',
    sections: SECTIONS[diseaseId] || DEFAULT_SECTIONS,
    links: {},
    section_gaps: [],
    sources: ['示例数据（仅用于界面预览）'],
    disclaimer: '本内容仅供参考，不构成诊断，具体请遵医嘱。'
  };
}
