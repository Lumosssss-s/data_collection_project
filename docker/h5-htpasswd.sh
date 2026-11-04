#!/bin/sh
# 容器启动钩子（nginx 官方镜像会执行 /docker-entrypoint.d/*.sh）：
# 从环境变量生成 H5 预览的 Basic Auth 凭据文件，密码不写死在任何配置文件里。
# {SHA} = base64(sha1(密码))，nginx auth_basic 支持该 RFC 2307 格式。
# fail-closed：凭据缺失则退出非零，容器启动失败，不退化为无鉴权服务。
set -eu

if [ -z "${MEDICAL_H5_AUTH_PASS:-}" ]; then
  echo "FATAL: MEDICAL_H5_AUTH_PASS 未设置，拒绝启动 H5 预览站点" >&2
  exit 1
fi

user="${MEDICAL_H5_AUTH_USER:-h5}"
hash=$(printf '%s' "$MEDICAL_H5_AUTH_PASS" | sha1sum | cut -d' ' -f1 | xxd -r -p | base64)
printf '%s:{SHA}%s\n' "$user" "$hash" > /etc/nginx/.htpasswd_h5
chmod 644 /etc/nginx/.htpasswd_h5
echo "h5 htpasswd ready (user=$user)"
