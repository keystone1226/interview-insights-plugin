# Samsung SDS Fabrix API 메모

## 핵심 정보

### Endpoint URL 구조
- Open API 신청 시 발급받은 URL 예시: `https://nsds-api.fabrix-s.samsungsds.com/sds/prod/api-llm/openapi/llm`
- **`/openapi/llm`까지 포함된 전체 경로가 ENDPOINT_URL**

### API 엔드포인트
| 용도 | 경로 | 메서드 |
|------|------|--------|
| 모델 목록 조회 | `ENDPOINT_URL/v1/models` | GET |
| 대화형 답변 | `ENDPOINT_URL/chat/completions` | POST |
| 단일 텍스트 답변 | `ENDPOINT_URL/completions` | POST |
| TGI 서빙 | `ENDPOINT_URL/generate` | POST |
| 이미지 생성 | `ENDPOINT_URL/image/generations` | POST |

### 필수 헤더
```python
headers = {
    "x-fabrix-client": YOUR_CLIENT_KEY,   # Open API 신청 시 발급
    "x-openapi-token": YOUR_PASS_KEY,     # Open API 신청 시 발급
    "x-llm-model-id": YOUR_MODEL_ID,      # 모델 목록 API로 조회
    "Content-Type": "application/json",
}
```

### Request Body (chat/completions)
```python
body = {
    "model": "/mnt/models",   # 모델명 (서버에 따라 생략 가능)
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"}
    ],
    # 선택
    "stream": False,
    "temperature": 1.0,
    "top_p": 1.0,
    "max_completion_tokens": 256,
}
```

### api_key
- ChatOpenAI 등 OpenAI 호환 클라이언트 사용 시: `api_key="EMPTY"` (고정값)

---

## Langflow 컴포넌트 사용 시 주의사항

### 프록시 문제 (Windows 사내망 환경)
- Windows 환경에서 `requests`, `httpx` 등 HTTP 라이브러리가 시스템/레지스트리 프록시를 자동으로 사용함
- Fabrix API 서버는 프록시를 통하지 않고 **직접 연결**해야 함
- `urllib.request.ProxyHandler({})` 로 프록시를 완전히 제거한 커스텀 opener를 사용해야 함

```python
import urllib.request

no_proxy_handler = urllib.request.ProxyHandler({})
opener = urllib.request.build_opener(no_proxy_handler, urllib.request.HTTPSHandler())
req = urllib.request.Request(url, data=body, headers=headers, method="POST")
with opener.open(req, timeout=120) as resp:
    data = json.loads(resp.read().decode("utf-8"))
```

### 자주 실수하는 URL 조합 오류
| 잘못된 예 | 올바른 예 |
|-----------|-----------|
| `ENDPOINT_URL/v1/chat/completions` | `ENDPOINT_URL/chat/completions` |
| `BASE_URL/chat/completions` (openapi/llm 미포함) | `BASE_URL/openapi/llm/chat/completions` |

---

## 트러블슈팅 히스토리 요약

1. **최초 404** → ChatOpenAI가 URL에 `/chat/completions` 자동 추가 → 경로 이중화 문제로 오인했으나 실제 원인은 프록시
2. **ProxyError 502** → 시스템 프록시가 Fabrix 서버 연결 차단
3. **requests/httpx trust_env=False 무효** → Windows 레지스트리 프록시는 `trust_env=False`로도 우회 불가
4. **urllib ProxyHandler({}) 성공** → 프록시 완전 제거 후 서버 도달 성공
5. **404 재발** → Endpoint URL에 `/openapi/llm` 경로 누락이 원인 (컴포넌트에 잘못된 URL 입력)
6. **해결** → 올바른 ENDPOINT_URL 입력 (`...openapi/llm`까지 포함)
