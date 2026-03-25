#!/usr/bin/env python3
"""FabriX LLM Serving API 테스트 스크립트.

사용법:
    # 1단계: 모델 목록 조회
    python test_fabrix_api.py models

    # 2단계: 채팅 API 테스트 (non-stream)
    python test_fabrix_api.py chat

    # 3단계: 채팅 API 테스트 (stream)
    python test_fabrix_api.py stream

    # 전체 테스트
    python test_fabrix_api.py all

환경변수 (.env 파일에서 자동 로드):
    TASK_LLM_CLIENT_KEY  - x-fabrix-client 값
    TASK_LLM_PASS_KEY    - x-openapi-token 값 (Bearer 포함)
    TASK_LLM_ENDPOINT    - API 엔드포인트 URL
    TASK_LLM_MODEL_ID    - x-llm-model-id 값 (models API로 조회 가능)
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# .env 로드
load_dotenv(Path(__file__).resolve().parent / ".env")

CLIENT_KEY = os.getenv("TASK_LLM_CLIENT_KEY", "")
PASS_KEY = os.getenv("TASK_LLM_PASS_KEY", "")
ENDPOINT = os.getenv(
    "TASK_LLM_ENDPOINT",
    "https://nsds-api.fabrix-s.samsungsds.com/sds/prod/api-llm/v1",
)
MODEL_ID = os.getenv("TASK_LLM_MODEL_ID", "")


def check_config():
    """환경변수 설정 확인."""
    print("=" * 60)
    print("설정 확인")
    print("=" * 60)
    print(f"  ENDPOINT:   {ENDPOINT}")
    print(f"  CLIENT_KEY: {CLIENT_KEY[:10]}..." if len(CLIENT_KEY) > 10 else f"  CLIENT_KEY: {CLIENT_KEY or '(미설정)'}")
    print(f"  PASS_KEY:   {PASS_KEY[:10]}..." if len(PASS_KEY) > 10 else f"  PASS_KEY:   {PASS_KEY or '(미설정)'}")
    print(f"  MODEL_ID:   {MODEL_ID or '(미설정 - models API로 먼저 조회하세요)'}")
    print()

    if not CLIENT_KEY or not PASS_KEY:
        print("ERROR: TASK_LLM_CLIENT_KEY, TASK_LLM_PASS_KEY를 .env에 설정하세요.")
        return False
    if CLIENT_KEY.startswith("여기에") or PASS_KEY.startswith("여기에"):
        print("ERROR: .env 파일의 플레이스홀더를 실제 API 키로 교체하세요.")
        return False
    return True


def test_models():
    """GET /v1/models - 사용 가능한 모델 목록 조회."""
    print("=" * 60)
    print("TEST: GET /v1/models (모델 목록 조회)")
    print("=" * 60)

    url = f"{ENDPOINT}/models"
    # ENDPOINT가 이미 /v1로 끝나는 경우와 아닌 경우 처리
    if not ENDPOINT.endswith("/v1"):
        url = f"{ENDPOINT}/v1/models"

    headers = {
        "x-fabrix-client": CLIENT_KEY,
        "x-openapi-token": PASS_KEY,
        "Content-Type": "application/json",
    }

    print(f"  URL: GET {url}")
    print()

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        print(f"  Status: {resp.status_code}")
        print(f"  Response:")
        try:
            data = resp.json()
            print(json.dumps(data, indent=2, ensure_ascii=False))

            # 모델 ID 추출 도움
            if isinstance(data, list) and len(data) > 0:
                print()
                print("  *** 사용 가능한 모델 ID 목록 ***")
                for m in data:
                    mid = m.get("modelId", "?")
                    name = m.get("modelName", "")
                    names = m.get("name", [])
                    label = ""
                    if names:
                        label = names[0].get("content", "") if isinstance(names, list) else str(names)
                    print(f"    - modelId: {mid}  ({name or label})")
                print()
                print("  .env에 TASK_LLM_MODEL_ID=<위 modelId 중 하나> 를 설정하세요.")
            elif isinstance(data, dict) and "data" in data:
                # OpenAI 호환 형식인 경우
                for m in data["data"]:
                    print(f"    - id: {m.get('id', '?')}")
        except Exception:
            print(resp.text[:2000])
    except requests.RequestException as e:
        print(f"  ERROR: {e}")

    print()


def test_chat(stream: bool = False):
    """POST /chat/completions - 채팅 API 테스트."""
    mode = "stream" if stream else "non-stream"
    print("=" * 60)
    print(f"TEST: POST /chat/completions ({mode})")
    print("=" * 60)

    if not MODEL_ID:
        print("  WARNING: TASK_LLM_MODEL_ID가 미설정입니다.")
        print("  먼저 'python test_fabrix_api.py models'로 모델 ID를 확인하세요.")
        print()

    url = f"{ENDPOINT}/chat/completions"
    if not ENDPOINT.rstrip("/").endswith("/v1") and "/v1/" not in ENDPOINT:
        url = f"{ENDPOINT}/v1/chat/completions"

    headers = {
        "x-fabrix-client": CLIENT_KEY,
        "x-openapi-token": PASS_KEY,
        "Content-Type": "application/json",
    }
    if MODEL_ID:
        headers["x-llm-model-id"] = MODEL_ID

    body = {
        "model": "/mnt/models",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "안녕하세요. 간단히 자기소개 해주세요."},
        ],
        "temperature": 0.7,
        "max_completion_tokens": 256,
    }

    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}

    print(f"  URL: POST {url}")
    print(f"  Headers: {json.dumps({k: v[:20] + '...' if len(str(v)) > 20 else v for k, v in headers.items()}, indent=4, ensure_ascii=False)}")
    print(f"  Body: {json.dumps(body, indent=4, ensure_ascii=False)}")
    print()

    try:
        if stream:
            resp = requests.post(url, headers=headers, json=body, timeout=120, stream=True)
            print(f"  Status: {resp.status_code}")
            print()
            if resp.status_code == 200:
                print("  --- Streaming Response ---")
                full_content = ""
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            print("\n  [DONE]")
                            break
                        try:
                            chunk = json.loads(data_str)
                            choices = chunk.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    print(content, end="", flush=True)
                                    full_content += content
                            # usage 정보
                            usage = chunk.get("usage")
                            if usage:
                                print(f"\n\n  Usage: {json.dumps(usage)}")
                        except json.JSONDecodeError:
                            print(f"  [parse error] {data_str[:200]}")
                print()
            else:
                print(f"  Error Response:")
                print(f"  {resp.text[:2000]}")
        else:
            resp = requests.post(url, headers=headers, json=body, timeout=120)
            print(f"  Status: {resp.status_code}")
            print()
            try:
                data = resp.json()
                print(f"  Response:")
                print(json.dumps(data, indent=2, ensure_ascii=False))

                if resp.status_code == 200:
                    choices = data.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "")
                        print(f"\n  --- Assistant 응답 ---")
                        print(f"  {content}")
                    usage = data.get("usage", {})
                    if usage:
                        print(f"\n  Tokens: prompt={usage.get('prompt_tokens')}, "
                              f"completion={usage.get('completion_tokens')}, "
                              f"total={usage.get('total_tokens')}")
            except Exception:
                print(f"  {resp.text[:2000]}")
    except requests.RequestException as e:
        print(f"  ERROR: {e}")

    print()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if not check_config():
        sys.exit(1)

    if cmd == "models":
        test_models()
    elif cmd == "chat":
        test_chat(stream=False)
    elif cmd == "stream":
        test_chat(stream=True)
    elif cmd == "all":
        test_models()
        test_chat(stream=False)
        test_chat(stream=True)
    else:
        print(f"Unknown command: {cmd}")
        print("사용법: python test_fabrix_api.py [models|chat|stream|all]")
        sys.exit(1)


if __name__ == "__main__":
    main()
