import React, { useState } from 'react';
import { View, Text, Input, Button } from '@tarojs/components';
import Taro, { useDidShow } from '@tarojs/taro';
import DisclaimerBar from '@/components/DisclaimerBar';
import styles from './index.module.scss';

const STORAGE_KEY = 'patient_id';

const MinePage: React.FC = () => {
  const [patientId, setPatientId] = useState('');

  useDidShow(() => {
    try {
      const saved = Taro.getStorageSync(STORAGE_KEY);
      if (saved) {
        setPatientId(String(saved));
      }
    } catch (e) {
      console.error('[Mine] 读取随访编号失败:', e);
    }
  });

  const savePatientId = () => {
    const id = patientId.trim();
    try {
      Taro.setStorageSync(STORAGE_KEY, id);
      Taro.showToast({ title: '已保存', icon: 'success' });
    } catch (e) {
      console.error('[Mine] 保存随访编号失败:', e);
      Taro.showToast({ title: '保存失败', icon: 'none' });
    }
  };

  const goFollowup = () => {
    Taro.navigateTo({ url: '/pages/followup/index' });
  };

  const goReport = () => {
    Taro.navigateTo({ url: '/pages/report/index' });
  };

  return (
    <View className={styles.page}>
      <View className={styles.hero}>
        <Text className={styles.heroTitle}>我的健康服务</Text>
        <Text className={styles.heroSub}>填写随访编号后，可查看属于您的随访安排</Text>
      </View>

      <View className={styles.card}>
        <Text className={styles.cardTitle}>随访编号</Text>
        <View className={styles.row}>
          <Input
            className={styles.input}
            value={patientId}
            placeholder="请输入您的随访编号"
            onInput={(e) => setPatientId(e.detail.value)}
          />
          <Button className={styles.saveBtn} onClick={savePatientId}>
            保存
          </Button>
        </View>
        <Text className={styles.cardHint}>随访编号由医生或随访人员提供，保存在本机，不会上传。</Text>
      </View>

      <View className={styles.entry} onClick={goFollowup}>
        <View>
          <Text className={styles.entryTitle}>我的随访</Text>
          <Text className={styles.entryDesc}>查看随访安排、填写近况反馈</Text>
        </View>
        <Text className={styles.entryArrow}>›</Text>
      </View>

      <View className={styles.entry} onClick={goReport}>
        <View>
          <Text className={styles.entryTitle}>报告解读</Text>
          <Text className={styles.entryDesc}>把报告文字整理成清晰要点</Text>
        </View>
        <Text className={styles.entryArrow}>›</Text>
      </View>

      <DisclaimerBar />
    </View>
  );
};

export default MinePage;
