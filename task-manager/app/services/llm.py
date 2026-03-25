"""SDS OpenAPI LLM integration service."""

import json
import os
from typing import Optional

import httpx

from app.config import LLM_CLIENT_KEY, LLM_ENDPOINT, LLM_MODEL, LLM_MODEL_ID, LLM_PASS_KEY

# FabriX API는 사내 프록시를 거치면 타임아웃 발생 → 프록시 우회
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_k, None)


def _is_ascii(s: str) -> bool:
    try:
        s.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def is_llm_configured() -> bool:
    return bool(
        LLM_ENDPOINT
        and LLM_CLIENT_KEY
        and LLM_PASS_KEY
        and LLM_MODEL_ID
        and _is_ascii(LLM_CLIENT_KEY)
        and _is_ascii(LLM_PASS_KEY)
    )


async def chat_completion(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    """Call the SDS LLM API and return the assistant's response text."""
    if not is_llm_configured():
        raise RuntimeError("LLM API is not configured. Set TASK_LLM_* env vars.")

    headers = {
        "x-fabrix-client": LLM_CLIENT_KEY,
        "x-openapi-token": LLM_PASS_KEY,
        "x-llm-model-id": LLM_MODEL_ID,
        "Content-Type": "application/json",
    }

    payload = {
        "model": "/mnt/models",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{LLM_ENDPOINT}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except UnicodeEncodeError:
        raise RuntimeError("API 키에 유효하지 않은 문자가 포함되어 있습니다. .env 파일에서 실제 API 키(ASCII)를 입력하세요.")
    except httpx.ConnectError:
        raise RuntimeError("LLM API 서버에 연결할 수 없습니다. 엔드포인트를 확인하세요.")
    except httpx.TimeoutException:
        raise RuntimeError("LLM API 요청 시간이 초과되었습니다.")
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"LLM API 오류 (HTTP {e.response.status_code})")

    # OpenAI-compatible response format
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise RuntimeError("LLM API 응답 형식이 올바르지 않습니다.")


async def generate_weekly_report(
    task_changes: list[dict],
    example_report: str,
    period_label: str,
) -> str:
    """Generate a weekly report based on task changes and an example format."""
    changes_text = json.dumps(task_changes, ensure_ascii=False, indent=2)

    messages = [
        {
            "role": "system",
            "content": (
                "당신은 디자인 팀의 주간보고서를 작성하는 어시스턴트입니다. "
                "사용자가 제공한 예시 보고서의 형식, 톤, 구조를 정확히 따라서 "
                "주간 업무 변동사항을 기반으로 주간보고서를 작성해주세요. "
                "예시와 동일한 포맷(제목, 섹션, 글머리 등)을 유지하세요."
            ),
        },
        {
            "role": "user",
            "content": (
                f"## 보고 기간\n{period_label}\n\n"
                f"## 예시 주간보고서 (이 형식을 따라주세요)\n{example_report}\n\n"
                f"## 이번 주 태스크 변동사항\n{changes_text}\n\n"
                "위 변동사항을 바탕으로 예시와 같은 형식의 주간보고서를 작성해주세요."
            ),
        },
    ]

    return await chat_completion(messages)
