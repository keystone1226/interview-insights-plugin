# 스터디 참여 가이드

## 환경 세팅

### 1. 레포 클론

```bash
git clone https://github.com/keystone1226/interview-insights-plugin.git
cd interview-insights-plugin
```

### 2. Claude Code (오픈클로) 사용

이 레포는 Claude Code 환경에서 사용할 수 있도록 세팅되어 있습니다.
- `CLAUDE.md` 파일이 프로젝트 컨텍스트를 제공합니다.
- Claude Code에서 레포를 열면 자동으로 프로젝트 맥락을 파악합니다.

## 과제 제출 프로세스

### 1. 브랜치 생성

```bash
git checkout -b study/<your-username>/week<N>
```

### 2. 과제 작성

```bash
# 주차별 폴더에 본인 폴더 생성
mkdir -p study/weekNN/<your-username>

# 템플릿 복사
cp study/TEMPLATE_notes.md study/weekNN/<your-username>/notes.md

# notes.md 편집
```

### 3. PR 생성

```bash
git add .
git commit -m "study(weekNN): <username> - <주제 요약>"
git push -u origin study/<your-username>/week<N>
```

GitHub에서 PR을 생성하고 리뷰를 요청합니다.

## 커밋 메시지 규칙

```
study(weekNN): <username> - <간단한 설명>
```

예시:
```
study(week01): johndoe - AI Agent 개요 정리
study(week03): janedoe - LangGraph 실습 코드 추가
```

## 코드 리뷰

- 모든 과제는 PR을 통해 제출합니다.
- 최소 1명 이상의 리뷰를 받은 후 머지합니다.
- 리뷰는 건설적인 피드백 중심으로 작성합니다.
