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

레이아웃
  - 왼쪽 사이드바: 분석 유형(VOC/여객흐름) 선택에 따라 관련 필터가 나타남
      · VOC 분석 페이지  → 답변부서 다중선택 + 연도 버튼(전체/2021~2026)
      · 여객흐름 분석 페이지 → 터미널 버튼(전체/P01/P02)
  - 연도별 접수 현황 (선택 연도 강조)
  - KPI 카드 4개
  - 01 채널 & 유형   : 등록채널 / 요구유형 / 고객유형 / 시간대
  - 02 서비스유형 & 이용편명 : 서비스유형 TOP / 터미널 / 항공사
  - 03 답변부서 & 발생원인
  - 04 추이·교차분석 & 빈도 키워드 : 월별추이 / 요구유형x발생원인 / 제목·내용 키워드(빈도)
  - 05 TF-IDF 키워드 분석 : 제목/내용 TF-IDF TOP15 + 요구유형별 대표 키워드 비교
  - 06 키워드 정성 분석 : 키워드 선택 시 실제 접수 제목/내용 사례 조회

두 번째 페이지 "출국장 여객흐름 분석"은 analyze_passenger_flow.py 의
load_and_prepare() / build_dashboard_data() 를 재사용한다 (Xovis 센서 원본,
xovis_flow.csv 기반 — 터미널 P01/P02 실측 비교 포함, 사이드바에서 터미널 선택 가능).
  - KPI 카드 (총 처리여객 / 평균 소요시간 / 피크시간대 / 최다혼잡 출국장)
  - 01 시간대별 처리여객수 · 평균소요시간
  - 02 출국장별 처리여객수 · 평균소요시간 · 평균대기열
  - 03 터미널별(P01/P02) 처리여객 · 소요시간 · 대기열 비교
  - 04 출국장 x 시간대 처리여객 히트맵
  - 05 측정지점별(입구 동/서 · 보안검색대) 비교
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from pathlib import Path

from analyze_voc import load_and_prepare, build_aggregates, INPUT_PATH
from analyze_passenger_flow import (
    load_and_prepare as flow_load_and_prepare,
    build_dashboard_data as flow_build_dashboard_data,
    INPUT_PATH as FLOW_INPUT_PATH,
)
from analyze_immigration import (
    load_and_prepare as imm_load_and_prepare,
    build_dashboard_data as imm_build_dashboard_data,
    INPUT_PATH as IMM_INPUT_PATH,
)

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
def get_aggregates(years_tuple, dept_tuple, _df):
    """선택된 연도(들)/답변부서(들)로 필터링한 뒤 12개 축 집계를 다시 계산한다.
    tuple 이 비어있으면(=전체 선택) 해당 조건은 필터링하지 않는다.
    _df 를 인자로 받아 캐시 키에 원본 데이터 변경(파일 재업로드 등)도 반영한다."""
    df = _df
    if years_tuple:
        df = df[df["연도"].isin(years_tuple)]
    if dept_tuple:
        df = df[df["답변부서_간략"].isin(dept_tuple)]
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
    /* 연도 버튼 스타일: 선택된 연도는 primary(파란색), 나머지는 secondary(회색) */
    div[data-testid="stHorizontalBlock"] button[kind="secondary"] {
        background: #f0efe9; border-color: #e1e0d9; color: #52514e;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_voc_dashboard():
    raw_df = get_raw_df()
    agg = get_aggregates(tuple(), tuple(), raw_df)  # 초기 타이틀 표시용 (전체 기간 기준)
    st.title("보안검색 서비스 VOC 분석 대시보드")
    st.caption(f"분석기간 {agg['meta']['date_min']} ~ {agg['meta']['date_max']}  ·  전체 접수 {agg['meta']['total']:,}건")

    # ---------------------------------------------------------------------------
    # 사이드바: 답변부서 선택
    #   선택한 부서(들)가 처리한 VOC만 걸러서 전체 화면을 다시 계산한다.
    #   연도 버튼 필터와 동시에 적용된다 (AND 조건).
    # ---------------------------------------------------------------------------
    dept_counts_all = raw_df["답변부서_간략"].fillna("미기재").value_counts()
    dept_options = list(dept_counts_all.index)

    st.sidebar.header("답변부서 선택")
    selected_depts = st.sidebar.multiselect(
        "분석할 답변부서를 선택하세요 (미선택 시 전체 부서)",
        options=dept_options,
        default=[],
        format_func=lambda d: f"{d} ({dept_counts_all[d]:,}건)",
    )
    if not selected_depts:
        st.sidebar.caption("부서를 선택하지 않아 전체 부서를 표시합니다.")
    dept_key = tuple(sorted(selected_depts)) if selected_depts else tuple()

    # ---------------------------------------------------------------------------
    # 연도 선택 (사이드바): 버튼을 눌러서 연도별로 분석
    #   "전체" + 각 연도 버튼을 배치. 클릭한 연도가 선택되며
    #   session_state 에 저장되어 다음 rerun에서도 유지된다.
    # ---------------------------------------------------------------------------
    years_available = sorted(int(y) for y in raw_df["연도"].dropna().unique())

    if "selected_year" not in st.session_state:
        st.session_state.selected_year = "전체"

    st.sidebar.header("연도 선택")
    year_options = ["전체"] + [str(y) for y in years_available]
    # 사이드바 폭이 좁으므로 한 줄에 3개씩 버튼을 배치한다.
    for row_start in range(0, len(year_options), 3):
        row_opts = year_options[row_start:row_start + 3]
        cols = st.sidebar.columns(len(row_opts))
        for col, y in zip(cols, row_opts):
            is_selected = st.session_state.selected_year == y
            if col.button(
                y if y == "전체" else f"{y}년",
                key=f"year_btn_{y}",
                type="primary" if is_selected else "secondary",
                use_container_width=True,
            ):
                st.session_state.selected_year = y
                st.rerun()

    if st.session_state.selected_year == "전체":
        selected_years = years_available
    else:
        selected_years = [int(st.session_state.selected_year)]

    is_full_range = set(selected_years) == set(years_available)
    years_key = tuple() if is_full_range else tuple(sorted(selected_years))
    agg = get_aggregates(years_key, dept_key, raw_df)

    caption_parts = []
    if is_full_range:
        caption_parts.append(f"전체 기간 ({agg['meta']['date_min']} ~ {agg['meta']['date_max']})")
    else:
        caption_parts.append(", ".join(f"{y}년" for y in sorted(selected_years)))
    if selected_depts:
        caption_parts.append(", ".join(selected_depts) + " 부서")
    else:
        caption_parts.append("전체 부서")
    st.caption(f"현재 보기: {' · '.join(caption_parts)}  ·  선택 조건 접수 {agg['meta']['total']:,}건")

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

    # ---------------------------------------------------------------------------
    # 06. 키워드 정성 분석 — 실제 접수 사례 조회
    #   빈도/TF-IDF 수치만으로는 "그래서 실제로 무슨 내용인지" 알 수 없으므로,
    #   키워드를 선택하면 그 단어가 포함된 실제 제목·내용을 최신순으로 보여준다.
    # ---------------------------------------------------------------------------
    st.markdown('<p class="section-label">06 · 키워드 정성 분석 (실제 사례 조회)</p>', unsafe_allow_html=True)
    st.caption("키워드를 선택하면 해당 단어가 포함된 실제 접수 제목·내용을 최신순으로 확인할 수 있습니다.")

    kw_examples = agg.get("keyword_examples", {})
    if kw_examples:
        kw_choice = st.selectbox("키워드 선택", options=sorted(kw_examples.keys()))
        examples = kw_examples.get(kw_choice, [])
        if examples:
            for ex in examples:
                with st.container(border=True):
                    top_row = st.columns([3, 1, 1])
                    top_row[0].markdown(f"**{ex['제목']}**")
                    top_row[1].caption(ex["요구유형"])
                    top_row[2].caption(ex["등록일시"])
                    st.write(ex["내용"])
        else:
            st.info("선택된 기간에는 이 키워드를 포함한 사례가 없습니다.")
    else:
        st.info("선택된 기간의 표본이 적어 대표 사례를 찾을 수 없습니다.")

    st.caption("voc_raw.xlsx 기반 · analyze_voc.py 집계 로직 재사용 · 연도 선택 시 전체 화면 자동 재계산")

# =============================================================================
# 출국장 여객흐름 분석 (xovis_flow.csv 기반)
#   analyze_passenger_flow.py 의 load_and_prepare() / build_dashboard_data() 를
#   그대로 재사용한다. 컬럼 의미 추정 방식은 analyze_passenger_flow.py 상단
#   주석을 참고 — 실제 정의서와 교차검증을 권장한다는 점을 화면에도 안내한다.
# =============================================================================
FLOW_APP_DIR = Path(__file__).resolve().parent
FLOW_CANDIDATE_PATHS = [
    FLOW_APP_DIR / FLOW_INPUT_PATH,
    FLOW_APP_DIR / "data" / FLOW_INPUT_PATH,
    Path(FLOW_INPUT_PATH),
]


def _find_flow_data_file():
    for p in FLOW_CANDIDATE_PATHS:
        if p.exists():
            return p
    return None


@st.cache_data
def _flow_load(source):
    return flow_load_and_prepare(source)


def get_flow_raw_df():
    """출국장 센서 원본 데이터를 로드한다. 저장소에 파일이 없으면 업로드 위젯으로 대체한다."""
    found = _find_flow_data_file()
    if found is not None:
        return _flow_load(str(found))

    st.warning(
        "출국장 센서 원본 CSV를 찾지 못했습니다. 다음 경로들을 확인했습니다:\n\n"
        + "\n".join(f"- `{p}`" for p in FLOW_CANDIDATE_PATHS)
        + "\n\n저장소에 데이터 파일을 커밋했다면 경로/파일명을 확인해 주세요. "
        "지금 바로 확인하려면 아래에 파일을 업로드하세요."
    )
    uploaded = st.file_uploader(f"'{FLOW_INPUT_PATH}' 파일 업로드", type=["csv"])
    if uploaded is None:
        st.stop()
    return _flow_load(uploaded)


@st.cache_data
def get_flow_aggregates(_df, terminal_tuple=()):
    """시간대/출국장/터미널 단위 집계 결과를 계산한다 (analyze_passenger_flow.build_dashboard_data 재사용).
    terminal_tuple 이 비어있으면(=전체 선택) 필터링하지 않는다."""
    df = _df
    if terminal_tuple:
        df = df[df["tmnl_cd"].isin(terminal_tuple)]
    return flow_build_dashboard_data(df)


def render_passenger_flow_dashboard():
    st.title("출국장 여객흐름 분석 대시보드")
    st.caption("터미널 · 출국장 · 시간대별 처리 여객수 · 평균 소요시간 · 대기열 규모 (Xovis 센서 원본 기반)")

    flow_df = get_flow_raw_df()

    # ---------------------------------------------------------------
    # 터미널 선택 (사이드바): 버튼을 눌러서 터미널별로 분석
    # ---------------------------------------------------------------
    all_terminals = sorted(flow_df["tmnl_cd"].unique().tolist())
    if "selected_terminal" not in st.session_state:
        st.session_state.selected_terminal = "전체"

    st.sidebar.header("터미널 선택")
    term_options = ["전체"] + all_terminals
    tcols = st.sidebar.columns(len(term_options))
    for col, t in zip(tcols, term_options):
        is_selected = st.session_state.selected_terminal == t
        if col.button(
            t, key=f"term_btn_{t}",
            type="primary" if is_selected else "secondary",
            use_container_width=True,
        ):
            st.session_state.selected_terminal = t
            st.rerun()

    if st.session_state.selected_terminal == "전체":
        terminal_key = tuple()
    else:
        terminal_key = (st.session_state.selected_terminal,)

    data = get_flow_aggregates(flow_df, terminal_key)

    label = "전체 터미널" if st.session_state.selected_terminal == "전체" else st.session_state.selected_terminal
    st.caption(f"현재 보기: {label}  ·  분석기간 {data['meta']['date_min']} ~ {data['meta']['date_max']}")

    has_processed = data["meta"]["total_processed"] > 0
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("총 처리 여객", f"{data['meta']['total_processed']:,}명" if has_processed else "집계 불가")
    k2.metric("평균 소요시간", f"{data['meta']['avg_wait_sec']/60:.1f}분")
    k3.metric("피크 시간대", f"{data['meta']['peak_hour']}시" if has_processed else "-")
    k4.metric("최다혼잡 출국장", data["meta"]["busiest_zone"] if has_processed else "-")
    if not has_processed:
        st.caption("⚠ 이 데이터에는 처리여객수 집계에 필요한 값이 없어 소요시간·대기열 지표만 제공됩니다.")

    st.divider()

    # -------------------------------------------------------------------
    # 01. 시간대별 전체 흐름
    # -------------------------------------------------------------------
    st.markdown('<p class="section-label">01 · 시간대별 전체 흐름</p>', unsafe_allow_html=True)
    c1, c2 = st.columns([1.4, 1])
    with c1:
        st.subheader("시간대별 처리 여객수")
        bh = data["by_hour"]
        if has_processed:
            fig = go.Figure(go.Bar(
                x=bh["hours"], y=bh["processed"], marker_color=BLUE, marker=dict(cornerradius=4),
            ))
            fig.update_layout(**base_layout(280))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("이 데이터에는 처리여객수 집계에 필요한 값이 없습니다.")
    with c2:
        st.subheader("시간대별 평균 소요시간 (분)")
        fig = go.Figure(go.Scatter(
            x=bh["hours"], y=[v / 60 for v in bh["avg_wait_sec"]], mode="lines",
            line=dict(color=YELLOW, width=2), fill="tozeroy", fillcolor="rgba(237,161,0,0.12)",
        ))
        fig.update_layout(**base_layout(280))
        fig.update_xaxes(nticks=8)
        fig.update_yaxes(title="소요시간(분)")
        st.plotly_chart(fig, use_container_width=True)

    # -------------------------------------------------------------------
    # 02. 출국장별 비교
    # -------------------------------------------------------------------
    st.markdown('<p class="section-label">02 · 출국장별 비교</p>', unsafe_allow_html=True)
    bz = data["by_zone"]
    zone_items = lambda values: [{"name": n, "value": v} for n, v in zip(bz["zones"], values)]

    c3, c4, c5 = st.columns(3)
    with c3:
        st.subheader("출국장별 처리 여객수")
        if has_processed:
            st.plotly_chart(vbar(zone_items(bz["processed"]), AQUA, 260), use_container_width=True)
        else:
            st.info("집계 불가")
    with c4:
        st.subheader("출국장별 평균 소요시간 (분)")
        wait_min_items = [{"name": n, "value": v / 60} for n, v in zip(bz["zones"], bz["avg_wait_sec"])]
        st.plotly_chart(vbar(wait_min_items, RED, 260), use_container_width=True)
    with c5:
        st.subheader("출국장별 평균 대기열")
        st.plotly_chart(vbar(zone_items(bz["queue_avg"]), VIOLET, 260), use_container_width=True)

    # -------------------------------------------------------------------
    # 03. 터미널별 비교
    # -------------------------------------------------------------------
    st.markdown('<p class="section-label">03 · 터미널별 비교</p>', unsafe_allow_html=True)
    bt = data["by_terminal"]
    if len(bt) > 1:
        bt_items = lambda key: [{"name": t["terminal"], "value": t[key]} for t in bt]
        ct1, ct2, ct3 = st.columns(3)
        with ct1:
            st.subheader("터미널별 처리 여객수")
            if has_processed:
                st.plotly_chart(vbar(bt_items("processed"), BLUE, 240), use_container_width=True)
            else:
                st.info("집계 불가")
        with ct2:
            st.subheader("터미널별 평균 소요시간 (분)")
            wait_min_bt = [{"name": t["terminal"], "value": t["avg_wait_sec"] / 60} for t in bt]
            st.plotly_chart(vbar(wait_min_bt, RED, 240), use_container_width=True)
        with ct3:
            st.subheader("터미널별 평균 대기열")
            st.plotly_chart(vbar(bt_items("queue_avg"), VIOLET, 240), use_container_width=True)
    else:
        st.info(
            f"현재 데이터에는 터미널이 '{bt[0]['terminal']}' 하나만 존재해 터미널 간 비교를 표시할 수 없습니다. "
            "다른 터미널 데이터가 추가되면 이 화면이 자동으로 터미널별 비교 차트를 그립니다."
        )
        tk1, tk2, tk3 = st.columns(3)
        tk1.metric(f"{bt[0]['terminal']} 총 처리여객", f"{bt[0]['processed']:,}명")
        tk2.metric(f"{bt[0]['terminal']} 평균 소요시간", f"{bt[0]['avg_wait_sec']/60:.1f}분")
        tk3.metric(f"{bt[0]['terminal']} 평균 대기열", f"{bt[0]['queue_avg']}명")

    # -------------------------------------------------------------------
    # 04. 출국장 x 시간대 히트맵
    # -------------------------------------------------------------------
    st.markdown('<p class="section-label">04 · 출국장 × 시간대 히트맵</p>', unsafe_allow_html=True)
    st.subheader("출국장별 시간대별 처리 여객수")
    if has_processed:
        hm = data["heatmap_processed"]
        fig = go.Figure(go.Heatmap(
            z=hm["matrix"], x=hm["hours"], y=hm["zones"],
            colorscale=[[0, "#f4f6fc"], [1, BLUE]],
            showscale=True, hovertemplate="%{y} · %{x}<br>처리여객 %{z:,}명<extra></extra>",
        ))
        fig.update_layout(
            height=360, margin=dict(l=8, r=8, t=8, b=8), font=CHART_FONT,
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("이 데이터에는 처리여객수 집계에 필요한 값이 없어 히트맵을 표시할 수 없습니다.")

    # -------------------------------------------------------------------
    # 05. 측정지점별 비교 (입구 동/서 vs 보안검색대)
    # -------------------------------------------------------------------
    st.markdown('<p class="section-label">05 · 측정지점별 비교</p>', unsafe_allow_html=True)
    st.caption("입구(동/서)와 보안검색대 중 어느 구간에서 지연이 발생하는지 비교합니다.")
    bp = data.get("by_measure_point")
    if bp and bp.get("points"):
        point_items = lambda values: [{"name": n, "value": v} for n, v in zip(bp["points"], values)]
        cp1, cp2 = st.columns(2)
        with cp1:
            st.subheader("측정지점별 평균 대기열")
            st.plotly_chart(hbar(point_items(bp["queue_avg"]), AQUA, 200), use_container_width=True)
        with cp2:
            st.subheader("측정지점별 평균 소요시간 (분)")
            wait_min_points = [{"name": n, "value": v / 60} for n, v in zip(bp["points"], bp["avg_wait_sec"])]
            st.plotly_chart(hbar(wait_min_points, YELLOW, 200), use_container_width=True)

    st.caption(
        f"{FLOW_INPUT_PATH} 기반 · analyze_passenger_flow.py 집계 로직 재사용 · "
        "소요시간·대기열은 처리여객수 가중평균(0-활동 구간 제외) 방식으로 이상치에 견고하게 집계"
    )


# =============================================================================
# 출입국 심사 소요시간 모니터링 (immigration_processing_time.csv 기반)
#   analyze_immigration.py 의 load_and_prepare() / build_dashboard_data() 를
#   재사용한다. 원본은 "신분확인_보안검색_대기시간_2026-1-2차.pptx" 리포트의
#   표 4개(1차/2차 x 신분확인/보안검색)를 옮겨 적어 tidy CSV로 정리한 것이다.
# =============================================================================
IMM_APP_DIR = Path(__file__).resolve().parent
IMM_CANDIDATE_PATHS = [
    IMM_APP_DIR / IMM_INPUT_PATH,
    IMM_APP_DIR / "data" / IMM_INPUT_PATH,
    Path(IMM_INPUT_PATH),
]


def _find_imm_data_file():
    for p in IMM_CANDIDATE_PATHS:
        if p.exists():
            return p
    return None


@st.cache_data
def _imm_load(source):
    return imm_load_and_prepare(source)


def get_imm_raw_df():
    found = _find_imm_data_file()
    if found is not None:
        return _imm_load(str(found))

    st.warning(
        f"출입국 심사 소요시간 원본 CSV를 찾지 못했습니다. 다음 경로들을 확인했습니다:\n\n"
        + "\n".join(f"- `{p}`" for p in IMM_CANDIDATE_PATHS)
        + "\n\n지금 바로 확인하려면 아래에 파일을 업로드하세요."
    )
    uploaded = st.file_uploader(f"'{IMM_INPUT_PATH}' 파일 업로드", type=["csv"])
    if uploaded is None:
        st.stop()
    return _imm_load(uploaded)


@st.cache_data
def get_imm_aggregates(_df):
    return imm_build_dashboard_data(_df)


def render_immigration_dashboard():
    st.title("출입국 심사 소요시간 모니터링")
    st.caption("보고서 · 절차구분 · 터미널 · 출국장 · 시간대별 95%(P95) 소요시간 · 평균 소요시간 · 처리인원")

    imm_df = get_imm_raw_df()
    data = get_imm_aggregates(imm_df)

    # ---------------------------------------------------------------
    # 보고서 선택 (사이드바) — 1차(`26.2.12~2.15) / 2차(`26.6.20~6.23)
    # ---------------------------------------------------------------
    all_reports = data["meta"]["reports"]
    if "selected_imm_report" not in st.session_state:
        st.session_state.selected_imm_report = all_reports[-1]

    st.sidebar.header("보고서 선택")
    report_cols = st.sidebar.columns(len(all_reports))
    for col, r in zip(report_cols, all_reports):
        is_sel = st.session_state.selected_imm_report == r
        if col.button(r, key=f"imm_report_btn_{r}", type="primary" if is_sel else "secondary", use_container_width=True):
            st.session_state.selected_imm_report = r
            st.rerun()

    # ---------------------------------------------------------------
    # 절차구분 선택 (사이드바) — 신분확인 / 보안검색
    # ---------------------------------------------------------------
    all_categories = data["meta"]["categories"]
    if "selected_imm_category" not in st.session_state:
        st.session_state.selected_imm_category = all_categories[0]

    st.sidebar.header("절차구분 선택")
    cat_cols = st.sidebar.columns(len(all_categories))
    for col, c in zip(cat_cols, all_categories):
        is_sel = st.session_state.selected_imm_category == c
        if col.button(c, key=f"imm_cat_btn_{c}", type="primary" if is_sel else "secondary", use_container_width=True):
            st.session_state.selected_imm_category = c
            st.rerun()

    # ---------------------------------------------------------------
    # 터미널 선택 (사이드바)
    # ---------------------------------------------------------------
    all_terminals = data["meta"]["terminals"]
    if "selected_imm_terminal" not in st.session_state:
        st.session_state.selected_imm_terminal = all_terminals[0]

    st.sidebar.header("터미널 선택")
    term_cols = st.sidebar.columns(len(all_terminals))
    for col, t in zip(term_cols, all_terminals):
        is_sel = st.session_state.selected_imm_terminal == t
        if col.button(t, key=f"imm_term_btn_{t}", type="primary" if is_sel else "secondary", use_container_width=True):
            st.session_state.selected_imm_terminal = t
            st.rerun()

    # 지표 선택 (P95 / 평균)
    if "selected_imm_metric" not in st.session_state:
        st.session_state.selected_imm_metric = "P95"
    st.sidebar.header("지표 선택")
    metric_cols = st.sidebar.columns(2)
    for col, m in zip(metric_cols, ["P95", "평균"]):
        is_sel = st.session_state.selected_imm_metric == m
        label = "95% 소요시간" if m == "P95" else "평균 소요시간"
        if col.button(label, key=f"imm_metric_btn_{m}", type="primary" if is_sel else "secondary", use_container_width=True):
            st.session_state.selected_imm_metric = m
            st.rerun()

    report = st.session_state.selected_imm_report
    category = st.session_state.selected_imm_category
    term = st.session_state.selected_imm_terminal
    metric = st.session_state.selected_imm_metric
    metric_label = "95% 소요시간" if metric == "P95" else "평균 소요시간"

    st.caption(f"현재 보기: {report} 보고서 · {category} · {term}  ·  {metric_label}")

    # ---------------------------------------------------------------
    # KPI 카드
    # ---------------------------------------------------------------
    summary = next((s for s in data["terminal_summary"]
                     if s["report"] == report and s["category"] == category and s["terminal"] == term), None)
    total_processed = data["processed"][report][category][0]  # '전체' 슬롯
    if summary:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric(f"{category} 전체 처리인원", f"{total_processed:,}건")
        k2.metric("평균 P95 소요시간", f"{summary['avg_p95_sec']//60:.0f}분 {summary['avg_p95_sec']%60:.0f}초")
        k3.metric("최장 게이트(P95)", summary["worst_gate"], f"{summary['worst_sec']//60}분 {summary['worst_sec']%60}초")
        k4.metric("최단 게이트(P95)", summary["best_gate"], f"{summary['best_sec']//60}분 {summary['best_sec']%60}초")

    st.divider()

    # ---------------------------------------------------------------
    # 01. 시간대별 처리인원 (보고서·절차구분 전체 집계 — 게이트별 세부값은 원본에 없음)
    # ---------------------------------------------------------------
    st.markdown('<p class="section-label">01 · 시간대별 처리인원</p>', unsafe_allow_html=True)
    st.caption(f"⚠ 원본 표에 게이트별 처리인원이 없어, {category} 전체(모든 터미널·게이트 합산) 기준으로만 제공합니다.")
    hours = [s for s in data["meta"]["time_slots"] if s != "전체"]
    proc_full = data["processed"][report][category]
    proc_hours = proc_full[1:]  # '전체' 제외, 시간대만

    fig0 = go.Figure(go.Bar(
        x=hours, y=proc_hours, marker_color=BLUE, marker=dict(cornerradius=4),
        hovertemplate="%{x}<br>%{y:,}건<extra></extra>",
    ))
    fig0.update_layout(**base_layout(260))
    fig0.update_layout(yaxis=dict(title="처리인원(건)"))
    st.subheader(f"{report} · {category} 시간대별 처리인원 (전체 {total_processed:,}건)")
    st.plotly_chart(fig0, use_container_width=True)

    # ---------------------------------------------------------------
    # 02. 시간대별 게이트별 소요시간 추이 (막대 — 게이트별 그룹 막대)
    # ---------------------------------------------------------------
    st.markdown('<p class="section-label">02 · 시간대별 게이트별 소요시간 추이</p>', unsafe_allow_html=True)
    gates = data["gates_by_terminal"][report][category][term]
    series = data["series"].get(report, {}).get(category, {}).get(term, {}).get(metric, {})

    bar_colors = [BLUE, AQUA, RED, VIOLET, YELLOW, "#8b6fd6", "#4ecbb0"]
    fig = go.Figure()
    for i, g in enumerate(gates):
        full = series.get(g, [])
        # series는 '전체' 포함 순서이므로 인덱스 1부터(시간대만) 슬라이스
        y = full[1:] if len(full) == len(data["meta"]["time_slots"]) else full
        fig.add_bar(
            name=g, x=hours, y=[v / 60 for v in y],
            marker_color=bar_colors[i % len(bar_colors)],
        )
    fig.update_layout(**base_layout(380, showlegend=True, barmode="group"))
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        yaxis=dict(title="소요시간(분)"),
    )
    st.subheader(f"{term} 게이트별 시간대별 {metric_label} (분)")
    st.plotly_chart(fig, use_container_width=True)

    # ---------------------------------------------------------------
    # 03. 게이트별 "전체" 소요시간 비교 (막대)
    # ---------------------------------------------------------------
    st.markdown('<p class="section-label">03 · 게이트별 전체 소요시간 비교</p>', unsafe_allow_html=True)
    overall_rows = [r for r in data["overall"]
                     if r["report"] == report and r["category"] == category
                     and r["terminal"] == term and r["metric"] == metric]
    overall_rows.sort(key=lambda r: r["seconds"], reverse=True)
    fig2 = go.Figure(go.Bar(
        x=[r["gate"] for r in overall_rows], y=[r["seconds"] / 60 for r in overall_rows],
        marker_color=AQUA, marker=dict(cornerradius=4),
        hovertemplate="%{x}<br>%{y:.1f}분<extra></extra>",
    ))
    fig2.update_layout(**base_layout(280))
    fig2.update_layout(yaxis=dict(title="소요시간(분)"))
    st.subheader(f"{term} 게이트별 전체 {metric_label}")
    st.plotly_chart(fig2, use_container_width=True)

    # ---------------------------------------------------------------
    # 04. 1차 vs 2차 보고서 비교 (해당 절차구분·터미널·지표 기준, "전체" 값)
    # ---------------------------------------------------------------
    if len(all_reports) > 1:
        st.markdown('<p class="section-label">04 · 보고서 회차 비교</p>', unsafe_allow_html=True)
        st.caption(f"{category} · {term} 게이트별 '전체' {metric_label} — 1차 vs 2차 나란히 비교")
        fig3 = go.Figure()
        cmp_colors = {all_reports[0]: BLUE, all_reports[-1]: RED}
        for r in all_reports:
            rows_r = [x for x in data["overall"]
                      if x["report"] == r and x["category"] == category
                      and x["terminal"] == term and x["metric"] == metric]
            gate_order = data["gates_by_terminal"][r][category][term]
            rows_r.sort(key=lambda x: gate_order.index(x["gate"]) if x["gate"] in gate_order else 0)
            fig3.add_bar(name=r, x=[x["gate"] for x in rows_r], y=[x["seconds"] / 60 for x in rows_r],
                         marker_color=cmp_colors.get(r, VIOLET))
        fig3.update_layout(**base_layout(300, showlegend=True, barmode="group"))
        fig3.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0), yaxis=dict(title="소요시간(분)"))
        st.plotly_chart(fig3, use_container_width=True)

    # ---------------------------------------------------------------
    # 05. 신분확인 vs 보안검색 비교 (해당 보고서·터미널·지표 기준, "전체" 값)
    # ---------------------------------------------------------------
    if len(all_categories) > 1:
        st.markdown('<p class="section-label">05 · 절차구분 비교</p>', unsafe_allow_html=True)
        st.caption(f"{report} · {term} 게이트별 '전체' {metric_label} — 신분확인 vs 보안검색 나란히 비교 (게이트 번호는 같아도 서로 다른 절차)")
        fig4 = go.Figure()
        cat_colors = {"신분확인": AQUA, "보안검색": VIOLET}
        for c in all_categories:
            rows_c = [x for x in data["overall"]
                      if x["report"] == report and x["category"] == c
                      and x["terminal"] == term and x["metric"] == metric]
            gate_order = data["gates_by_terminal"][report][c][term]
            rows_c.sort(key=lambda x: gate_order.index(x["gate"]) if x["gate"] in gate_order else 0)
            fig4.add_bar(name=c, x=[x["gate"] for x in rows_c], y=[x["seconds"] / 60 for x in rows_c],
                         marker_color=cat_colors.get(c, GRAY))
        fig4.update_layout(**base_layout(300, showlegend=True, barmode="group"))
        fig4.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0), yaxis=dict(title="소요시간(분)"))
        st.plotly_chart(fig4, use_container_width=True)

    st.caption(f"{IMM_INPUT_PATH} 기반 · analyze_immigration.py 집계 로직 재사용 · 11~13시는 원본 표에 데이터가 없어 제외됨")


# =============================================================================
# 페이지 라우팅
# =============================================================================
st.sidebar.markdown("### 분석 유형")
selected_page = st.sidebar.radio(
    "분석 유형 선택",
    ["VOC 분석", "출국장 여객흐름 분석", "출입국 심사 소요시간 모니터링"],
    label_visibility="collapsed",
)
st.sidebar.divider()

if selected_page == "VOC 분석":
    render_voc_dashboard()
elif selected_page == "출국장 여객흐름 분석":
    render_passenger_flow_dashboard()
else:
    render_immigration_dashboard()

