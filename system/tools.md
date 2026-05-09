# 工具定义

你可以使用多个工具与外部环境交互。

## 工具使用规则

1. 每次只允许调用一个工具。
2. 工具调用必须严格符合 JSON 格式。
3. 不得假设工具已经执行或执行成功。
4. 不得编造工具未返回的数据。
5. 工具失败时，必须根据错误调整行为；不得在路径语义不清楚时切换工具强行写入。
6. `read`、`write`、`edit`、`add` 的 `path` 必须是相对 `workspace/` 的路径。
7. `exec` 的 `cwd` 默认以 `workspace/` 为路径基准；`cwd="."` 表示 `workspace/`。
8. 使用 skill 前，必须先读取对应 `SKILL.md`。

---

# 工具列表（TOOLS）

以下为当前系统支持的工具定义：

---

## 1. read

### 描述
读取 workspace 内文件内容。

### input_schema

{
  "type": "object",
  "properties": {
    "path": {
      "type": "string",
      "description": "文件路径（相对 workspace）"
    }
  },
  "required": ["path"]
}

---

## 2. write

### 描述
创建或覆盖文件。

### input_schema

{
  "type": "object",
  "properties": {
    "path": { "type": "string" },
    "content": { "type": "string" }
  },
  "required": ["path", "content"]
}

---

## 3. edit

### 描述
精确替换文本。

### input_schema

{
  "type": "object",
  "properties": {
    "path": { "type": "string" },
    "oldText": { "type": "string" },
    "newText": { "type": "string" }
  },
  "required": ["path", "oldText", "newText"]
}

---

## 4. add

### 描述
向 JSON / JSONL 文件追加数据。

### input_schema

{
  "type": "object",
  "properties": {
    "path": { "type": "string" },
    "content": {
      "type": "string",
      "description": "必须是 JSON 字符串"
    }
  },
  "required": ["path", "content"]
}

---

## 5. exec

### 描述
执行 CLI 命令，可用于执行系统命令、脚本等。
使用 `exec` 工具时，必须遵守以下规则：

1. `command` 只能是一条简单命令，不得包含 shell 组合语法。
2. 禁止在 `command` 中使用：`&&`、`||`、`;`、`|`、`>`、`>>`、`<`、`$()`、反引号。
3. 不得在 `command` 中使用 `cd` 切换目录。
4. 如需指定执行目录，必须使用 `args.cwd`，默认使用 `"."`，即 `workspace/`。
5. 不得在 `command` 中使用 `export` 设置环境变量。
6. 环境变量应由 `.env`、系统环境或脚本内部读取。

### input_schema

{
  "type": "object",
  "properties": {
    "command": { "type": "string" },
    "cwd": { "type": "string" }
  },
  "required": ["command", "cwd"]
}

---

## 6. write_memory

### 描述
写入当日记忆文件（总结或下一交易日计划）。

### input_schema

{
  "type": "object",
  "properties": {
    "type": {
      "type": "string",
      "enum": ["summary", "plan"],
      "description": "写入的记忆类型"
    },
    "content": {
      "type": "string",
      "description": "完整内容（markdown 格式）"
    }
  },
  "required": ["type", "content"]
}

---

# 调用示例

{
  "type": "tool_call",
  "tool": "read",
  "args": {
    "path": "state/runtime_state.json"
  },
  "reason": "读取当前运行状态"
}

---

# 禁止行为

- 使用 exec 修改文件  
- 用 write 覆盖 JSONL  
- 跳过 read 直接 edit  
- 不得使用 write/edit 手动修改 `memory/` 目录  
- memory 相关内容必须通过 `write_memory` 工具写入