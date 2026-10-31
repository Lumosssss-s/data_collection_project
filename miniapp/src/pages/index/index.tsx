import React from 'react';
import { View, Text } from '@tarojs/components';
import Taro from '@tarojs/taro';
import DisclaimerBar from '@/components/DisclaimerBar';
import styles from './index.module.scss';

/** 服务入口配置（tone 对应入口图标配色，取自既有语义色板） */
const SERVICES = [
  {
    key: 'preconsult',
    title: '先说症状',
    desc: '描述不适，提示是否需要尽快就医',
    tone: 'primary',
    // 已从 tabBar 移除，改为普通页面用 navigateTo 打开
    tab: false,
    url: '/pages/preconsult/index'
  },
  {
    key: 'knowledge',
    title: '了解疾病',
    desc: '疾病科普与用药的通俗介绍',
    tone: 'info',
    tab: true,
    url: '/pages/knowledge/index'
  },
  {
    key: 'followup',
    title: '我的随访',
    desc: '查看随访安排并填写近况反馈',
    tone: 'success',
    tab: false,
    url: '/pages/followup/index'
  },
  {
    key: 'report',
    title: '报告解读',
    desc: '把报告文字整理成清晰要点',
    tone: 'warning',
    tab: false,
    url: '/pages/report/index'
  }
];

const IndexPage: React.FC = () => {
  const goService = (item: (typeof SERVICES)[number]) => {
    console.info('[Home] 进入服务:', item.key);
    if (item.tab) {
      Taro.switchTab({ url: item.url });
      return;
    }
    Taro.navigateTo({ url: item.url });
  };

  return (
    <View className={styles.page}>
      <View className={styles.header}>
        <Text className={styles.headerEyebrow}>患者健康服务</Text>
        <Text className={styles.headerTitle}>肿瘤健康助手</Text>
        <Text className={styles.headerSub}>为患者与家属提供易懂的健康参考服务</Text>
      </View>

      <View className={styles.content}>
        <View className={styles.grid}>
          {SERVICES.map((item, i) => (
            <View
              key={item.key}
              className={`${styles.card} ${styles[`tone-${item.tone}`]}`}
              onClick={() => goService(item)}
            >
              <View className={styles.cardHead}>
                <Text className={styles.cardIndex}>{`0${i + 1}`}</Text>
                <Text className={styles.cardArrow}>›</Text>
              </View>
              <Text className={styles.cardTitle}>{item.title}</Text>
              <Text className={styles.cardDesc}>{item.desc}</Text>
            </View>
          ))}
        </View>

        <View className={styles.tipCard}>
          <Text className={styles.tipTitle}>温馨提示</Text>
          <Text className={styles.tipText}>
            本应用提供的是健康参考信息，不能替代医生面诊。若症状明显或持续加重，请尽快就医。
          </Text>
        </View>

        <DisclaimerBar />
      </View>
    </View>
  );
};

export default IndexPage;
