import React, { useEffect, useState } from 'react';
import { View, Text } from '@tarojs/components';
import { useRouter } from '@tarojs/taro';
import StateView from '@/components/StateView';
import DisclaimerBar from '@/components/DisclaimerBar';
import { fetchDrugDetail } from '@/services/patientService';
import { MOCK_NOTICE } from '@/utils/constants';
import type { DrugPatientData, DrugPlain } from '@/types/api';
import styles from './index.module.scss';

const DrugDetailPage: React.FC = () => {
  const router = useRouter();
  const drugId = router.params.id ? decodeURIComponent(router.params.id) : '';
  const [detail, setDetail] = useState<DrugPatientData | null>(null);
  const [loading, setLoading] = useState(true);
  const [fromMock, setFromMock] = useState(false);

  useEffect(() => {
    if (!drugId) {
      setLoading(false);
      return;
    }
    fetchDrugDetail(drugId)
      .then((res) => {
        setDetail(res.data);
        setFromMock(res.fromMock);
      })
      .catch((e) => {
        console.error('[DrugDetail] 加载失败:', e);
      })
      .finally(() => setLoading(false));
  }, [drugId]);

  if (loading) {
    return (
      <View className={styles.page}>
        <StateView type="loading" />
      </View>
    );
  }

  if (!detail) {
    return (
      <View className={styles.page}>
        <StateView type="empty" text="未找到该药品的用药说明" />
        <DisclaimerBar />
      </View>
    );
  }

  // plain 可能缺失（后端拆分后 /plain 生成失败返回 null）：兜底空对象，章节按字段条件渲染，不崩页
  const plain: Partial<DrugPlain> = detail.plain || {};

  return (
    <View className={styles.page}>
      <View className={styles.header}>
        <Text className={styles.name}>{detail.generic_name}</Text>
        {detail.brand_names && detail.brand_names.length > 0 ? (
          <Text className={styles.brand}>商品名：{detail.brand_names.join('、')}</Text>
        ) : null}
        {detail.aliases_zh && detail.aliases_zh.length > 0 ? (
          <Text className={styles.alias}>{detail.aliases_zh.join('、')}</Text>
        ) : null}
      </View>

      {/* 黑框警示：置顶安全提示（药名之后、白话之前，先于任何其他信息）。字段与措辞沿用
          PC 端 patient.js：title + text 逐字呈现，超 600 字截断加省略号；正文缺失时整块不渲染 */}
      {detail.has_boxed_warning && detail.boxed_warning && detail.boxed_warning.length > 0 ? (
        <View className={styles.boxed}>
          <Text className={styles.boxedLabel}>FDA 黑框警示</Text>
          {detail.boxed_warning.map((w, i) => {
            const text = String((w && w.text) || '');
            return (
              <Text key={`bw-${i}`} className={styles.boxedText}>
                {(w && w.title ? `${w.title}：` : '') + text.slice(0, 600) + (text.length > 600 ? '…' : '')}
              </Text>
            );
          })}
        </View>
      ) : null}

      {fromMock ? <Text className={styles.mockNotice}>{MOCK_NOTICE}</Text> : null}

      {plain.what_is_it ? (
        <View className={styles.card}>
          <Text className={styles.cardTitle}>这个药是做什么的</Text>
          <Text className={styles.cardText}>{plain.what_is_it}</Text>
        </View>
      ) : null}

      {plain.how_to_use ? (
        <View className={styles.card}>
          <Text className={styles.cardTitle}>说明书中的用法</Text>
          <Text className={styles.cardText}>{plain.how_to_use}</Text>
        </View>
      ) : null}

      {plain.cautions && plain.cautions.length > 0 ? (
        <View className={styles.card}>
          <Text className={styles.cardTitle}>注意事项</Text>
          {plain.cautions.map((c, i) => (
            <Text key={`c-${i}`} className={styles.cardItem}>
              · {c}
            </Text>
          ))}
        </View>
      ) : null}

      {plain.side_effects && plain.side_effects.length > 0 ? (
        <View className={styles.card}>
          <Text className={styles.cardTitle}>可能出现的不良反应</Text>
          {plain.side_effects.map((s, i) => (
            <View key={`s-${i}`} className={styles.sideItem}>
              <Text className={styles.sideTerm}>{s.term}</Text>
              {s.plain ? <Text className={styles.sidePlain}>{s.plain}</Text> : null}
              {s.when_to_seek_help ? <Text className={styles.sideHelp}>{s.when_to_seek_help}</Text> : null}
            </View>
          ))}
        </View>
      ) : null}

      {plain.seek_help ? (
        <View className={styles.card}>
          <Text className={styles.cardTitle}>出现这些情况请及时就医</Text>
          <Text className={styles.cardText}>{plain.seek_help}</Text>
        </View>
      ) : null}

      <DisclaimerBar text={detail.disclaimer} seekHelp={detail.seek_help} />
    </View>
  );
};

export default DrugDetailPage;
