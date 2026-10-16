import React, { useEffect, useState } from 'react';
import { View, Text } from '@tarojs/components';
import { useRouter } from '@tarojs/taro';
import StateView from '@/components/StateView';
import DisclaimerBar from '@/components/DisclaimerBar';
import { fetchDrugDetail } from '@/services/patientService';
import { MOCK_NOTICE } from '@/utils/constants';
import type { DrugPatientData } from '@/types/api';
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

  const { plain } = detail;

  return (
    <View className={styles.page}>
      <View className={styles.header}>
        <Text className={styles.name}>{detail.generic_name}</Text>
        {detail.brand_names && detail.brand_names.length > 0 ? (
          <Text className={styles.brand}>商品名：{detail.brand_names.join('、')}</Text>
        ) : null}
      </View>

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
