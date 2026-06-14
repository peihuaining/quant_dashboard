#!/bin/bash
# Quant Dashboard — 启动脚本
# 访问: http://127.0.0.1:9001

PORT=9001
BACKEND="$(dirname "$0")/backend"

if ss -tlnp | grep -q ":${PORT}"; then
  echo "端口 ${PORT} 已被占用，请先关闭已有进程"
  ss -tlnp | grep ":${PORT}"
  exit 1
fi

echo "启动 Quant Dashboard"
echo "  本机:   http://127.0.0.1:${PORT}"
echo "  局域网: http://192.168.100.168:${PORT}  (仅允许 192.168.100.0/24)"
cd "$BACKEND" && python3 -m uvicorn app:app --host 0.0.0.0 --port "$PORT" --log-level warning
