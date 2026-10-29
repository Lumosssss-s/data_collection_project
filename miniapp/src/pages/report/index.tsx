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

          {/* 概览：仅事实计数，不作医学判断 */}
          <View className={styles.overview}>
            <View className={styles.overviewStat}>
              <Text className={styles.overviewValue}>{result.findings.length}</Text>
              <Text className={styles.overviewLabel}>处要点</Text>
            </View>
            <View className={styles.overviewDivider} />
            <View className={styles.overviewStat}>
              <Text className={styles.overviewValue}>{result.key_signs.length}</Text>
              <Text className={styles.overviewLabel}>项需关注</Text>
            </View>
            <View className={styles.overviewDivider} />
            <View className={styles.overviewStat}>
              <Text className={styles.overviewValue}>{result.followup_suggestions.length}</Text>
              <Text className={styles.overviewLabel}>条随访建议</Text>
            </View>
          </View>

          <View className={styles.section}>
            <View className={styles.sectionHead}>
              <Text className={styles.sectionIndex}>01</Text>
              <Text className={styles.sectionTitle}>结构化要点</Text>
            </View>
            {result.findings.length === 0 ? (
              <View className={styles.emptyBox}>
                <View className={styles.emptyIcon} />
                <Text className={styles.emptyLine}>未整理出结构化要点。</Text>
              </View>
            ) : (
              result.findings.map((f, i) => (
                <View key={`f-${i}`} className={styles.finding}>
                  <Text className={styles.findingTitle}>发现 {i + 1}</Text>
                  <View className={styles.kvGrid}>
                    {FINDING_FIELDS.map((field) => {
                      const value = f[field.key];
                      if (!value) {
                        return null;
                      }
                      return (
                        <View key={`${i}-${String(field.key)}`} className={styles.kvItem}>
                          <Text className={styles.kvLabel}>{field.label}</Text>
                          <Text className={styles.kvValue}>{String(value)}</Text>
                        </View>
                      );
                    })}
                  </View>
                </View>
              ))
            )}
          </View>

          {result.key_signs.length > 0 ? (
            <View className={styles.section}>
              <View className={styles.sectionHead}>
                <Text className={styles.sectionIndex}>02</Text>
                <Text className={styles.sectionTitle}>提示关注的征象</Text>
              </View>
              <View className={styles.attentionList}>
                {result.key_signs.map((k, i) => (
                  <View key={`k-${i}`} className={styles.attentionItem}>
                    <Text className={styles.attentionMark}>!</Text>
                    <Text className={styles.attentionText}>{k}</Text>
                  </View>
                ))}
              </View>
            </View>
          ) : null}

          {result.followup_suggestions.length > 0 ? (
            <View className={styles.section}>
              <View className={styles.sectionHead}>
                <Text className={styles.sectionIndex}>03</Text>
                <Text className={styles.sectionTitle}>下一步做什么</Text>
              </View>
              <View className={styles.stepList}>
                {result.followup_suggestions.map((s, i) => (
                  <View key={`s-${i}`} className={styles.step}>
                    <View className={styles.stepIndexWrap}>
                      <Text className={styles.stepIndex}>{i + 1}</Text>
                    </View>
                    <View className={styles.stepBody}>
                      <Text className={styles.stepText}>{s.text}</Text>
                      <Text className={styles.stepSource}>来源：{s.source}</Text>
                    </View>
                  </View>
                ))}
              </View>
            </View>
          ) : null}

          {result.diff_prev ? (
            <View className={styles.section}>
              <View className={styles.sectionHead}>
                <Text className={styles.sectionIndex}>04</Text>
                <Text className={styles.sectionTitle}>与上次对比</Text>
              </View>

              <View className={styles.diffRow}>
                <Text className={styles.diffLabel}>病灶数量</Text>
                <Text className={styles.diffValue}>
                  上次 {result.diff_prev.previous_count} 处 → 本次 {result.diff_prev.current_count} 处
                </Text>
              </View>

              {result.diff_prev.size_changes && result.diff_prev.size_changes.length > 0
                ? result.diff_prev.size_changes.map((c, i) => (
                    <View key={`sc-${i}`} className={styles.diffRow}>
                      <Text className={styles.diffLabel}>{c.site}</Text>
                      <Text className={styles.diffValue}>
                        {c.before} → {c.after}
                      </Text>
                    </View>
                  ))
                : null}

              {result.diff_prev.added.length > 0 ? (
                <View className={styles.diffItem}>
                  <Text className={classnames(styles.diffSymbol, styles.diffSymbolWarn)}>+</Text>
                  <Text className={styles.diffDescription}>新增：{result.diff_prev.added.join('；')}</Text>
                </View>
              ) : null}

              {result.diff_prev.removed.length > 0 ? (
                <View className={styles.diffItem}>
                  <Text className={classnames(styles.diffSymbol, styles.diffSymbolGood)}>−</Text>
                  <Text className={styles.diffDescription}>消失：{result.diff_prev.removed.join('；')}</Text>
                </View>
              ) : null}

              {result.diff_prev.unchanged.length > 0 ? (
                <View className={styles.diffItem}>
                  <Text className={classnames(styles.diffSymbol, styles.diffSymbolSame)}>=</Text>
                  <Text className={styles.diffDescription}>无变化：{result.diff_prev.unchanged.join('；')}</Text>
                </View>
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
