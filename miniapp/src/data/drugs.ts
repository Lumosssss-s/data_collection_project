import type { DrugItem, DrugListData, DrugPatientData } from '@/types/api';

/**
 * 用药了解 mock 数据（后端 A4 药品说明书未就绪时的兜底展示）。
 * 字段结构与 `GET /patient/drugs`、`GET /patient/drug/{id}` 一致。
 * 内容为通俗改写示例，仅用于界面预览。
 */

export const mockDrugItems: DrugItem[] = [
  { drug_id: 'DRUG-DEMO-0001', generic_name: '奥希替尼', brand_names: ['泰瑞沙'], cancer_type: '肺癌' },
  { drug_id: 'DRUG-DEMO-0002', generic_name: '吉非替尼', brand_names: ['易瑞沙'], cancer_type: '肺癌' },
  { drug_id: 'DRUG-DEMO-0003', generic_name: '培美曲塞', brand_names: ['力比泰'], cancer_type: '肺癌' },
  { drug_id: 'DRUG-DEMO-0004', generic_name: '曲妥珠单抗', brand_names: ['赫赛汀'], cancer_type: '乳腺癌' },
  { drug_id: 'DRUG-DEMO-0005', generic_name: '他莫昔芬', brand_names: ['诺瓦得士'], cancer_type: '乳腺癌' },
  { drug_id: 'DRUG-DEMO-0006', generic_name: '卡培他滨', brand_names: ['希罗达'], cancer_type: '结直肠癌' },
  { drug_id: 'DRUG-DEMO-0007', generic_name: '奥沙利铂', brand_names: ['乐沙定'], cancer_type: '结直肠癌' },
  { drug_id: 'DRUG-DEMO-0008', generic_name: '仑伐替尼', brand_names: ['乐卫玛'], cancer_type: '甲状腺癌' }
];

export const mockDrugList: DrugListData = {
  total: mockDrugItems.length,
  items: mockDrugItems
};

/** 药品列表（按药名 / 商品名过滤） */
export function mockDrugSearch(q: string): DrugListData {
  const key = (q || '').trim().toLowerCase();
  const items = key
    ? mockDrugItems.filter(
        (d) =>
          d.generic_name.toLowerCase().indexOf(key) >= 0 ||
          (d.brand_names || []).some((b) => b.toLowerCase().indexOf(key) >= 0)
      )
    : mockDrugItems;
  return { total: items.length, items };
}

const PLAIN_MAP: Record<string, DrugPatientData['plain']> = {
  'DRUG-DEMO-0001': {
    what_is_it: '这个药用于治疗有特定基因改变的肺癌。用药前医生会先做基因检测确认是否适合。',
    how_to_use: '一般为口服，每天一次，具体剂量以医生处方和说明书为准。',
    cautions: ['按医生要求的剂量和时间服用，不要自行加量或停药。', '服药期间按医嘱定期复查。'],
    side_effects: [
      { term: '腹泻', plain: '比较常见，多为轻度', when_to_seek_help: '腹泻明显或伴脱水时应及时联系医生' },
      { term: '皮疹', plain: '比较常见，多为轻度', when_to_seek_help: '皮疹范围扩大或伴发热时应就诊' },
      { term: '间质性肺病', plain: '较少见但需重视', when_to_seek_help: '出现气促、干咳加重请立即就医' }
    ],
    seek_help: '如出现明显气促、持续发热或严重腹泻，请立即就医。'
  }
};

const DEFAULT_PLAIN: DrugPatientData['plain'] = {
  what_is_it: '该药品的通俗说明正在整理中。',
  how_to_use: '请严格按照医生处方和药品说明书使用。',
  cautions: ['不要自行调整剂量或停药。', '用药期间按医嘱复查。'],
  side_effects: [
    { term: '常见不良反应', plain: '具体见药品说明书', when_to_seek_help: '如出现明显不适，请及时联系医生' }
  ],
  seek_help: '如出现严重不适，请立即就医。'
};

/** 药品说明书患者版 */
export function mockDrugDetail(drugId: string): DrugPatientData {
  const item = mockDrugItems.find((d) => d.drug_id === drugId);
  return {
    drug_id: drugId,
    generic_name: item ? item.generic_name : '药品详情',
    brand_names: item ? item.brand_names : [],
    plain: PLAIN_MAP[drugId] || DEFAULT_PLAIN,
    disclaimer: '本条信息仅供参考，不构成诊断，也不构成用药建议，具体请遵医嘱。',
    seek_help: '如出现严重不适，请及时联系医生或前往医院就诊。'
  };
}
