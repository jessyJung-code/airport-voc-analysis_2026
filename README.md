# 보안검색 서비스 VOC · 출국장 여객흐름 · 출입국 심사 소요시간 통합 대시보드

Streamlit 기반 3페이지 대시보드
- **VOC 분석**: 보안검색 VOC 접수 데이터 분석 (연도·답변부서 필터)
- **출국장 여객흐름 분석**: Xovis 센서 원본 기반 처리여객/대기시간/대기열 분석 (터미널 필터)
- **출입국 심사 소요시간 모니터링**: 신분확인·보안검색 소요시간 리포트 분석 (보고서 회차·절차구분·터미널·지표 필터)

## 1. 저장소(레포지토리) 구성

배포하려면 아래 파일들을 **모두 같은 저장소**에 올려야 합니다.

```
repo/
├── voc_dashboard_app.py          # 메인 앱 (streamlit run 대상)
├── analyze_voc.py                 # VOC 집계 로직
├── analyze_passenger_flow.py      # 여객흐름 집계 로직
├── analyze_immigration.py         # 출입국 심사 소요시간 집계 로직
├── requirements.txt                # 파이썬 패키지 목록
├── runtime.txt                     # (선택) 파이썬 버전 고정
├── voc_raw.xlsx                    # VOC 원본 데이터 ← 직접 추가 필요
├── xovis_flow.csv                  # 여객흐름 원본 데이터 ← 직접 추가 필요
└── immigration_processing_time.csv # 출입국 심사 소요시간 원본 데이터 ← 직접 추가 필요
```

`voc_dashboard_app.py`, `analyze_voc.py`, `analyze_passenger_flow.py`,
`analyze_immigration.py`, `requirements.txt`, `runtime.txt`는 이 대화에서 만든
파일을 그대로 커밋하면 됩니다.
**`voc_raw.xlsx`, `xovis_flow.csv`, `immigration_processing_time.csv`는 원본
데이터라 별도로 저장소에 추가**해야 합니다.

`immigration_processing_time.csv`는 인천공항 "출입국 소요시간 모니터링 결과
보고서"(1차 `26.2.12~2.15 / 2차 `26.6.20~6.23) 캡처 표를 옮겨 적은 tidy CSV로,
이미 이 대화에서 생성해 함께 제공했다 — 별도 가공 없이 그대로 저장소에
커밋하면 된다.

### 데이터 파일을 저장소에 올리지 않으려면
`voc_dashboard_app.py`는 해당 경로에서 파일을 못 찾으면 자동으로 업로드 위젯을
띄우도록 되어 있습니다. 즉, 데이터 파일 없이 배포해도 앱은 정상 기동하고,
접속한 사람이 화면에서 직접 파일을 업로드해서 쓸 수 있습니다. 다만 접속할
때마다 다시 올려야 하므로, 상시 운영할 대시보드라면 A안(저장소에 커밋)을

권장합니다.

### 파일 크기가 큰 경우 (GitHub 100MB 제한)
`voc_raw.xlsx`나 `xovis_flow.csv`가 100MB를 넘으면 일반 git으로 올릴 수 없습니다.
- **Git LFS** 사용, 또는
- 데이터를 S3/Google Drive 등 외부 스토리지에 두고 `get_raw_df()` /
  `get_flow_raw_df()` 안에서 다운로드하도록 코드를 수정 (필요하면 말씀해 주세요,
  바로 수정해 드립니다)

## 2. Streamlit Community Cloud 배포 절차

1. 위 파일들을 GitHub 저장소(레포)에 push
2. https://share.streamlit.io 접속 → "New app"
3. 저장소/브랜치 선택, **Main file path**에 `voc_dashboard_app.py` 지정
4. Deploy 클릭 — `requirements.txt`를 자동으로 읽어 패키지를 설치합니다
5. 배포 후 데이터 파일을 못 찾는다는 에러가 뜨면, 저장소에 데이터 파일이
   실제로 커밋됐는지, 파일명이 `voc_raw.xlsx` / `xovis_flow.csv` / `immigration_processing_time.csv`와 정확히
   일치하는지 확인하세요 (대소문자 포함)

## 3. 로컬에서 먼저 테스트하기

```bash
pip install -r requirements.txt
streamlit run voc_dashboard_app.py
```

같은 폴더에 `voc_raw.xlsx`, `xovis_flow.csv`, `immigration_processing_time.csv`를 두고 실행하면 됩니다.

## 4. requirements.txt 안내

| 패키지 | 용도 |
|---|---|
| streamlit | 대시보드 프레임워크 |
| pandas | 데이터 처리 |
| openpyxl | VOC 원본(xlsx) 읽기 |
| kiwipiepy | 한국어 형태소 분석 (제목/내용 키워드 추출) |
| scikit-learn | TF-IDF 키워드 분석 |
| plotly | 인터랙티브 차트 |

`kiwipiepy`는 사전 학습된 형태소 분석 모델(`kiwipiepy_model`)을 함께 설치하므로
별도 다운로드나 인터넷 접근이 배포 시점에 필요하지 않습니다.

## 5. 자주 발생하는 배포 이슈

| 증상 | 원인 / 해결 |
|---|---|
| `FileNotFoundError` 또는 업로드 위젯이 뜸 | 데이터 파일이 저장소에 없음 → 1번 참고 |
| 앱이 계속 "Installing dependencies"에 머묾 | `kiwipiepy` 빌드에 시간이 걸릴 수 있음 → 보통 2~3분 내 완료, 그 이상 걸리면 로그 확인 |
| 메모리 초과로 앱이 재시작됨 | Streamlit Community Cloud 무료 플랜은 메모리 제한(1GB)이 있음 → 데이터가 매우 크면 유료 플랜 또는 사전 집계본(JSON) 배포 방식 고려 |
| 캐시가 안 갱신됨(데이터 바꿨는데 그대로) | 앱 메뉴 → "Clear cache" 후 재실행 |
