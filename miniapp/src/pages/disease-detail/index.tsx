import React, { useEffect, useState } from 'react';
import { View, Text } from '@tarojs/components';
import { useRouter } from '@tarojs/taro';
import StateView from '@/components/StateView';
import DisclaimerBar from '@/components/DisclaimerBar';
import { fetchDiseaseDetail } from '@/services/patientService';
import { MOCK_NOTICE } from '@/utils/constants';
import type { DiseaseDetail } from '@/types/api';
import styles from './index.module.scss';

const DiseaseDetailPage: React.FC = () => {
  const router = useRouter();
  const diseaseId = router.params.id ? decodeURIComponent(router.params.id) : '';
  const [detail, setDetail] = useState<DiseaseDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [fromMock, setFromMock] = useState(false);

  useEffect(() => {
    if (!diseaseId) {
      setLoading(false);
      return;
    }
    fetchDiseaseDetail(diseaseId)
      .then((res) => {
        setDetail(res.data);
        setFromMock(res.fromMock);
      })
      .catch((e) => {
        console.error('[DiseaseDetail] 加载失败:', e);
      })
      .finally(() => setLoading(false));
  }, [diseaseId]);

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
        <StateView type="empty" text="未找到该疾病的科普内容" />
        <DisclaimerBar />
      </View>
    );
  }

  let lastGroup = '';

  return (
    <View className={styles.page}>
      <View className={styles.header}>
        <Text className={styles.name}>{detail.name_canonical}</Text>
        {detail.name_en ? <Text className={styles.nameEn}>{detail.name_en}</Text> : null}
        <View className={styles.tags}>
          {detail.category_label ? <Text className={styles.tag}>{detail.category_label}</Text> : null}
          {detail.cancer_type ? <Text className={styles.tag}>{detail.cancer_type}</Text> : null}
        </View>
        {detail.departments && detail.departments.length > 0 ? (
          <Text className={styles.dept}>就诊科室：{detail.departments.join('、')}</Text>
        ) : null}
      </View>

      {fromMock ? <Text className={styles.mockNotice}>{MOCK_NOTICE}</Text> : null}

      <View className={styles.sections}>
        {detail.sections.map((s) => {
          const showGroup = s.group && s.group !== lastGroup;
          lastGroup = s.group;
          return (
            <View key={s.key}>
              {showGroup ? <Text className={styles.groupTitle}>{s.group}</Text> : null}
              <View className={styles.sectionCard}>
                <Text className={styles.sectionLabel}>{s.label}</Text>
                <Text className={styles.sectionText}>{s.text}</Text>
              </View>
            </View>
          );
        })}
      </View>

      <DisclaimerBar text={detail.disclaimer} />
    </View>
  );
};

export default DiseaseDetailPage;
