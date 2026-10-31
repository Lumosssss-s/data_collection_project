import Taro from '@tarojs/taro';
import { API_BASE } from './api';

/**
 * 循证问答服务：POST /qa/stream（SSE 事件流）。
 *
 * - H5：fetch + ReadableStream 增量解析，逐字渲染（需预览代理服务器透传 SSE 分块）
 * - 小程序：Taro.request 无增量读取，等完整响应后一次性解析全部事件（仅少实时感，功能一致）
 */

export interface QaSource {
  data_type?: string;
  title?: string;
  cancer_type?: string;
  breadcrumb?: string;
  content?: string;
}

export interface QaChunk {
  type: 'status' | 'content' | 'sources' | 'end' | 'error';
  data?: string;
  sources?: QaSource[];
  cancer_types?: string[];
}

export interface QaPayload {
  question: string;
  top_k?: number;
  history?: { role: string; content: string }[];
  filters?: Record<string, unknown>;
}

/** 解析单个 SSE 事件块（"data: {...}"），非法块静默跳过 */
function emitBlock(block: string, onChunk: (c: QaChunk) => void): void {
  for (const line of block.split('\n')) {
    if (line.startsWith('data: ')) {
      try {
        onChunk(JSON.parse(line.slice(6)) as QaChunk);
      } catch (e) {
        console.warn('[QA] SSE 事件解析失败:', e);
      }
    }
  }
}

/** H5：流式读取，逐块回调 */
async function askStreamH5(payload: QaPayload, onChunk: (c: QaChunk) => void): Promise<void> {
  const res = await fetch(API_BASE + '/qa/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!res.ok || !res.body) {
    throw new Error(`问答请求失败（HTTP ${res.status}）`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buf += decoder.decode(value, { stream: true });
    let idx = buf.indexOf('\n\n');
    while (idx >= 0) {
      emitBlock(buf.slice(0, idx), onChunk);
      buf = buf.slice(idx + 2);
      idx = buf.indexOf('\n\n');
    }
  }
}

/** 小程序：等响应完整后统一解析（SSE 全文一次性到达） */
function askStreamWeapp(payload: QaPayload, onChunk: (c: QaChunk) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    Taro.request({
      url: API_BASE + '/qa/stream',
      method: 'POST',
      data: payload,
      timeout: 180000, // 问答走 LLM 生成，长尾可能超过 60s
      header: { 'Content-Type': 'application/json', Accept: 'text/event-stream' }
    })
      .then((res) => {
        if (res.statusCode >= 400) {
          throw new Error(`问答请求失败（HTTP ${res.statusCode}）`);
        }
        const text = typeof res.data === 'string' ? res.data : '';
        if (!text) {
          throw new Error('问答响应为空');
        }
        for (const block of text.split('\n\n')) {
          emitBlock(block, onChunk);
        }
        resolve();
      })
      .catch(reject);
  });
}

/** 发起流式问答；H5 逐字回调，小程序一次性回调，接口签名一致 */
export function askStream(
  payload: QaPayload,
  onChunk: (c: QaChunk) => void
): Promise<void> {
  return process.env.TARO_ENV === 'h5'
    ? askStreamH5(payload, onChunk)
    : askStreamWeapp(payload, onChunk);
}
