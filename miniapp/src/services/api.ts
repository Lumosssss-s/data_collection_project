import Taro from '@tarojs/taro';
import type { ApiEnvelope } from '@/types/api';

/**
 * 后端 API 基地址。
 *
 * - H5 预览 / 本机调试：留 localhost（宿主机 docker 映射 8002 → 容器 8001）
 * - 微信真机调试：改为局域网 IP（如 http://192.168.1.10:8002/api/v1）
 *   并在小程序后台配置 request 合法域名（正式发布需 HTTPS + 已备案域名）
 */
export const API_BASE = 'http://localhost:8002/api/v1';

/** 单次请求超时（毫秒） */
const TIMEOUT = 15000;

/** 拼接 query 参数（过滤空值） */
function buildUrl(path: string, params?: Record<string, unknown>): string {
  const url = API_BASE + path;
  if (!params) {
    return url;
  }
  const qs = Object.keys(params)
    .filter((k) => params[k] !== undefined && params[k] !== null && params[k] !== '')
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(String(params[k]))}`)
    .join('&');
  return qs ? `${url}?${qs}` : url;
}

async function request<T>(
  method: 'GET' | 'POST',
  path: string,
  data?: Record<string, unknown>,
  params?: Record<string, unknown>
): Promise<T> {
  const url = buildUrl(path, params);
  console.info(`[API] ${method} ${url}`);

  const res = await Taro.request({
    url,
    method,
    data,
    timeout: TIMEOUT,
    header: { 'Content-Type': 'application/json' }
  });

  const body = res.data as ApiEnvelope<T>;
  if (res.statusCode >= 400 || !body || body.success !== true) {
    const msg = (body && body.message) || `请求失败（HTTP ${res.statusCode}）`;
    console.error('[API] 业务失败:', msg);
    throw new Error(msg);
  }
  return body.data;
}

export const api = {
  get: <T>(path: string, params?: Record<string, unknown>) =>
    request<T>('GET', path, undefined, params),
  post: <T>(path: string, data?: Record<string, unknown>) => request<T>('POST', path, data)
};
