#!/usr/bin/env bash
set -euo pipefail

# ===== 路径定义 =====
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE:-$ROOT/workspace}"
CONFIG_DIR="$ROOT/config"
DASHBOARD_RUNTIME_DIR="$ROOT/dashboard/runtime"
STATE_DIR="$WORKSPACE/state"
POOLS_DIR="$WORKSPACE/pools"
LOGS_DIR="$WORKSPACE/logs"
MEMORY_DIR="$WORKSPACE/memory"

AGENT_RUNS_DIR="$LOGS_DIR/agent_runs"
SCHEDULER_DIR="$LOGS_DIR/scheduler"
MX_DATA_OUTPUT_DIR="$LOGS_DIR/mx_data/output"
REPORTS_DIR="$WORKSPACE/reports"
ALARM_CONFIG_PATH="$CONFIG_DIR/alarm.json"
DASHBOARD_MANUAL_RUNS_PATH="$DASHBOARD_RUNTIME_DIR/manual_runs.jsonl"
DASHBOARD_INITIALIZATION_RUNS_PATH="$DASHBOARD_RUNTIME_DIR/initialization_runs.jsonl"
DASHBOARD_SCHEDULER_LOG_PATH="$DASHBOARD_RUNTIME_DIR/scheduler.log"

# ===== 获取时间 =====
TODAY=$(date +"%Y-%m-%d")
NOW=$(date +"%Y-%m-%d %H:%M:%S")

# ===== 准备目录 =====
mkdir -p \
  "$CONFIG_DIR" \
  "$DASHBOARD_RUNTIME_DIR" \
  "$STATE_DIR" \
  "$POOLS_DIR" \
  "$LOGS_DIR" \
  "$MEMORY_DIR" \
  "$AGENT_RUNS_DIR" \
  "$SCHEDULER_DIR" \
  "$MX_DATA_OUTPUT_DIR" \
  "$REPORTS_DIR"

# ===== 清空 pools / logs =====
echo "Clearing contents of pools..."
find "$POOLS_DIR" -type f -exec truncate -s 0 {} +

echo "Clearing contents of logs..."
find "$LOGS_DIR" -type f -exec truncate -s 0 {} +

echo "Clearing contents of memory..."
rm -rf "$MEMORY_DIR"/*

echo "Clearing contents of agent_runs..."
rm -rf "$AGENT_RUNS_DIR"/*

echo "Clearing contents of scheduler..."
rm -rf "$SCHEDULER_DIR"/*

echo "Clearing contents of mx_data/output..."
rm -rf "$MX_DATA_OUTPUT_DIR"/*

echo "Clearing contents of reports..."
rm -rf "$REPORTS_DIR"/*

echo "Clearing dashboard history..."
: > "$DASHBOARD_MANUAL_RUNS_PATH"
: > "$DASHBOARD_INITIALIZATION_RUNS_PATH"
: > "$DASHBOARD_SCHEDULER_LOG_PATH"

touch \
  "$POOLS_DIR/holdings.jsonl" \
  "$POOLS_DIR/strategies.jsonl" \
  "$POOLS_DIR/candidates.jsonl" \
  "$LOGS_DIR/trades.jsonl" \
  "$LOGS_DIR/events.jsonl" \
  "$LOGS_DIR/agent_runs.jsonl"


# ===== 初始化 account_state.json =====
echo "Initializing account_state.json..."
cat > "$STATE_DIR/account_state.json" <<EOF
{
  "mode": "initialization",
  "cash": 1000000,
  "total_asset": 1000000,
  "market_value": 0,
  "available_cash": 1000000,
  "position_count": 0,
  "risk": {
    "max_position_ratio": 1,
    "max_single_stock_ratio": 0.5,
    "max_daily_trades": 5,
    "stop_trading": false
  },
  "updated_at": "$NOW"
}
EOF

# ===== 初始化 market_state.json =====
echo "Initializing market_state.json..."
cat > "$STATE_DIR/market_state.json" <<EOF
{
  "date": "$TODAY",
  "market_view": "unknown",
  "risk_level": "unknown",
  "summary": "系统初始化，市场状态待更新。",
  "hot_topics": [],
  "watch_sectors": [],
  "avoid_sectors": [],
  "key_events": [],
  "updated_at": "$NOW",
  "evidence": []
}
EOF

# ===== 初始化 alarm.json =====
echo "Initializing alarm.json..."
cat > "$ALARM_CONFIG_PATH" <<EOF
{
  "enabled": true,
  "alarms": []
}
EOF

echo "Workspace initialized successfully."
