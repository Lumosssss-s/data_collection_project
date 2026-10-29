import Taro from '@tarojs/taro';
import type { ApiEnvelope } from '@/types/api';

/**
 * 后端 API 基地址。
 *
 * H5：跟随访问者所在主机 —— PC 打开走 localhost，手机用局域网 IP 打开则自动走该 IP，
 * 无需硬编码 IP（宿主机 docker 映射 8002 → 容器 8001）。
 * 小程序：真机需改为局域网 IP 或已备案 HTTPS 域名，并在小程序后台配置 request 合法域名。
 */
export const API_BASE = (() => {
  if (process.env.TARO_ENV === 'h5' && typeof location !== 'undefined' && location.hostname) {
    return 'http://' + location.hostname + ':8002/api/v1';
  }
  return 'http://localhost:8002/api/v1';
})();

/** 单次请求超时（毫秒） */
const TIMEOUT = 15000;

/** 长耗时接口超时（报告解析走 LLM 真实抽取，实测约 40s） */
export const LONG_TIMEOUT = 60000;

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

/** 请求选项：可覆盖单次超时（毫秒） */
export interface RequestOptions {
  timeout?: number;
}

async function request<T>(
  method: 'GET' | 'POST',
  path: string,
  data?: Record<string, unknown>,
  params?: Record<string, unknown>,
  options?: RequestOptions
): Promise<T> {
  const url = buildUrl(path, params);
  console.info(`[API] ${method} ${url}`);

  const res = await Taro.request({
    url,
    method,
    data,
    timeout: options && options.timeout ? options.timeout : TIMEOUT,
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
  get: <T>(path: string, params?: Record<string, unknown>, options?: RequestOptions) =>
    request<T>('GET', path, undefined, params, options),
  post: <T>(path: string, data?: Record<string, unknown>, options?: RequestOptions) =>
    request<T>('POST', path, data, undefined, options)
};
