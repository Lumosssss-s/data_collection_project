import React, { useCallback, useEffect, useRef, useState } from 'react';
import { View, Text, Textarea, Button, ScrollView } from '@tarojs/components';
import Taro from '@tarojs/taro';
import classnames from 'classnames';
import { askStream, type QaChunk, type QaSource } from '@/services/qaService';
import { DISCLAIMER, SEEK_HELP } from '@/utils/constants';
import styles from './index.module.scss';

/** 会话存储键（与 PC 端 localStorage 键同名，便于口径统一） */
const QA_STORAGE_KEY = 'medical_rag_qa_state';

/** 欢迎态示例问题（科普向，不含诊断诱导） */
const SAMPLE_QUESTIONS = [
  '肺癌靶向治疗后常见的不良反应有哪些？',
  '术后复查一般间隔多久一次？',
  '化疗期间饮食上需要注意什么？'
];

interface QaMessage {
  role: 'user' | 'assistant';
  content: string;
  sources?: QaSource[];
  status?: string;
  streaming?: boolean;
}

/** 兜底恢复历史（跨次打开保留多轮对话） */
function loadMessages(): QaMessage[] {
  try {
    const saved = Taro.getStorageSync(QA_STORAGE_KEY);
    if (saved && Array.isArray(saved.messages)) {
      return saved.messages.map((m: QaMessage) => ({ ...m, streaming: false }));
    }
  } catch (e) {
    console.warn('[QA] 读取会话失败:', e);
  }
  return [];
}

function saveMessages(messages: QaMessage[]): void {
  try {
    Taro.setStorageSync(QA_STORAGE_KEY, { messages });
  } catch (e) {
    console.warn('[QA] 保存会话失败:', e);
  }
}

/** 行内渲染：识别 **加粗**，其余原样输出 */
function renderInline(line: string, keyPrefix: string): React.ReactNode {
  const parts = line.split(/(\*\*[^*]+\*\*)/g).filter((p) => p !== '');
  return parts.map((p, i) =>
    p.startsWith('**') && p.endsWith('**') ? (
      <Text key={`${keyPrefix}-b${i}`} className={styles.mdBold}>
        {p.slice(2, -2)}
      </Text>
    ) : (
      <Text key={`${keyPrefix}-t${i}`}>{p}</Text>
    )
  );
}

/**
 * 轻量富文本渲染：把 LLM 返回的 markdown 常见结构（标题 / 有序列表 / 无序列表 / 段落）
 * 转成可读排版。不引第三方库，只覆盖实际会出现的形态。
 */
function renderRich(text: string): React.ReactNode {
  const lines = text.split('\n');
  return lines.map((raw, i) => {
    const line = raw.replace(/\s+$/, '');
    const k = `l${i}`;

    if (!line.trim()) {
      return <View key={k} className={styles.mdGap} />;
    }
    const head = line.match(/^#{1,4}\s+(.*)$/);
    if (head) {
      return (
        <View key={k} className={styles.mdHead}>
          {renderInline(head[1], k)}
        </View>
      );
    }
    const ordered = line.match(/^(\d+)[.、)]\s*(.*)$/);
    if (ordered) {
      return (
        <View key={k} className={styles.mdRow}>
          <Text className={styles.mdMarker}>{ordered[1]}.</Text>
          <Text className={styles.mdBody}>{renderInline(ordered[2], k)}</Text>
        </View>
      );
    }
    const bullet = line.match(/^[-*•]\s+(.*)$/);
    if (bullet) {
      return (
        <View key={k} className={styles.mdRow}>
          <Text className={styles.mdMarker}>·</Text>
          <Text className={styles.mdBody}>{renderInline(bullet[1], k)}</Text>
        </View>
      );
    }
    return (
      <View key={k} className={styles.mdPara}>
        {renderInline(line, k)}
      </View>
    );
  });
}

const QaPage: React.FC = () => {
  const [messages, setMessages] = useState<QaMessage[]>(loadMessages);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const [scrollTo, setScrollTo] = useState('');
  const inputRef = useRef('');

  const updateMessages = useCallback((updater: (prev: QaMessage[]) => QaMessage[]) => {
    setMessages((prev) => {
      const next = updater(prev);
      saveMessages(next);
      return next;
    });
  }, []);

  useEffect(() => {
    if (messages.length > 0) {
      setScrollTo(`msg-${messages.length - 1}`);
    }
  }, [messages.length]);

  const submit = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!q || sending) {
        return;
      }
      setInput('');
      inputRef.current = '';
      Taro.hideKeyboard();

      // 多轮历史：取已完结的往轮问答（排除流式占位）
      const priorHistory = messages
        .filter((m) => !(m.role === 'assistant' && m.streaming))
        .reduce<{ role: string; content: string }[]>((acc, m) => {
          if (m.content && (m.role === 'user' || m.role === 'assistant')) {
            acc.push({ role: m.role, content: m.content });
          }
          return acc;
        }, []);

      const placeholder: QaMessage = {
        role: 'assistant',
        content: '',
        status: '正在检索循证依据…',
        streaming: true
      };
      updateMessages((prev) => [...prev, { role: 'user', content: q }, placeholder]);
      setSending(true);

      /** 只更新列表末尾的 AI 占位；append 为增量追加正文 */
      const patchLast = (patch: Partial<QaMessage>, append?: string) => {
        updateMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (!last || last.role !== 'assistant') {
            return prev;
          }
          next[next.length - 1] = {
            ...last,
            ...patch,
            ...(append ? { content: last.content + append } : {})
          };
          return next;
        });
      };

      try {
        await askStream({ question: q, top_k: 5, history: priorHistory }, (chunk: QaChunk) => {
          if (chunk.type === 'content') {
            patchLast({ status: '' }, chunk.data || '');
          } else if (chunk.type === 'status') {
            patchLast({ status: chunk.data || '' });
          } else if (chunk.type === 'sources') {
            patchLast({ sources: chunk.sources || [] });
          } else if (chunk.type === 'end') {
            patchLast({ streaming: false, status: '' });
          } else if (chunk.type === 'error') {
            patchLast({ streaming: false, status: '', content: '问答失败：' + (chunk.data || '') });
          }
        });
        patchLast({ streaming: false, status: '' });
      } catch (e) {
        patchLast({
          streaming: false,
          status: '',
          content: '请求失败：' + (e instanceof Error ? e.message : String(e))
        });
      } finally {
        setSending(false);
      }
    },
    [sending, messages, updateMessages]
  );

  const send = useCallback(() => submit(inputRef.current), [submit]);

  const newSession = () => {
    if (sending) {
      return;
    }
    Taro.showModal({
      title: '新建会话',
      content: '将清空当前对话记录，确定吗？',
      confirmText: '开始新会话',
      success: (res) => {
        if (res.confirm) {
          setMessages([]);
          saveMessages([]);
          setExpanded({});
          setInput('');
          inputRef.current = '';
        }
      }
    });
  };

  const toggleSources = (idx: number) => {
    setExpanded((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  const onInput = (e: { detail: { value: string } }) => {
    setInput(e.detail.value);
    inputRef.current = e.detail.value;
  };

  return (
    <View className={styles.page}>
      {/* 顶栏：标题 + 新会话，替代原先大标题长描述，压缩纵向占用 */}
      <View className={styles.topBar}>
        <View className={styles.topTitle}>
          <Text className={styles.topTitleText}>智能问答</Text>
          <Text className={styles.topSub}>附循证出处</Text>
        </View>
        <Text className={classnames(styles.topAction, sending && styles.topActionOff)} onClick={newSession}>
          新会话
        </Text>
      </View>

      <ScrollView
        scrollY
        scrollIntoView={scrollTo}
        scrollWithAnimation
        className={styles.chat}
        enhanced
        showScrollbar={false}
      >
        {messages.length === 0 ? (
          <View className={styles.welcome}>
            <Text className={styles.welcomeTitle}>可以这样问</Text>
            {SAMPLE_QUESTIONS.map((q, i) => (
              <View key={i} className={styles.sample} onClick={() => submit(q)}>
                <Text className={styles.sampleText}>{q}</Text>
                <Text className={styles.sampleArrow}>›</Text>
              </View>
            ))}
          </View>
        ) : (
          messages.map((m, idx) =>
            m.role === 'user' ? (
              <View key={`msg-${idx}`} id={`msg-${idx}`} className={styles.rowUser}>
                <View className={styles.bubbleUser}>
                  <Text className={styles.bubbleUserText}>{m.content}</Text>
                </View>
              </View>
            ) : (
              <View key={`msg-${idx}`} id={`msg-${idx}`} className={styles.rowAi}>
                <View className={styles.bubbleAi}>
                  {m.streaming && !m.content ? (
                    <View className={styles.aiStatus}>
                      <View className={styles.spinner} />
                      <Text className={styles.aiStatusText}>{m.status || '正在生成回答…'}</Text>
                    </View>
                  ) : (
                    <View className={styles.aiContent}>
                      {renderRich(m.content)}
                      {m.streaming ? <Text className={styles.cursor}>▌</Text> : null}
                    </View>
                  )}

                  {m.sources && m.sources.length > 0 ? (
                    <View className={styles.sources}>
                      <Text className={styles.sourcesToggle} onClick={() => toggleSources(idx)}>
                        循证来源 {m.sources.length} 条{expanded[idx] ? ' ▾' : ' ▸'}
                      </Text>
                      {expanded[idx]
                        ? m.sources.map((s, i) => (
                            <View key={i} className={styles.sourceItem}>
                              <Text className={styles.sourceTitle}>
                                {i + 1}. {s.title || ''}
                              </Text>
                              <Text className={styles.sourceMeta}>
                                {s.data_type === 'doc'
                                  ? '指南'
                                  : s.data_type === 'rec'
                                    ? '推荐条目'
                                    : s.data_type === 'drug'
                                      ? '说明书'
                                      : '资料'}
                                {s.cancer_type ? ` · ${s.cancer_type}` : ''}
                                {s.breadcrumb ? ` · ${s.breadcrumb}` : ''}
                              </Text>
                              {(s.content || '').length > 0 ? (
                                <Text className={styles.sourceExcerpt}>{(s.content || '').substring(0, 120)}</Text>
                              ) : null}
                            </View>
                          ))
                        : null}
                    </View>
                  ) : null}
                </View>
              </View>
            )
          )
        )}
      </ScrollView>

      {/* 输入区：胶囊输入壳 + 右侧悬浮发送钮，按钮绝对定位，textarea 独占整行避开 flex 压缩 bug */}
      <View className={styles.composer}>
        <View className={styles.inputShell}>
          <Textarea
            className={styles.input}
            value={input}
            placeholder="输入您的健康疑问…"
            maxlength={500}
            showConfirmBar={false}
            onInput={onInput}
          />
          <View className={styles.sendWrap}>
            <Button
              className={classnames(styles.sendBtn, (!input.trim() || sending) && styles.sendBtnOff)}
              onClick={send}
              disabled={sending || !input.trim()}
            >
              {sending ? '生成中' : '发送'}
            </Button>
          </View>
        </View>
      </View>

      <View className={styles.disclaimer}>
        <Text className={styles.disclaimerText}>
          {DISCLAIMER}
          {SEEK_HELP}
        </Text>
      </View>
    </View>
  );
};

export default QaPage;
