# -*- coding: utf-8 -*-
"""
보안검색 서비스 VOC 종합 인터랙티브 대시보드 (Streamlit)
=========================================================
실행 방법 (로컬)
  1) pip install streamlit plotly pandas openpyxl kiwipiepy scikit-learn
  2) 이 파일과 같은 폴더에 analyze_voc.py 와 원본 데이터 "voc_raw.xlsx" 를 둔다.
  3) streamlit run voc_dashboard_app.py

배포 방법 (Streamlit Community Cloud)
  cwd(작업 디렉터리)가 로컬과 다르기 때문에 파일을 스크립트와 "같은 폴더"에
  두는 것만으로는 부족할 수 있다. 아래 중 하나로 해결한다.
  A) 저장소 루트에 원본 xlsx를 커밋 (예: repo/voc_raw.xlsx)
     또는 repo/data/voc_raw.xlsx 에 커밋
     → 이 스크립트는 두 위치를 자동으로 찾는다 (CANDIDATE_PATHS 참고).
     ⚠ GitHub 파일 크기 제한(100MB)에 걸리면 Git LFS를 사용하거나
       데이터를 별도 스토리지(S3, Google Drive 등)에서 내려받도록
       get_raw_df()를 수정해야 한다.
  B) 저장소에 데이터를 올리지 않으려면 아무 것도 안 해도 된다 — 파일을
     못 찾으면 화면에 업로드 버튼이 자동으로 뜬다.

analyze_voc.py 의 load_and_prepare() / build_aggregates() 를 그대로 재사용해서
집계 로직을 이중으로 관리하지 않는다.

레이아웃 (채팅에서 보여드린 연도별 종합 대시보드와 동일한 구성)
  - 사이드바 연도 다중 선택 (선택 연도별로 전체 화면이 재계산됨)
  - 연도별 접수 현황 (선택 연도 강조)
  - KPI 카드 4개
  - 01 채널 & 유형   : 등록채널 / 요구유형 / 고객유형 / 시간대
  - 02 서비스유형 & 이용편명 : 서비스유형 TOP / 터미널 / 항공사
  - 03 답변부서 & 발생원인
  - 04 추이·교차분석 & 빈도 키워드 : 월별추이 / 요구유형x발생원인 / 제목·내용 키워드(빈도)
  - 05 TF-IDF 키워드 분석 : 제목/내용 TF-IDF TOP15 + 요구유형별 대표 키워드 비교
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from pathlib import Path

from analyze_voc import load_and_prepare, build_aggregates, INPUT_PATH

# ---------------------------------------------------------------------------
# 색상 팔레트 (categorical, 고정 순서로 사용 — 값의 순위에 따라 색을 바꾸지 않음)
# ---------------------------------------------------------------------------
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
YELLOW = "#eda100"
MAGENTA = "#e87ba4"
VIOLET = "#4a3aa7"
RED = "#e34948"
GRAY = "#898781"
GRID = "#e1e0d9"
TEXT_SECONDARY = "#52514e"
YEAR_HIGHLIGHT = BLUE
YEAR_DIM = "#c3c2b7"
CROSS_COLORS = [RED, GRAY, YELLOW, VIOLET, MAGENTA, BLUE, AQUA]

CHART_FONT = dict(family="Pretendard, Noto Sans KR, sans-serif", size=12, color=TEXT_SECONDARY)


# ---------------------------------------------------------------------------
# 데이터 소스 찾기
#   로컬 실행과 Streamlit Community Cloud 배포 양쪽에서 동작하도록,
#   실행 위치(cwd)가 아니라 이 스크립트 파일 기준 상대경로로 후보들을 찾는다.
#   그래도 못 찾으면(=깃 저장소에 데이터 파일을 올리지 않은 경우) 화면에
#   업로드 버튼을 띄워 그 자리에서 파일을 받는다 — 클라우드에 원본 VOC
#   데이터를 커밋하고 싶지 않을 때 특히 유용하다.
# ---------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent

CANDIDATE_PATHS = [
    APP_DIR / INPUT_PATH,               # 앱과 같은 폴더
    APP_DIR / "data" / INPUT_PATH,      # data/ 하위 폴더에 커밋한 경우
    Path(INPUT_PATH),                   # 현재 작업 디렉터리 (로컬 실행 시)
]


def _find_data_file():
    for p in CANDIDATE_PATHS:
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# 데이터 로드 (streamlit 캐시로 반복 재계산 방지)
# ---------------------------------------------------------------------------
@st.cache_data
def _load_and_tag(source):
    """load_and_prepare 는 파일 경로/파일객체 어느 쪽이든 그대로 받는다
    (내부에서 pandas.read_excel 을 쓰기 때문)."""
    df = load_and_prepare(source)
    df["연도"] = df["등록일시_dt"].dt.year
    return df


def get_raw_df():
    """원본 데이터를 로드한다. 저장소에 파일이 없으면 업로드 위젯으로 대체한다."""
    found = _find_data_file()
    if found is not None:
        return _load_and_tag(str(found))

    st.warning(
        f"원본 데이터 파일을 찾지 못했습니다. 다음 경로들을 확인했습니다:\n\n"
        + "\n".join(f"- `{p}`" for p in CANDIDATE_PATHS)
        + "\n\n저장소에 데이터 파일을 커밋했다면 경로/파일명을 확인해 주세요. "
        "지금 바로 확인하려면 아래에 파일을 업로드하세요."
    )
    uploaded = st.file_uploader(f"'{INPUT_PATH}' 파일 업로드", type=["xlsx"])
    if uploaded is None:
        st.stop()  # 파일이 없으면 이후 코드를 실행하지 않고 대기
    return _load_and_tag(uploaded)


@st.cache_data
def get_aggregates(years_tuple, _df):
    """선택된 연도(들)로 필터링한 뒤 12개 축 집계를 다시 계산한다.
    years_tuple 이 비어있으면(=전체 연도 선택) 필터링하지 않는다.
    _df 를 인자로 받아 캐시 키에 원본 데이터 변경(파일 재업로드 등)도 반영한다."""
    df = _df
    if years_tuple:
        df = df[df["연도"].isin(years_tuple)]
    return build_aggregates(df)




def base_layout(height, showlegend=False, barmode=None):
    layout = dict(
        height=height,
        margin=dict(l=8, r=8, t=8, b=8),
        font=CHART_FONT,
        showlegend=showlegend,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor=GRID, zeroline=False),
        yaxis=dict(gridcolor=GRID, zeroline=False),
    )
    if barmode:
        layout["barmode"] = barmode
    return layout


def hbar(items, color, height, top=None, ascending=True):
    """가로 막대 차트 (값이 큰 항목이 위로 오도록 정렬)"""
    d = items[:top] if top else items
    d = sorted(d, key=lambda x: x["value"], reverse=not ascending)
    fig = go.Figure(go.Bar(
        x=[x["value"] for x in d], y=[x["name"] for x in d],
        orientation="h", marker_color=color, marker=dict(cornerradius=4),
    ))
    fig.update_layout(**base_layout(height))
    return fig


def vbar(items, color, height, top=None):
    d = items[:top] if top else items
    fig = go.Figure(go.Bar(
        x=[x["name"] for x in d], y=[x["value"] for x in d],
        marker_color=color, marker=dict(cornerradius=4),
    ))
    fig.update_layout(**base_layout(height))
    return fig


# ---------------------------------------------------------------------------
# 페이지 설정
# ---------------------------------------------------------------------------
st.set_page_config(page_title="보안검색 서비스 VOC 대시보드", page_icon="🛫", layout="wide")

st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem; padding-bottom: 2rem;}
    div[data-testid="stMetric"] {background: #f7f7f5; border-radius: 10px; padding: 14px 16px;}
    .section-label {font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase;
        color: #898781; margin: 1.5rem 0 0.5rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

raw_df = get_raw_df()
agg = get_aggregates(tuple(), raw_df)  # 초기 타이틀 표시용 (전체 기간 기준)
st.title("보안검색 서비스 VOC 분석 대시보드")
st.caption(f"분석기간 {agg['meta']['date_min']} ~ {agg['meta']['date_max']}  ·  전체 접수 {agg['meta']['total']:,}건")

# ---------------------------------------------------------------------------
# 사이드바: 연도 선택
# ---------------------------------------------------------------------------
years_available = sorted(int(y) for y in raw_df["연도"].dropna().unique())

st.sidebar.header("연도 선택")
selected_years = st.sidebar.multiselect(
    "분석할 연도를 선택하세요 (미선택 시 전체 기간)",
    options=years_available,
    default=years_available,
)
if not selected_years:
    selected_years = years_available
    st.sidebar.caption("연도를 선택하지 않아 전체 기간을 표시합니다.")

is_full_range = set(selected_years) == set(years_available)
years_key = tuple() if is_full_range else tuple(sorted(selected_years))
agg = get_aggregates(years_key, raw_df)

if is_full_range:
    st.caption(f"현재 보기: 전체 기간 ({agg['meta']['date_min']} ~ {agg['meta']['date_max']})")
else:
    label = ", ".join(f"{y}년" for y in sorted(selected_years))
    st.caption(f"현재 보기: {label}  ·  선택 기간 접수 {agg['meta']['total']:,}건")

# ---------------------------------------------------------------------------
# 연도별 접수 현황 (필터와 무관하게 항상 전체 연도를 보여주고, 선택 연도를 강조)
# ---------------------------------------------------------------------------
st.subheader("연도별 접수 현황")
yearly_counts = raw_df.groupby("연도").size().reindex(years_available, fill_value=0)
bar_colors = [YEAR_HIGHLIGHT if y in selected_years else YEAR_DIM for y in years_available]
fig = go.Figure(go.Bar(
    x=[str(y) for y in years_available], y=yearly_counts.values,
    marker_color=bar_colors, marker=dict(cornerradius=4),
    text=yearly_counts.values, textposition="outside",
))
fig.update_layout(**base_layout(200))
st.plotly_chart(fig, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# KPI 카드
# ---------------------------------------------------------------------------
k1, k2, k3, k4 = st.columns(4)
k1.metric("전체 접수", f"{agg['meta']['total']:,}건")
k2.metric("불편불만 비율", f"{agg['meta']['complaint_ratio']}%")
k3.metric("평균 처리시간", f"{agg['meta']['avg_duration_h']}시간", f"중앙값 {agg['meta']['median_duration_h']}h")
k4.metric("칭찬·격려", f"{agg['meta']['praise_count']:,}건")

# ---------------------------------------------------------------------------
# 01. 채널 & 유형
# ---------------------------------------------------------------------------
st.markdown('<p class="section-label">01 · 채널 & 유형</p>', unsafe_allow_html=True)
c1, c2 = st.columns(2)
with c1:
    st.subheader("등록채널")
    st.plotly_chart(hbar(agg["channel"], BLUE, 220), use_container_width=True)
with c2:
    st.subheader("요구유형 분포")
    d = agg["request_type"]
    fig = go.Figure(go.Pie(
        labels=[x["name"] for x in d], values=[x["value"] for x in d], hole=0.55,
        marker=dict(colors=[RED, BLUE, AQUA, YELLOW], line=dict(color="#fff", width=2)),
        textinfo="label+percent",
    ))
    fig.update_layout(**base_layout(220))
    st.plotly_chart(fig, use_container_width=True)

c3, c4 = st.columns(2)
with c3:
    st.subheader("고객유형")
    st.plotly_chart(vbar(agg["customer_type"], VIOLET, 250, top=8), use_container_width=True)
with c4:
    st.subheader("시간대별 접수")
    st.plotly_chart(vbar(agg["timebin"], ORANGE, 250), use_container_width=True)

# ---------------------------------------------------------------------------
# 02. 서비스유형 & 이용편명
# ---------------------------------------------------------------------------
st.markdown('<p class="section-label">02 · 서비스유형 & 이용편명</p>', unsafe_allow_html=True)
st.subheader("서비스유형 TOP 10")
st.plotly_chart(hbar(agg["service_type"], AQUA, 340, top=10), use_container_width=True)

c5, c6 = st.columns([1, 1.4])
with c5:
    st.subheader("터미널별")
    d = agg["terminal"]
    fig = go.Figure(go.Pie(
        labels=[x["name"] for x in d], values=[x["value"] for x in d],
        marker=dict(colors=[GRAY, "#c3c2b7", BLUE, AQUA], line=dict(color="#fff", width=2)),
    ))
    fig.update_layout(**base_layout(260, showlegend=True))
    st.plotly_chart(fig, use_container_width=True)
with c6:
    st.subheader("항공사별 TOP 10 (식별 가능 건)")
    st.plotly_chart(vbar(agg["airline"], BLUE, 260, top=10), use_container_width=True)

# ---------------------------------------------------------------------------
# 03. 답변부서 & 발생원인
# ---------------------------------------------------------------------------
st.markdown('<p class="section-label">03 · 답변부서 & 발생원인</p>', unsafe_allow_html=True)
c7, c8 = st.columns(2)
with c7:
    st.subheader("답변부서")
    st.plotly_chart(hbar(agg["dept"], VIOLET, 260), use_container_width=True)
with c8:
    st.subheader("발생원인")
    st.plotly_chart(hbar(agg["cause"], ORANGE, 260), use_container_width=True)

# ---------------------------------------------------------------------------
# 04. 추이 & 교차분석 & 빈도 키워드
# ---------------------------------------------------------------------------
st.markdown('<p class="section-label">04 · 추이 · 교차분석 & 빈도 키워드</p>', unsafe_allow_html=True)

st.subheader("월별 VOC 접수 추이")
d = agg["monthly"]
fig = go.Figure(go.Scatter(
    x=[x["month"] for x in d], y=[x["value"] for x in d],
    mode="lines", line=dict(color=BLUE, width=2), fill="tozeroy",
    fillcolor="rgba(42,120,214,0.1)",
))
fig.update_layout(**base_layout(260))
fig.update_xaxes(nticks=12)
st.plotly_chart(fig, use_container_width=True)

st.subheader("요구유형 x 발생원인 교차분석")
cross = agg["cross_request_cause"]
fig = go.Figure()
for i, cause in enumerate(cross["causes"]):
    fig.add_bar(
        name=cause, x=cross["requests"],
        y=[row[i] for row in cross["matrix"]],
        marker_color=CROSS_COLORS[i % len(CROSS_COLORS)],
    )
fig.update_layout(**base_layout(300, showlegend=True, barmode="stack"))
fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
st.plotly_chart(fig, use_container_width=True)

c9, c10 = st.columns(2)
with c9:
    st.subheader("제목 키워드(빈도) TOP 8")
    st.plotly_chart(hbar(agg["title_keywords"], BLUE, 260, top=8), use_container_width=True)
with c10:
    st.subheader("내용 키워드(빈도) TOP 8")
    st.plotly_chart(hbar(agg["content_keywords"], VIOLET, 260, top=8), use_container_width=True)

# ---------------------------------------------------------------------------
# 05. TF-IDF 키워드 분석
# ---------------------------------------------------------------------------
st.markdown('<p class="section-label">05 · TF-IDF 키워드 분석</p>', unsafe_allow_html=True)
st.caption("단순 빈도와 달리, 여러 접수 건에 걸쳐 고르게 중요한 단어(제목/내용) 또는 특정 요구유형에서 유독 두드러지는 단어(요구유형별)를 잡아냅니다.")

c11, c12 = st.columns(2)
with c11:
    st.subheader("제목 TF-IDF 키워드 TOP 15")
    if agg.get("tfidf_title"):
        st.plotly_chart(hbar(agg["tfidf_title"], YELLOW, 320, top=15), use_container_width=True)
    else:
        st.info("선택된 기간의 표본이 적어 TF-IDF를 계산할 수 없습니다.")
with c12:
    st.subheader("내용 TF-IDF 키워드 TOP 15")
    if agg.get("tfidf_content"):
        st.plotly_chart(hbar(agg["tfidf_content"], MAGENTA, 320, top=15), use_container_width=True)
    else:
        st.info("선택된 기간의 표본이 적어 TF-IDF를 계산할 수 없습니다.")

st.subheader("요구유형별 대표(distinctive) 키워드 — TF-IDF 기준")
by_group = agg.get("tfidf_by_request_type", {})
group_order = ["불편불만", "상담문의", "의견제안", "칭찬격려"]
group_colors = {"불편불만": RED, "상담문의": BLUE, "의견제안": YELLOW, "칭찬격려": AQUA}
if by_group:
    label_set = []
    for g in group_order:
        for item in by_group.get(g, [])[:6]:
            if item["name"] not in label_set:
                label_set.append(item["name"])
    fig = go.Figure()
    for g in group_order:
        gmap = {x["name"]: x["value"] for x in by_group.get(g, [])}
        fig.add_bar(name=g, x=label_set, y=[gmap.get(l, 0) for l in label_set], marker_color=group_colors[g])
    fig.update_layout(**base_layout(340, showlegend=True, barmode="group"))
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("선택된 기간에 요구유형별 비교를 위한 표본이 부족합니다.")

st.caption("voc_raw.xlsx 기반 · analyze_voc.py 집계 로직 재사용 · 연도 선택 시 전체 화면 자동 재계산")
