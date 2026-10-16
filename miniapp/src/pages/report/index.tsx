import React, { useState } from 'react';
import { View, Text, Textarea, Button } from '@tarojs/components';
import Taro from '@tarojs/taro';
import classnames from 'classnames';
import DisclaimerBar from '@/components/DisclaimerBar';
import StateView from '@/components/StateView';
import { parseReport } from '@/services/patientService';
import { MOCK_NOTICE, REPORT_DISCLAIMER } from '@/utils/constants';
import type { ReportParseData } from '@/types/api';
import styles from './index.module.scss';

const PLACEHOLDER =
  '粘贴报告文字。示例：\n右肺上叶见磨玻璃结节，大小约 12mm×10mm，边界欠清，可见分叶；纵隔未见肿大淋巴结。';

const FINDING_FIELDS: { key: keyof ReportParseData['findings'][number]; label: string }[] = [
  { key: 'site', label: '部位' },
  { key: 'size', label: '大小' },
  { key: 'density', label: '密度' },
  { key: 'margin', label: '边界' },
  { key: 'lymph_nodes', label: '淋巴结' }
];

const ReportPage: React.FC = () => {
  const [text, setText] = useState('');
  const [result, setResult] = useState<ReportParseData | null>(null);
  const [loading, setLoading] = useState(false);
  const [fromMock, setFromMock] = useState(false);

  const handleParse = async () => {
    const content = text.trim();
    if (!content) {
      Taro.showToast({ title: '请输入报告文字', icon: 'none' });
      return;
    }
    let patientId = '';
    try {
      patientId = String(Taro.getStorageSync('patient_id') || '');
    } catch (e) {
      console.error('[Report] 读取随访编号失败:', e);
    }
    setLoading(true);
    try {
      const res = await parseReport(content, patientId);
      setResult(res.data);
      setFromMock(res.fromMock);
    } catch (e) {
      console.error('[Report] 解析失败:', e);
      Taro.showToast({ title: '解析失败，请稍后重试', icon: 'none' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <View className={styles.page}>
      <View className={styles.card}>
        <Text className={styles.cardTitle}>报告文字</Text>
        <Textarea
          className={styles.textarea}
          value={text}
          placeholder={PLACEHOLDER}
          maxlength={-1}
          onInput={(e) => setText(e.detail.value)}
        />
        <Button className={classnames(styles.primaryBtn, loading && styles.btnDisabled)} onClick={handleParse}>
          {loading ? '解析中…' : '开始解读'}
        </Button>
        <Text className={styles.hint}>仅对报告文字做结构化整理，不做影像判读、不做图片识别。</Text>
      </View>

      {loading ? <StateView type="loading" text="正在整理报告内容…" /> : null}

      {!loading && result ? (
        <View className={styles.result}>
          {fromMock ? <Text className={styles.mockNotice}>{MOCK_NOTICE}</Text> : null}

          <View className={styles.card}>
            <Text className={styles.cardTitle}>结构化要点（{result.findings.length} 处）</Text>
            {result.findings.length === 0 ? (
              <Text className={styles.emptyLine}>未整理出结构化要点。</Text>
            ) : (
              result.findings.map((f, i) => (
                <View key={`f-${i}`} className={styles.finding}>
                  {FINDING_FIELDS.map((field) => {
                    const value = f[field.key];
                    if (!value) {
                      return null;
                    }
                    return (
                      <View key={`${i}-${String(field.key)}`} className={styles.kvRow}>
                        <Text className={styles.kvLabel}>{field.label}</Text>
                        <Text className={styles.kvValue}>{String(value)}</Text>
                      </View>
                    );
                  })}
                </View>
              ))
            )}
          </View>

          {result.key_signs.length > 0 ? (
            <View className={styles.card}>
              <Text className={styles.cardTitle}>提示关注的征象</Text>
              <View className={styles.tagWrap}>
                {result.key_signs.map((k, i) => (
                  <Text key={`k-${i}`} className={styles.tag}>
                    {k}
                  </Text>
                ))}
              </View>
            </View>
          ) : null}

          {result.followup_suggestions.length > 0 ? (
            <View className={styles.card}>
              <Text className={styles.cardTitle}>随访建议</Text>
              {result.followup_suggestions.map((s, i) => (
                <View key={`s-${i}`} className={styles.suggestion}>
                  <Text className={styles.suggestionText}>{s.text}</Text>
                  <Text className={styles.suggestionSource}>来源：{s.source}</Text>
                </View>
              ))}
            </View>
          ) : null}

          {result.diff_prev ? (
            <View className={styles.card}>
              <Text className={styles.cardTitle}>与上次对比</Text>
              <Text className={styles.diffHead}>
                上次 {result.diff_prev.previous_count} 处 → 本次 {result.diff_prev.current_count} 处
              </Text>
              {result.diff_prev.size_changes && result.diff_prev.size_changes.length > 0
                ? result.diff_prev.size_changes.map((c, i) => (
                    <Text key={`sc-${i}`} className={styles.diffChange}>
                      大小变化：{c.site} {c.before} → {c.after}
                    </Text>
                  ))
                : null}
              {result.diff_prev.added.length > 0 ? (
                <Text className={styles.diffAdded}>新增：{result.diff_prev.added.join('；')}</Text>
              ) : null}
              {result.diff_prev.removed.length > 0 ? (
                <Text className={styles.diffRemoved}>消失：{result.diff_prev.removed.join('；')}</Text>
              ) : null}
              {result.diff_prev.unchanged.length > 0 ? (
                <Text className={styles.diffSame}>无变化：{result.diff_prev.unchanged.join('；')}</Text>
              ) : null}
            </View>
          ) : null}
        </View>
      ) : null}

      <DisclaimerBar text={REPORT_DISCLAIMER} />
    </View>
  );
};

export default ReportPage;
