from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


def extract_final_content(content: str) -> str:
    """删除 <think>...</think> 中的内容"""
    content = re.sub(
        r"<think>.*?</think>",
        "",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()
    return content


def extract_think_content(content: str) -> str:
    """提取 <think>...</think> 中的内容"""
    think_parts = re.findall(
        r"<think>(.*?)</think>",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return "\n\n".join(part.strip() for part in think_parts if part.strip())


def _get_env(name: str, required: bool = True) -> str:
    value = os.getenv(name, "").strip()
    if required and not value:
        raise RuntimeError(f"未设置 {name}")
    return value


def _resolve_llm_config(model_profile: str = "main") -> Dict[str, str]:
    """
    根据模型角色读取 LLM 配置。

    model_profile:
    - "main": 主 Agent，读取 LLM_API_KEY / LLM_URL / LLM_MODEL
    - "sub": 子 Agent，优先读取 SUB_LLM_API_KEY / SUB_LLM_URL / SUB_LLM_MODEL
             未配置时逐项回退到主 Agent 配置
    """

    profile = model_profile.lower().strip()

    main_config = {
        "api_key": _get_env("LLM_API_KEY"),
        "base_url": _get_env("LLM_URL"),
        "model": _get_env("LLM_MODEL"),
    }

    if profile == "main":
        return main_config

    if profile == "sub":
        return {
            "api_key": os.getenv("SUB_LLM_API_KEY", "").strip() or main_config["api_key"],
            "base_url": os.getenv("SUB_LLM_URL", "").strip() or main_config["base_url"],
            "model": os.getenv("SUB_LLM_MODEL", "").strip() or main_config["model"],
        }

    raise ValueError(f"未知模型配置: {model_profile}，可选值: main / sub")


def call_llm(
    messages: List[Dict[str, str]],
    model_profile: str = "main",
    temperature: float = 0.2,
    tools: Optional[List[Dict[str, Any]]] = None,
    max_tokens: int = 4096,
) -> str:
    """
    调用 LLM。

    支持 OpenAI 原生 tool_calling（修复 DeepSeek 多轮对话空返回问题）：
    如果传入 tools 参数，则通过 API 级别的 tools 定义让模型输出
    结构化的 tool_calls，避免模型自己拼接 JSON 出错或返回空内容。

    设计思路：
    - 传入 tools 后，API 可能返回原生 tool_calls（结构化数据）
    - 本函数将原生 tool_calls 转成文本 JSON，格式与模型自行输出 JSON 完全一致
    - 这样 agent_loop 侧不需要改任何消息格式逻辑
    - 如果 API 没返回 tool_calls（回退路径），则回到原有文本解析流程
    - 保留 JSON 文本 fallback，改动前后行为完全兼容

    Args:
        messages: OpenAI Chat Completions 格式消息
        model_profile: 模型配置角色，默认 main
        temperature: 温度参数，默认 0.2
        tools: OpenAI function calling 工具列表（可选）
        max_tokens: 单次响应的最大 token 数，默认 4096；设为 0 则不由客户端限制

    Returns:
        模型去除 <think>...</think> 后的最终输出（或原生 tool_call 转文本 JSON）
    """

    config = _resolve_llm_config(model_profile)

    client = OpenAI(
        api_key=config["api_key"],
        base_url=config["base_url"],
    )

    def _build_kwargs() -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": config["model"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
        return kwargs

    def _do_call() -> Any:
        return client.chat.completions.create(**_build_kwargs())

    response = _do_call()

    max_retries = 3
    for attempt in range(max_retries):
        choice = response.choices[0]
        msg = choice.message

        # 优先处理原生 tool_calls：API 通过 tools 参数返回结构化函数调用
        # 绕过 JSON 文本解析，直接从 response 提取 tool name + arguments
        # 格式化为文本 JSON 以兼容 agent_loop 现有消息格式
        if msg.tool_calls:
            tc = msg.tool_calls[0]
            try:
                parsed_args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                parsed_args = {}
            return json.dumps({
                "type": "tool_call",
                "tool": tc.function.name,
                "args": parsed_args,
                "reason": "",
            }, ensure_ascii=False)

        raw_content = msg.content or ""

        think_content = extract_think_content(raw_content)
        content = extract_final_content(raw_content)

        if content or think_content:
            break

        if attempt < max_retries - 1:
            import time
            time.sleep(2)
            response = _do_call()
        else:
            debug_path = Path(__file__).resolve().parents[1] / "debug_llm.log"
            with open(debug_path, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] finish_reason={choice.finish_reason}\n")
                f.write(f"Raw content: {raw_content!r}\n")
                f.write(f"---\n")
            raise RuntimeError("模型返回内容为空")

    if not content and think_content:
        content = think_content

    return content

if __name__ == "__main__":
    test_messages = [
        {"role": "user", "content": "你好"}
    ]
    result = call_llm(test_messages)
    print(result)