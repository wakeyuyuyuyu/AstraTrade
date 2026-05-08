from __future__ import annotations

import os
import re
from typing import List, Dict

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


def extract_final_content(content: str) -> str:
    '''删除 <think>...</think> 中的内容'''
    content = re.sub(
        r"<think>.*?</think>",
        "",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()
    return content

def call_llm(messages: List[Dict[str, str]]) -> str:
    api_key = os.getenv("LLM_API_KEY").strip()
    model = os.getenv("LLM_MODEL").strip()
    base_url = os.getenv("LLM_URL").strip()

    if not api_key:
        raise RuntimeError("未设置 LLM_API_KEY")

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        
    )

    content = response.choices[0].message.content
    content = extract_final_content(content)
    if not content:
        raise RuntimeError("模型返回内容为空")
    print(content)
    return content