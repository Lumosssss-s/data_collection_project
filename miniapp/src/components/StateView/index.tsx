import React from 'react';
import { View, Text } from '@tarojs/components';
import classnames from 'classnames';
import styles from './index.module.scss';

interface StateViewProps {
  /** 状态类型：加载中 / 空态 / 错误 */
  type: 'loading' | 'empty' | 'error';
  /** 提示文案 */
  text?: string;
}

const DEFAULT_TEXT: Record<StateViewProps['type'], string> = {
  loading: '加载中…',
  empty: '暂无内容',
  error: '加载失败，请稍后重试'
};

/** 统一的加载 / 空态 / 错误视图（含降级提示场景复用） */
const StateView: React.FC<StateViewProps> = ({ type, text }) => {
  return (
    <View className={classnames(styles.box, type === 'error' && styles.errorBox)}>
      {type === 'loading' && <View className={styles.spinner} />}
      <Text className={styles.text}>{text || DEFAULT_TEXT[type]}</Text>
    </View>
  );
};

export default StateView;
