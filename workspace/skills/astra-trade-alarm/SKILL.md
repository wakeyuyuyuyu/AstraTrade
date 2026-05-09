---
name: astra-trade-alarm
description: AstraTrade alarm 任务管理 skill。用于让 Agent 自主创建、更新、启用、禁用或删除 config/alarm.json 中的 alarm 定时任务，并通过 alarm 在指定时间以 manual 形式唤醒主 Agent。适用于用户要求“提醒我之后检查某股票”“明天盘前分析候选池”“收盘后复盘”“定时让 Agent 执行某个自然语言任务”等场景。
---

# AstraTrade Alarm

## 功能定位

使用本 skill 管理 AstraTrade 项目中的 `config/alarm.json`。

alarm 用于保存用户或 Agent 生成的定时任务。到达触发时间后，外部 scheduler/alarm runner 应读取 `config/alarm.json`，并将对应 `task` 以 `manual` 调用方式唤醒主 Agent。

本 skill 只负责生成和维护 alarm 配置，不负责真正运行常驻调度器。

## 文件结构

本 skill 包含：

```text
astra-trade-alarm/
├── SKILL.md
└── scripts/
    └── alarm_manager.py
```

## 使用原则

1. 当需要新增、更新、启用、禁用、删除 alarm 时，调用 `scripts/alarm_manager.py`。
2. 不要手动编辑 `config/alarm.json`，除非脚本不可用。
3. alarm 任务的 `task` 必须是可直接传给主 Agent 的自然语言任务。
4. alarm 到点后默认以 `manual` 模式唤醒主 Agent，不需要在 alarm 配置里保存 `mode` 字段。
5. 时间使用项目运行环境的本地时间，不在 `alarm.json` 中保存 timezone。

## alarm.json 结构

目标文件路径：

```text
config/alarm.json
```

基础结构：

```json
{
  "enabled": true,
  "alarms": []
}
```

周期型 alarm 示例：

```json
{
  "alarm_id": "alarm_0910",
  "name": "盘前重点候选检查",
  "enabled": true,
  "trigger_time": "09:10",
  "weekdays": [1, 2, 3, 4, 5],
  "task": "检查当前候选池和市场状态，筛选今日盘前最值得关注的候选股票，并给出观察重点。",
  "run_once": false
}
```

一次性 alarm 示例：

```json
{
  "alarm_id": "alarm_20260512092000",
  "name": "一次性人工任务",
  "enabled": true,
  "trigger_datetime": "2026-05-12 09:20:00",
  "task": "分析 300059 是否值得加入候选池。",
  "run_once": true
}
```

## alarm_id 规则

由脚本自动生成，不要手动传入。

周期型：

```text
alarm_HHMM
```

例如：`09:10` → `alarm_0910`

一次性：

```text
alarm_YYYYMMDDHHMMSS
```

例如：`2026-05-12 09:20:00` → `alarm_20260512092000`

如果同一时间已存在 alarm，脚本会自动追加序号：

```text
alarm_0910_02
alarm_20260512092000_02
```

## 创建周期型 alarm

使用 `add-recurring`：

```bash
python skills/astra-trade-alarm/scripts/alarm_manager.py add-recurring \
  --project-root . \
  --time 09:10 \
  --weekdays 1,2,3,4,5 \
  --name "盘前重点候选检查" \
  --task "检查当前候选池和市场状态，筛选今日盘前最值得关注的候选股票，并给出观察重点。"
```

参数说明：

- `--project-root`：AstraTrade 项目根目录，默认 `.`。
- `--time`：触发时间，格式 `HH:MM`。
- `--weekdays`：生效星期，使用 `1,2,3,4,5` 表示周一至周五。
- `--name`：alarm 展示名称。
- `--task`：到点后传给主 Agent 的自然语言任务。
- `--disabled`：可选，创建后默认关闭。

## 创建一次性 alarm

使用 `add-once`：

```bash
python skills/astra-trade-alarm/scripts/alarm_manager.py add-once \
  --project-root . \
  --datetime "2026-05-12 09:20:00" \
  --name "检查 300059" \
  --task "分析 300059 是否值得加入候选池。"
```

参数说明：

- `--datetime`：触发时间，格式 `YYYY-MM-DD HH:MM:SS`。
- `--name`：alarm 展示名称。
- `--task`：到点后传给主 Agent 的自然语言任务。
- `--disabled`：可选，创建后默认关闭。

## 更新 alarm

使用 `update`，通过 `alarm_id` 指定目标：

```bash
python skills/astra-trade-alarm/scripts/alarm_manager.py update \
  --project-root . \
  --alarm-id alarm_0910 \
  --name "盘前候选池检查" \
  --task "检查候选池，删除不适合继续观察的股票，并保留最值得跟踪的标的。"
```

可更新字段：

- `--name`
- `--task`
- `--enabled true|false`
- `--time HH:MM`
- `--datetime "YYYY-MM-DD HH:MM:SS"`
- `--weekdays 1,2,3,4,5`

注意：

- 使用 `--time` 会把目标改为周期型 alarm，并设置 `run_once=false`。
- 使用 `--datetime` 会把目标改为一次性 alarm，并设置 `run_once=true`。
- 更新时间后，脚本会根据新时间重新生成 `alarm_id`。

## 删除 alarm

```bash
python skills/astra-trade-alarm/scripts/alarm_manager.py delete \
  --project-root . \
  --alarm-id alarm_0910
```

## 启用或关闭整个 alarm 系统

```bash
python skills/astra-trade-alarm/scripts/alarm_manager.py set-global \
  --project-root . \
  --enabled true
```

## 查看当前 alarm 配置

```bash
python skills/astra-trade-alarm/scripts/alarm_manager.py list \
  --project-root .
```

## 执行建议

当用户提出模糊需求时，先自行转化为明确的 alarm 参数，不要过度追问。

示例：

用户说：

```text
明天开盘前提醒我分析一下机器人板块
```

可转化为：

- 类型：一次性 alarm
- 时间：下一个交易日 09:10:00
- name：机器人板块盘前分析
- task：分析机器人板块最新行情、热点持续性和候选股票机会，给出是否需要加入候选池的建议。

用户说：

```text
每天收盘后让 Agent 复盘一下
```

可转化为：

- 类型：周期型 alarm
- 时间：15:30
- weekdays：1,2,3,4,5
- name：盘后复盘
- task：复盘今日持仓、候选池、交易记录和市场状态，总结今日决策表现，并生成下一交易日观察计划。
