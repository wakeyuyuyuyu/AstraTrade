from __future__ import annotations

import os
import re
from typing import List, Dict, Optional

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
) -> str:
    """
    调用 LLM。

    Args:
        messages: OpenAI Chat Completions 格式消息
        model_profile: 模型配置角色，默认 main
        temperature: 温度参数，默认 0.2

    Returns:
        模型去除 <think>...</think> 后的最终输出
    """

    config = _resolve_llm_config(model_profile)

    client = OpenAI(
        api_key=config["api_key"],
        base_url=config["base_url"],
    )

    response = client.chat.completions.create(
        model=config["model"],
        messages=messages,
        temperature=temperature,
    )

    content = response.choices[0].message.content or ""

    think_content = extract_think_content(content)
    # 如果以后想保存 think，可以在这里返回或记录到日志
    # if think_content:
    #     print("\n========== MODEL THINK ==========")
    #     print(think_content)
    #     print("========== END THINK ==========\n")

    content = extract_final_content(content)

    if not content:
        raise RuntimeError("模型返回内容为空")

    return content

if __name__ == "__main__":
    test_messages = [
        {"role": "user", "content": "你好"}
    ]
    result = call_llm(test_messages)
    print(result)