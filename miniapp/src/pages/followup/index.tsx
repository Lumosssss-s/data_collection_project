import React, { useState } from 'react';
import { View, Text, Input, Button, Textarea } from '@tarojs/components';
import Taro, { useDidShow } from '@tarojs/taro';
import classnames from 'classnames';
import StateView from '@/components/StateView';
import DisclaimerBar from '@/components/DisclaimerBar';
import { fetchFollowupTasks, submitFollowupRecord } from '@/services/patientService';
import { MOCK_NOTICE } from '@/utils/constants';
import type { FollowupRecordData, FollowupTask } from '@/types/api';
import styles from './index.module.scss';

const SEVERITY_OPTIONS = ['轻度', '中度', '重度', '危及生命'];

const FollowupPage: React.FC = () => {
  const [patientId, setPatientId] = useState('');
  const [tasks, setTasks] = useState<FollowupTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [fromMock, setFromMock] = useState(false);
  const [openTaskId, setOpenTaskId] = useState('');
  const [severity, setSeverity] = useState('');
  const [feedback, setFeedback] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [lastResult, setLastResult] = useState<FollowupRecordData | null>(null);

  useDidShow(() => {
    try {
      const saved = Taro.getStorageSync('patient_id');
      if (saved) {
        setPatientId(String(saved));
      }
    } catch (e) {
      console.error('[Followup] 读取随访编号失败:', e);
    }
  });

  const handleQuery = async () => {
    const id = patientId.trim();
    if (!id) {
      Taro.showToast({ title: '请输入随访编号', icon: 'none' });
      return;
    }
    setLoading(true);
    try {
      const res = await fetchFollowupTasks(id);
      setTasks(res.data.tasks);
      setFromMock(res.fromMock);
      setLoaded(true);
      setLastResult(null);
      console.info('[Followup] 查询完成，任务数:', res.data.tasks.length, 'mock=', res.fromMock);
    } catch (e) {
      console.error('[Followup] 查询失败:', e);
      Taro.showToast({ title: '查询失败，请稍后重试', icon: 'none' });
    } finally {
      setLoading(false);
    }
  };

  const toggleTask = (taskId: string) => {
    setOpenTaskId((prev) => (prev === taskId ? '' : taskId));
    setSeverity('');
    setFeedback('');
  };

  const handleSubmit = async (task: FollowupTask) => {
    if (!severity && !feedback.trim()) {
      Taro.showToast({ title: '请选择不适程度或填写情况', icon: 'none' });
      return;
    }
    setSubmitting(true);
    try {
      const res = await submitFollowupRecord(task.task_id, severity, feedback.trim());
      setLastResult(res.data);
      setOpenTaskId('');
      if (res.data.alerts.length > 0) {
        Taro.showToast({ title: '已记录，请留意提醒', icon: 'none' });
      } else {
        Taro.showToast({ title: '已记录', icon: 'success' });
      }
      await handleQuery();
    } catch (e) {
      console.error('[Followup] 提交失败:', e);
      Taro.showToast({ title: '提交失败，请稍后重试', icon: 'none' });
    } finally {
      setSubmitting(false);
    }
  };

  const dueCount = tasks.filter((t) => t.due && t.status !== 'done').length;

  return (
    <View className={styles.page}>
      <View className={styles.card}>
        <Text className={styles.cardTitle}>随访编号</Text>
        <View className={styles.row}>
          <Input
            className={styles.input}
            value={patientId}
            placeholder="请输入您的随访编号"
            onInput={(e) => setPatientId(e.detail.value)}
          />
          <Button className={styles.queryBtn} onClick={handleQuery}>
            查询
          </Button>
        </View>
      </View>

      {loading ? <StateView type="loading" text="正在查询随访安排…" /> : null}

      {!loading && loaded && tasks.length === 0 ? (
        <StateView type="empty" text="暂无随访安排，或该编号下没有待办任务" />
      ) : null}

      {!loading && tasks.length > 0 ? (
        <View className={styles.list}>
          {fromMock ? <Text className={styles.mockNotice}>{MOCK_NOTICE}</Text> : null}

          <View className={styles.summary}>
            <Text className={styles.summaryText}>共 </Text>
            <Text className={styles.summaryNum}>{tasks.length}</Text>
            <Text className={styles.summaryText}> 项随访安排，其中 </Text>
            <Text className={dueCount > 0 ? styles.summaryNumWarn : styles.summaryNum}>{dueCount}</Text>
            <Text className={styles.summaryText}> 项已到期</Text>
          </View>

          {tasks.map((task) => (
            <View
              key={task.task_id}
              className={classnames(
                styles.taskCard,
                task.status === 'done' && styles.taskCardDone,
                task.status !== 'done' && task.due && styles.taskCardDue
              )}
            >
              <View className={styles.taskHead}>
                <Text className={styles.taskTitle}>{task.timepoint}</Text>
                {task.status === 'done' ? (
                  <Text className={styles.statusDone}>已反馈</Text>
                ) : task.due ? (
                  <Text className={styles.statusDue}>已到期</Text>
                ) : (
                  <Text className={styles.statusPending}>待反馈</Text>
                )}
              </View>
              <View className={styles.metaRow}>
                <Text className={styles.metaLabel}>检查项目</Text>
                <Text className={styles.metaValue}>{task.items.join('、')}</Text>
              </View>
              <View className={styles.metaRow}>
                <Text className={styles.metaLabel}>计划日期</Text>
                <Text className={styles.metaValue}>{task.due_date}</Text>
              </View>

              {task.status !== 'done' ? (
                <Button className={styles.feedbackBtn} onClick={() => toggleTask(task.task_id)}>
                  {openTaskId === task.task_id ? '收起' : '填写反馈'}
                </Button>
              ) : null}

              {openTaskId === task.task_id ? (
                <View className={styles.feedbackForm}>
                  <Text className={styles.formLabel}>不适程度（可选）</Text>
                  <View className={styles.severityRow}>
                    {SEVERITY_OPTIONS.map((opt) => (
                      <Text
                        key={opt}
                        className={classnames(styles.severityChip, severity === opt && styles.severityChipActive)}
                        onClick={() => setSeverity(opt)}
                      >
                        {opt}
                      </Text>
                    ))}
                  </View>
                  <Text className={styles.formLabel}>近况描述（可选）</Text>
                  <Textarea
                    className={styles.textarea}
                    value={feedback}
                    placeholder="例如：最近有些乏力和腹泻"
                    maxlength={200}
                    onInput={(e) => setFeedback(e.detail.value)}
                  />
                  <Button
                    className={classnames(styles.submitBtn, submitting && styles.btnDisabled)}
                    onClick={() => handleSubmit(task)}
                  >
                    {submitting ? '提交中…' : '提交反馈'}
                  </Button>
                </View>
              ) : null}
            </View>
          ))}
        </View>
      ) : null}

      {lastResult ? (
        <View className={styles.alertCard}>
          <Text className={styles.alertTitle}>刚刚的反馈已记录</Text>
          <Text className={styles.alertText}>评估程度：{lastResult.grade_label}</Text>
          {lastResult.alerts.length > 0
            ? lastResult.alerts.map((a) => (
                <Text key={a.alert_id} className={styles.alertWarn}>
                  ⚠️ {a.term}：{a.level_label}
                </Text>
              ))
            : null}
        </View>
      ) : null}

      <DisclaimerBar />
    </View>
  );
};

export default FollowupPage;
