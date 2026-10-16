import React from 'react';
import { View, Text } from '@tarojs/components';
import { DISCLAIMER, SEEK_HELP } from '@/utils/constants';
import styles from './index.module.scss';

interface DisclaimerBarProps {
  /** 免责声明文案（缺省用全局通用文案） */
  text?: string;
  /** 就医指引文案（缺省用全局通用文案） */
  seekHelp?: string;
}

/** 免责声明 + 就医指引条（患者端每页必备） */
const DisclaimerBar: React.FC<DisclaimerBarProps> = ({ text, seekHelp }) => {
  return (
    <View className={styles.bar}>
      <Text className={styles.text}>{text || DISCLAIMER}</Text>
      <Text className={styles.help}>{seekHelp || SEEK_HELP}</Text>
    </View>
  );
};

export default DisclaimerBar;
