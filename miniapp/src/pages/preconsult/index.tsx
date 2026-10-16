import React, { useEffect, useRef, useState } from 'react';
import { View, Text, ScrollView, Input, Button } from '@tarojs/components';
import classnames from 'classnames';
import DisclaimerBar from '@/components/DisclaimerBar';
import {
  createPreconsultSession,
  sendPreconsultMessage
} from '@/services/patientService';
import { MOCK_NOTICE, PRECONSULT_DISCLAIMER, RISK_LABELS } from '@/utils/constants';
import type { PreconsultMessageData } from '@/types/api';
import styles from './index.module.scss';

interface ChatMessage {
  id: string;
  role: 'user' | 'bot' | 'warn' | 'tip';
  text: string;
}

let msgSeq = 0;
function nextId(): string {
  msgSeq += 1;
  return `msg-${msgSeq}`;
}

const PreconsultPage: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [result, setResult] = useState<PreconsultMessageData | null>(null);
  const [sending, setSending] = useState(false);
  const [ready, setReady] = useState(false);
  const scrollRef = useRef<string>('');

  const pushMessage = (role: ChatMessage['role'], text: string) => {
    const id = nextId();
    setMessages((prev) => [...prev, { id, role, text }]);
    scrollRef.current = id;
  };

  const initSession = async () => {
    const res = await createPreconsultSession();
    const data = res.data;
    setSessionId(data.session_id);
    setReady(true);
    setMessages([]);
    if (res.fromMock) {
      pushMessage('tip', MOCK_NOTICE);
    }
    const prompt = data.next_question ? data.next_question.prompt : '请描述您的主要不适。';
    pushMessage('bot', prompt);
    console.info('[Preconsult] 会话已创建:', data.session_id, 'mock=', res.fromMock);
  };

  useEffect(() => {
    initSession().catch((e) => {
      console.error('[Preconsult] 初始化失败:', e);
      pushMessage('warn', '服务暂时不可用，请稍后重试。');
    });
    // 仅在首次挂载时创建会话
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || !sessionId || sending) {
      return;
    }
    setInput('');
    pushMessage('user', text);
    setSending(true);
    try {
      const res = await sendPreconsultMessage(sessionId, text);
      const data = res.data;

      data.red_flags.forEach((flag) => {
        pushMessage('warn', `⚠️ ${flag.action}`);
      });

      if (data.next_question) {
        pushMessage('bot', data.next_question.prompt);
      } else {
        pushMessage('bot', '信息采集已完成，下面是为您整理的建议。');
      }
      setResult(data);
    } catch (e) {
      console.error('[Preconsult] 发送失败:', e);
      pushMessage('warn', '发送失败，请稍后重试。');
    } finally {
      setSending(false);
    }
  };

  const riskKey = result ? result.risk_level : 'routine';

  return (
    <View className={styles.page}>
      <ScrollView className={styles.chat} scrollY scrollIntoView={scrollRef.current} scrollWithAnimation>
        <View className={styles.chatInner}>
          {messages.map((m) => (
            <View
              key={m.id}
              className={classnames(
                styles.bubble,
                m.role === 'user' && styles.bubbleUser,
                m.role === 'bot' && styles.bubbleBot,
                m.role === 'warn' && styles.bubbleWarn,
                m.role === 'tip' && styles.bubbleTip
              )}
            >
              <Text className={styles.bubbleText}>{m.text}</Text>
            </View>
          ))}
        </View>
      </ScrollView>

      <View className={styles.inputBar}>
        <Input
          className={styles.input}
          value={input}
          placeholder="请描述您的不适"
          confirmType="send"
          disabled={!ready}
          onInput={(e) => setInput(e.detail.value)}
          onConfirm={handleSend}
        />
        <Button className={classnames(styles.sendBtn, (!ready || sending) && styles.sendBtnDisabled)} onClick={handleSend}>
          {sending ? '发送中' : '发送'}
        </Button>
      </View>

      {result && (
        <View className={styles.panel}>
          <View className={styles.card}>
            <Text className={styles.cardTitle}>目前判断</Text>
            <View className={classnames(styles.riskTag, styles[riskKey] || styles.routine)}>
              <Text className={styles.riskTagText}>{result.risk_label || RISK_LABELS[riskKey] || riskKey}</Text>
            </View>
          </View>

          {result.department && result.department.primary ? (
            <View className={styles.card}>
              <Text className={styles.cardTitle}>建议就诊科室</Text>
              <Text className={styles.cardText}>{result.department.primary}</Text>
              {result.department.alt && result.department.alt.length > 0 && (
                <Text className={styles.cardSub}>也可考虑：{result.department.alt.join('、')}</Text>
              )}
            </View>
          ) : null}

          {result.visit_prep && result.visit_prep.length > 0 && (
            <View className={styles.card}>
              <Text className={styles.cardTitle}>就诊前请准备</Text>
              {result.visit_prep.map((t, i) => (
                <Text key={`prep-${i}`} className={styles.cardItem}>
                  · {t}
                </Text>
              ))}
            </View>
          )}

          {result.symptoms && result.symptoms.length > 0 && (
            <View className={styles.card}>
              <Text className={styles.cardTitle}>您提到的症状</Text>
              <View className={styles.tagWrap}>
                {result.symptoms.map((s, i) => (
                  <Text key={`sym-${i}`} className={styles.tag}>
                    {s}
                  </Text>
                ))}
              </View>
            </View>
          )}
        </View>
      )}

      <DisclaimerBar text={PRECONSULT_DISCLAIMER} />
    </View>
  );
};

export default PreconsultPage;
