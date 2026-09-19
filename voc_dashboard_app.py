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
# 출국장 여객흐름 분석 (월별 통합, Xovis 센서 원본 기반)
#   기존 "출국장 여객흐름 분석"과 "_2(월별 비교)" 두 페이지를 하나로 합쳤다.
#   analyze_passenger_flow.py 의 load_and_prepare() / build_dashboard_data() 를
#   재사용하되, 서로 다른 월의 원본 파일을 왼쪽 사이드바 버튼으로 전환해서 볼 수
#   있게 한다.
#     2월 = xovis_flow_02m.csv (`26.2.9~2.14)
#     3월 = xovis_flow_03m.csv (`26.3.9~3.14)
#     4월 = xovis_flow_04m.csv (`26.4.6~4.11)
# =============================================================================
FLOW2_MONTH_FILES = {
    "1월": "xovis_flow_01m.csv",
    "2월": "xovis_flow_02m.csv",
    "3월": "xovis_flow_03m.csv",
    "4월": "xovis_flow_04m.csv",
    "5월": "xovis_flow_05m.csv",
    "6월": "xovis_flow_06m.csv",
    "7월": "xovis_flow_07m.csv",
    "8월": "xovis_flow_08m.csv",
    "9월": "xovis_flow_09m.csv",
    "10월": "xovis_flow_10m.csv",
    "11월": "xovis_flow_11m.csv",
    "12월": "xovis_flow_12m.csv",
}
# 실제로 데이터 파일이 있는 월(2~8월). 나머지 달은 버튼은
# 보이지만 눌렀을 때 "데이터 없음" 안내와 업로드 위젯이 뜬다.
FLOW2_MONTHS_WITH_DATA = {"2월", "3월", "4월", "5월", "6월", "7월", "8월"}
FLOW2_APP_DIR = Path(__file__).resolve().parent


def _find_flow2_data_file(filename):
    """지정한 파일명(.csv) 그대로, 그리고 gzip 압축본(.csv.gz)까지 함께
    찾는다 — GitHub 업로드 용량 절감을 위해 .gz로 커밋하는 경우가 많아서다."""
    bases = [FLOW2_APP_DIR, FLOW2_APP_DIR / "data", Path(".")]
    candidates = []
    for base in bases:
        candidates.append(base / filename)
        candidates.append(base / f"{filename}.gz")
    for p in candidates:
        if p.exists():
            return p, candidates
    return None, candidates


@st.cache_data
def _flow2_load(source):
    return flow_load_and_prepare(source)


def get_flow2_raw_df(month: str):
    """선택한 월의 출국장 센서 원본 데이터를 로드한다. 저장소에 파일이 없으면
    업로드 위젯으로 대체한다."""
    filename = FLOW2_MONTH_FILES[month]
    found, candidates = _find_flow2_data_file(filename)
    if found is not None:
        return _flow2_load(str(found))

    st.warning(
        f"{month} 출국장 센서 원본 CSV(`{filename}`)를 찾지 못했습니다. 다음 경로들을 확인했습니다:\n\n"
        + "\n".join(f"- `{p}`" for p in candidates)
        + "\n\n저장소에 데이터 파일을 커밋했다면 경로/파일명을 확인해 주세요. "
        "지금 바로 확인하려면 아래에 파일을 업로드하세요."
    )
    uploaded = st.file_uploader(f"'{filename}'(.gz 압축본도 가능) 파일 업로드", type=["csv", "gz"], key=f"flow2_uploader_{month}")
    if uploaded is None:
        st.stop()
    return _flow2_load(uploaded)


@st.cache_data
def get_flow2_aggregates(month: str, terminal_tuple=()):
    """analyze_passenger_flow.build_dashboard_data 재사용 (기본 페이지와 동일 로직).
    캐시 키를 (month, terminal_tuple) 문자열/튜플로만 잡아서 — 매번 큰
    DataFrame을 해싱하지 않아 훨씬 빠르고, 월이 바뀌면 반드시 새로 계산된다.
    (예전엔 DataFrame 인자 이름을 밑줄로 시작해 캐시 키에서 제외했었는데,
    그 바람에 terminal_tuple이 같으면 월이 달라도 첫 계산 결과를 그대로
    재사용하는 버그가 있었다.)"""
    df = get_flow2_raw_df(month)
    if terminal_tuple:
        df = df[df["tmnl_cd"].isin(terminal_tuple)]
    return flow_build_dashboard_data(df)


def render_passenger_flow_dashboard():
    st.title("출국장 여객흐름 분석")
    st.caption("월 선택 · 터미널 · 출국장 · 시간대별 처리 여객수 · 평균 소요시간 · 대기열 규모 (Xovis 센서 원본 기반)")

    # ---------------------------------------------------------------
    # 연도 선택 (사이드바) — 현재는 2026년 데이터만 있지만, VOC 페이지와
    # 동일한 구조로 맞춰서 나중에 다른 연도가 추가돼도 그대로 확장되게 한다.
    # ---------------------------------------------------------------
    years_available = ["2026"]
    if "selected_flow2_year" not in st.session_state:
        st.session_state.selected_flow2_year = years_available[0]

    st.sidebar.header("연도 선택")
    ycols = st.sidebar.columns(len(years_available))
    for col, y in zip(ycols, years_available):
        is_sel = st.session_state.selected_flow2_year == y
        if col.button(f"{y}년", key=f"flow2_year_btn_{y}", type="primary" if is_sel else "secondary", use_container_width=True):
            st.session_state.selected_flow2_year = y
            st.rerun()

    # ---------------------------------------------------------------
    # 월 선택 (사이드바) — 기본 페이지와 완전히 동일한 분석을, 월만 바꿔서 본다
    # ---------------------------------------------------------------
    all_months = list(FLOW2_MONTH_FILES.keys())
    if "selected_flow2_month" not in st.session_state:
        # 데이터가 있는 첫 번째 달을 기본값으로 (없으면 첫 번째 달)
        st.session_state.selected_flow2_month = next(iter(FLOW2_MONTHS_WITH_DATA), all_months[0])

    st.sidebar.header("월 선택")
    st.sidebar.caption(f"데이터 보유: {', '.join(sorted(FLOW2_MONTHS_WITH_DATA, key=lambda m: int(m.replace('월',''))))}")
    for row_start in range(0, len(all_months), 4):
        row_months = all_months[row_start:row_start + 4]
        month_cols = st.sidebar.columns(4)
        for col, m in zip(month_cols, row_months):
            is_sel = st.session_state.selected_flow2_month == m
            has_data = m in FLOW2_MONTHS_WITH_DATA
            label = m if has_data else f"{m}·"
            if col.button(label, key=f"flow2_month_btn_{m}", type="primary" if is_sel else "secondary", use_container_width=True):
                st.session_state.selected_flow2_month = m
                st.rerun()

    month = st.session_state.selected_flow2_month
    flow_df = get_flow2_raw_df(month)

    # ---------------------------------------------------------------
    # 터미널 선택 (사이드바)
    # ---------------------------------------------------------------
    all_terminals = sorted(flow_df["tmnl_cd"].unique().tolist())
    if "selected_flow2_terminal" not in st.session_state:
        st.session_state.selected_flow2_terminal = "전체"

    st.sidebar.header("터미널 선택")
    term_options = ["전체"] + all_terminals
    tcols = st.sidebar.columns(len(term_options))
    for col, t in zip(tcols, term_options):
        is_selected = st.session_state.selected_flow2_terminal == t
        if col.button(
            t, key=f"flow2_term_btn_{t}",
            type="primary" if is_selected else "secondary",
            use_container_width=True,
        ):
            st.session_state.selected_flow2_terminal = t
            st.rerun()

    if st.session_state.selected_flow2_terminal == "전체":
        terminal_key = tuple()
    else:
        terminal_key = (st.session_state.selected_flow2_terminal,)

    data = get_flow2_aggregates(month, terminal_key)

    term_label = "전체 터미널" if st.session_state.selected_flow2_terminal == "전체" else st.session_state.selected_flow2_terminal
    st.caption(f"현재 보기: {st.session_state.selected_flow2_year}년 {month} · {term_label}  ·  분석기간 {data['meta']['date_min']} ~ {data['meta']['date_max']}")

    has_processed = data["meta"]["total_processed"] > 0
    has_processed = data["meta"]["total_processed"] > 0
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("총 처리 여객", f"{data['meta']['total_processed']:,}명" if has_processed else "집계 불가")
    k2.metric("평균 소요시간", f"{data['meta']['avg_wait_sec']/60:.1f}분")
    k3.metric("P95 소요시간", f"{data['meta']['p95_wait_sec']/60:.1f}분")
    k4.metric("피크 시간대", f"{data['meta']['peak_hour']}시" if has_processed else "-")
    k5.metric("최다혼잡 출국장", data["meta"]["busiest_zone"] if has_processed else "-")
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
        st.subheader("시간대별 소요시간 (분)")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=bh["hours"], y=[v / 60 for v in bh["avg_wait_sec"]], mode="lines", name="평균",
            line=dict(color=YELLOW, width=2), fill="tozeroy", fillcolor="rgba(237,161,0,0.12)",
        ))
        fig.add_trace(go.Scatter(
            x=bh["hours"], y=[v / 60 for v in bh["p95_wait_sec"]], mode="lines", name="P95",
            line=dict(color=RED, width=2, dash="dot"),
        ))
        fig.update_layout(**base_layout(280, showlegend=True))
        fig.update_xaxes(nticks=8)
        fig.update_yaxes(title="소요시간(분)")
        fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
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
        st.subheader("출국장별 소요시간 (분)")
        fig_wz = go.Figure()
        fig_wz.add_bar(name="평균", x=bz["zones"], y=[v / 60 for v in bz["avg_wait_sec"]], marker_color=RED)
        fig_wz.add_bar(name="P95", x=bz["zones"], y=[v / 60 for v in bz["p95_wait_sec"]], marker_color=YELLOW)
        fig_wz.update_layout(**base_layout(260, showlegend=True, barmode="group"))
        fig_wz.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
        st.plotly_chart(fig_wz, use_container_width=True)
    with c5:
        st.subheader("출국장별 평균 대기열")
        st.plotly_chart(vbar(zone_items(bz["queue_avg"]), VIOLET, 260), use_container_width=True)

    # -------------------------------------------------------------------
    # 03. 터미널별 비교
    # -------------------------------------------------------------------
    st.markdown('<p class="section-label">03 · 터미널별 비교</p>', unsafe_allow_html=True)
    bt = data["by_terminal"]
    if not bt:
        st.info("선택한 조건에 해당하는 터미널 데이터가 없습니다.")
    elif len(bt) > 1:
        bt_items = lambda key: [{"name": t["terminal"], "value": t[key]} for t in bt]
        ct1, ct2, ct3 = st.columns(3)
        with ct1:
            st.subheader("터미널별 처리 여객수")
            if has_processed:
                st.plotly_chart(vbar(bt_items("processed"), BLUE, 240), use_container_width=True)
            else:
                st.info("집계 불가")
        with ct2:
            st.subheader("터미널별 소요시간 (분)")
            fig_wt = go.Figure()
            fig_wt.add_bar(name="평균", x=[t["terminal"] for t in bt], y=[t["avg_wait_sec"] / 60 for t in bt], marker_color=RED)
            fig_wt.add_bar(name="P95", x=[t["terminal"] for t in bt], y=[t["p95_wait_sec"] / 60 for t in bt], marker_color=YELLOW)
            fig_wt.update_layout(**base_layout(240, showlegend=True, barmode="group"))
            fig_wt.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
            st.plotly_chart(fig_wt, use_container_width=True)
        with ct3:
            st.subheader("터미널별 평균 대기열")
            st.plotly_chart(vbar(bt_items("queue_avg"), VIOLET, 240), use_container_width=True)
    else:
        st.info(
            f"현재 데이터에는 터미널이 '{bt[0]['terminal']}' 하나만 존재해 터미널 간 비교를 표시할 수 없습니다."
        )
        tk1, tk2, tk3, tk4 = st.columns(4)
        tk1.metric(f"{bt[0]['terminal']} 총 처리여객", f"{bt[0]['processed']:,}명")
        tk2.metric(f"{bt[0]['terminal']} 평균 소요시간", f"{bt[0]['avg_wait_sec']/60:.1f}분")
        tk3.metric(f"{bt[0]['terminal']} P95 소요시간", f"{bt[0]['p95_wait_sec']/60:.1f}분")
        tk4.metric(f"{bt[0]['terminal']} 평균 대기열", f"{bt[0]['queue_avg']}명")

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
    # 05. 측정지점별 비교 (입구 동/서 vs 보안검색대 vs 게이트 레인)
    # -------------------------------------------------------------------
    st.markdown('<p class="section-label">05 · 측정지점별 비교</p>', unsafe_allow_html=True)
    st.caption("입구(동/서), 보안검색대, 게이트 레인 등 어느 구간에서 지연이 발생하는지 비교합니다.")
    bp = data.get("by_measure_point")
    if bp and bp.get("points"):
        point_items = lambda values: [{"name": n, "value": v} for n, v in zip(bp["points"], values)]
        cp1, cp2 = st.columns(2)
        with cp1:
            st.subheader("측정지점별 평균 대기열")
            st.plotly_chart(hbar(point_items(bp["queue_avg"]), AQUA, 200), use_container_width=True)
        with cp2:
            st.subheader("측정지점별 소요시간 (분)")
            fig_wp = go.Figure()
            fig_wp.add_bar(name="평균", y=bp["points"], x=[v / 60 for v in bp["avg_wait_sec"]], orientation="h", marker_color=RED)
            fig_wp.add_bar(name="P95", y=bp["points"], x=[v / 60 for v in bp["p95_wait_sec"]], orientation="h", marker_color=YELLOW)
            fig_wp.update_layout(**base_layout(200, showlegend=True, barmode="group"))
            fig_wp.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
            st.plotly_chart(fig_wp, use_container_width=True)

    # -------------------------------------------------------------------
    # 06. 스마트패스 vs 일반 출국장 그룹 비교
    # -------------------------------------------------------------------
    st.markdown('<p class="section-label">06 · 스마트패스 vs 일반 그룹 비교</p>', unsafe_allow_html=True)
    bg = data.get("by_gate_group")
    if bg:
        group_zones_caption = " · ".join(f"{g['group']}: {', '.join(g['zones'])}" for g in bg)
        st.caption(group_zones_caption)
        gg1, gg2, gg3, gg4 = st.columns(4)
        group_colors = {"스마트패스": AQUA, "일반": GRAY}
        bar_colors_bg = [group_colors.get(g["group"], BLUE) for g in bg]
        with gg1:
            st.subheader("그룹별 처리 여객수")
            if has_processed:
                fig_g1 = go.Figure(go.Bar(
                    x=[g["group"] for g in bg], y=[g["processed"] for g in bg],
                    marker_color=bar_colors_bg, marker=dict(cornerradius=4),
                ))
                fig_g1.update_layout(**base_layout(240))
                st.plotly_chart(fig_g1, use_container_width=True)
            else:
                st.info("집계 불가")
        with gg2:
            st.subheader("그룹별 평균 소요시간 (분)")
            fig_g2 = go.Figure(go.Bar(
                x=[g["group"] for g in bg], y=[g["avg_wait_sec"] / 60 for g in bg],
                marker_color=bar_colors_bg, marker=dict(cornerradius=4),
            ))
            fig_g2.update_layout(**base_layout(240))
            st.plotly_chart(fig_g2, use_container_width=True)
        with gg3:
            st.subheader("그룹별 P95 소요시간 (분)")
            fig_g3 = go.Figure(go.Bar(
                x=[g["group"] for g in bg], y=[g["p95_wait_sec"] / 60 for g in bg],
                marker_color=bar_colors_bg, marker=dict(cornerradius=4),
            ))
            fig_g3.update_layout(**base_layout(240))
            st.plotly_chart(fig_g3, use_container_width=True)
        with gg4:
            st.subheader("그룹별 평균 대기열")
            fig_g4 = go.Figure(go.Bar(
                x=[g["group"] for g in bg], y=[g["queue_avg"] for g in bg],
                marker_color=bar_colors_bg, marker=dict(cornerradius=4),
            ))
            fig_g4.update_layout(**base_layout(240))
            st.plotly_chart(fig_g4, use_container_width=True)

        # 시간대별 추이 — 전체 평균만 보면 왜 차이가 나는지 알기 어려워서,
        # 어느 시간대에 격차가 벌어지는지 확인할 수 있게 추가.
        ggh = data.get("gate_group_by_hour", {})
        if ggh:
            st.caption("⚠ 결함으로 자동 탐지된 센서(예: 대기열이 수천 명까지 찍히는 비정상 스트림)는 제외하고 계산했습니다.")
            gh1, gh2 = st.columns(2)
            group_line_colors = {"스마트패스": AQUA, "일반": GRAY}
            with gh1:
                st.subheader("시간대별 평균 소요시간 (분)")
                fig_gh1 = go.Figure()
                for grp, series in ggh.items():
                    fig_gh1.add_trace(go.Scatter(
                        x=series["hours"], y=[v / 60 for v in series["avg_wait_sec"]],
                        mode="lines+markers", name=grp,
                        line=dict(width=2.2, color=group_line_colors.get(grp)),
                        marker=dict(size=4),
                    ))
                fig_gh1.update_layout(**base_layout(300, showlegend=True))
                fig_gh1.update_layout(
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                    yaxis=dict(title="소요시간(분)"),
                )
                st.plotly_chart(fig_gh1, use_container_width=True)
            with gh2:
                st.subheader("시간대별 P95 소요시간 (분)")
                fig_gh2 = go.Figure()
                for grp, series in ggh.items():
                    fig_gh2.add_trace(go.Scatter(
                        x=series["hours"], y=[v / 60 for v in series["p95_wait_sec"]],
                        mode="lines+markers", name=grp,
                        line=dict(width=2.2, color=group_line_colors.get(grp)),
                        marker=dict(size=4),
                    ))
                fig_gh2.update_layout(**base_layout(300, showlegend=True))
                fig_gh2.update_layout(
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                    yaxis=dict(title="소요시간(분)"),
                )
                st.plotly_chart(fig_gh2, use_container_width=True)

            # 차트만으로는 정확한 값을 읽기 어려워서, 시간대별 실제 수치를
            # 표로도 함께 제공한다 (평균·P95·대기열, 그룹별).
            st.subheader("시간대별 분석 값")
            hours_ref = next(iter(ggh.values()))["hours"]
            table_rows = []
            for h_idx, h in enumerate(hours_ref):
                row = {"시간대": h}
                for grp, series in ggh.items():
                    row[f"{grp} 평균(분)"] = round(series["avg_wait_sec"][h_idx] / 60, 1)
                    row[f"{grp} P95(분)"] = round(series["p95_wait_sec"][h_idx] / 60, 1)
                    row[f"{grp} 대기열(명)"] = series["queue_avg"][h_idx]
                table_rows.append(row)
            st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
    else:
        st.info("스마트패스/일반 그룹 데이터가 없습니다.")

    st.caption(
        f"{FLOW2_MONTH_FILES[month]} 기반 · analyze_passenger_flow.py 집계 로직 재사용(기본 여객흐름 페이지와 동일) · "
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
    # 필터별 "전체" 선택을 처리하는 공용 헬퍼
    #   - 절차구분 "전체" → 신분확인+보안검색을 게이트별로 합산 (요청하신
    #     "합쳐놓은 시간 계산 결과")
    #   - 보고서 "전체" → 1차·2차를 게이트별로 평균
    #   - 터미널 "전체" → T1·T2 게이트를 한 차트에 "터미널 게이트명"으로 합쳐서 표시
    #   - 지표 "전체" → P95·평균 두 계열을 함께 표시
    # ---------------------------------------------------------------
    def resolve_list(sel, all_values):
        return list(all_values) if sel == "전체" else [sel]

    def combined_overall(report_sel, category_sel, terminal_sel, metric_sel):
        """게이트별 '전체' 소요시간을 선택 조건에 맞춰 결합해 반환한다.
        반환값: [{"metric":..,"gate":.., "seconds":..}, ...]"""
        reports = resolve_list(report_sel, data["meta"]["reports"])
        categories = resolve_list(category_sel, data["meta"]["categories"])
        terminals = resolve_list(terminal_sel, data["meta"]["terminals"])
        metrics = resolve_list(metric_sel, ["P95", "평균"])

        out_rows = []
        for m in metrics:
            for t in terminals:
                gate_list = None
                for r in reports:
                    for c in categories:
                        gl = data["gates_by_terminal"].get(r, {}).get(c, {}).get(t)
                        if gl:
                            gate_list = gl
                            break
                    if gate_list:
                        break
                if not gate_list:
                    continue
                for g in gate_list:
                    report_vals = []
                    for r in reports:
                        cat_sum, found = 0.0, False
                        for c in categories:
                            match = next((x for x in data["overall"]
                                          if x["report"] == r and x["category"] == c
                                          and x["terminal"] == t and x["gate"] == g and x["metric"] == m), None)
                            if match:
                                cat_sum += match["seconds"]
                                found = True
                        if found:
                            report_vals.append(cat_sum)
                    if report_vals:
                        label = g if len(terminals) == 1 else f"{t} {g}"
                        out_rows.append({"metric": m, "gate": label, "seconds": sum(report_vals) / len(report_vals)})
        return out_rows

    def combined_hourly(report_sel, category_sel, terminal_sel, metric_sel):
        """게이트별 시간대별 소요시간(분)을 같은 규칙으로 결합해 반환한다.
        반환값: {gate_label: [시간대별 초(seconds) 리스트]}"""
        reports = resolve_list(report_sel, data["meta"]["reports"])
        categories = resolve_list(category_sel, data["meta"]["categories"])
        terminals = resolve_list(terminal_sel, data["meta"]["terminals"])
        metric = metric_sel if metric_sel != "전체" else "P95"
        n_slots = len(data["meta"]["time_slots"])

        result = {}
        for t in terminals:
            gate_list = None
            for r in reports:
                for c in categories:
                    gl = data["gates_by_terminal"].get(r, {}).get(c, {}).get(t)
                    if gl:
                        gate_list = gl
                        break
                if gate_list:
                    break
            if not gate_list:
                continue
            for g in gate_list:
                report_series = []
                for r in reports:
                    cat_sum = [0.0] * n_slots
                    found = False
                    for c in categories:
                        s = data["series"].get(r, {}).get(c, {}).get(t, {}).get(metric, {}).get(g)
                        if s and len(s) == n_slots:
                            cat_sum = [a + b for a, b in zip(cat_sum, s)]
                            found = True
                    if found:
                        report_series.append(cat_sum)
                if report_series:
                    avg_series = [sum(vals) / len(vals) for vals in zip(*report_series)]
                    label = g if len(terminals) == 1 else f"{t} {g}"
                    result[label] = avg_series
        return result

    # ---------------------------------------------------------------
    # 보고서 선택 (사이드바) — 1차(`26.2.12~2.15) / 2차(`26.6.20~6.23) / 전체
    # ---------------------------------------------------------------
    all_reports = data["meta"]["reports"]
    report_options = all_reports + ["전체"]
    if "selected_imm_report" not in st.session_state:
        st.session_state.selected_imm_report = all_reports[-1]

    st.sidebar.header("보고서 선택")
    report_cols = st.sidebar.columns(len(report_options))
    for col, r in zip(report_cols, report_options):
        is_sel = st.session_state.selected_imm_report == r
        if col.button(r, key=f"imm_report_btn_{r}", type="primary" if is_sel else "secondary", use_container_width=True):
            st.session_state.selected_imm_report = r
            st.rerun()

    # ---------------------------------------------------------------
    # 절차구분 선택 (사이드바) — 신분확인 / 보안검색 / 전체(합산)
    # ---------------------------------------------------------------
    all_categories = data["meta"]["categories"]
    category_options = all_categories + ["전체"]
    if "selected_imm_category" not in st.session_state:
        st.session_state.selected_imm_category = all_categories[0]

    st.sidebar.header("절차구분 선택")
    st.sidebar.caption("'전체' 선택 시 신분확인+보안검색을 게이트별로 합산합니다")
    cat_cols = st.sidebar.columns(len(category_options))
    for col, c in zip(cat_cols, category_options):
        is_sel = st.session_state.selected_imm_category == c
        if col.button(c, key=f"imm_cat_btn_{c}", type="primary" if is_sel else "secondary", use_container_width=True):
            st.session_state.selected_imm_category = c
            st.rerun()

    # ---------------------------------------------------------------
    # 터미널 선택 (사이드바)
    # ---------------------------------------------------------------
    all_terminals = data["meta"]["terminals"]
    terminal_options = all_terminals + ["전체"]
    if "selected_imm_terminal" not in st.session_state:
        st.session_state.selected_imm_terminal = all_terminals[0]

    st.sidebar.header("터미널 선택")
    term_cols = st.sidebar.columns(len(terminal_options))
    for col, t in zip(term_cols, terminal_options):
        is_sel = st.session_state.selected_imm_terminal == t
        if col.button(t, key=f"imm_term_btn_{t}", type="primary" if is_sel else "secondary", use_container_width=True):
            st.session_state.selected_imm_terminal = t
            st.rerun()

    # 지표 선택 (P95 / 평균 / 전체)
    if "selected_imm_metric" not in st.session_state:
        st.session_state.selected_imm_metric = "P95"
    st.sidebar.header("지표 선택")
    metric_options = ["P95", "평균", "전체"]
    metric_cols = st.sidebar.columns(3)
    for col, m in zip(metric_cols, metric_options):
        is_sel = st.session_state.selected_imm_metric == m
        label = "95%" if m == "P95" else m
        if col.button(label, key=f"imm_metric_btn_{m}", type="primary" if is_sel else "secondary", use_container_width=True):
            st.session_state.selected_imm_metric = m
            st.rerun()

    report = st.session_state.selected_imm_report
    category = st.session_state.selected_imm_category
    term = st.session_state.selected_imm_terminal
    metric = st.session_state.selected_imm_metric
    metric_label = {"P95": "95% 소요시간", "평균": "평균 소요시간", "전체": "95%+평균 소요시간"}[metric]

    # 단일 값이 필요한 하위 섹션(04/05)을 위한 대표값 (전체 선택 시 첫 값으로 대체)
    single_metric = metric if metric != "전체" else "P95"

    st.caption(f"현재 보기: {report} 보고서 · {category} · {term}  ·  {metric_label}")

    # ---------------------------------------------------------------
    # KPI 카드 — combined_overall() 하나로 모든 "전체" 조합을 일관되게 반영
    # ---------------------------------------------------------------
    combo_rows = combined_overall(report, category, term, "P95")  # KPI는 P95 기준 대표
    if combo_rows:
        best = min(combo_rows, key=lambda r: r["seconds"])
        worst = max(combo_rows, key=lambda r: r["seconds"])
        avg_p95 = sum(r["seconds"] for r in combo_rows) / len(combo_rows)
    else:
        best = worst = None
        avg_p95 = 0

    reports_for_proc = resolve_list(report, all_reports)
    categories_for_proc = resolve_list(category, all_categories)
    total_processed = sum(
        data["processed"][r][c][0] for r in reports_for_proc for c in categories_for_proc
    )
    proc_label = category if category != "전체" else "신분확인+보안검색"

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(f"{proc_label} 전체 처리인원", f"{total_processed:,}건")
    k2.metric("평균 P95 소요시간", f"{avg_p95//60:.0f}분 {avg_p95%60:.0f}초")
    if worst:
        k3.metric("최장 게이트(P95)", worst["gate"], f"{worst['seconds']//60:.0f}분 {worst['seconds']%60:.0f}초")
    if best:
        k4.metric("최단 게이트(P95)", best["gate"], f"{best['seconds']//60:.0f}분 {best['seconds']%60:.0f}초")

    st.divider()

    # ---------------------------------------------------------------
    # 01. 시간대별 처리인원 (보고서·절차구분 전체 집계 — 게이트별 세부값은 원본에 없음)
    # ---------------------------------------------------------------
    st.markdown('<p class="section-label">01 · 시간대별 처리인원</p>', unsafe_allow_html=True)
    st.caption(f"⚠ 원본 표에 게이트별 처리인원이 없어, {proc_label} 전체(모든 터미널·게이트 합산) 기준으로만 제공합니다.")
    hours = [s for s in data["meta"]["time_slots"] if s != "전체"]

    proc_series_by_cat = {}
    for c in categories_for_proc:
        summed = [0] * (len(data["meta"]["time_slots"]))
        for r in reports_for_proc:
            vals = data["processed"][r][c]
            summed = [a + b for a, b in zip(summed, vals)]
        proc_series_by_cat[c] = summed[1:]  # '전체' 제외

    fig0 = go.Figure()
    proc_colors = {"신분확인": AQUA, "보안검색": VIOLET}
    for c, vals in proc_series_by_cat.items():
        fig0.add_bar(name=c, x=hours, y=vals, marker_color=proc_colors.get(c, BLUE))
    fig0.update_layout(**base_layout(260, showlegend=len(proc_series_by_cat) > 1, barmode="group"))
    fig0.update_layout(yaxis=dict(title="처리인원(건)"))
    st.subheader(f"{report} · {proc_label} 시간대별 처리인원 (전체 {total_processed:,}건)")
    st.plotly_chart(fig0, use_container_width=True)

    # ---------------------------------------------------------------
    # 02. 시간대별 게이트별 소요시간 추이 (막대 — 게이트별 그룹 막대)
    # ---------------------------------------------------------------
    st.markdown('<p class="section-label">02 · 시간대별 게이트별 소요시간 추이</p>', unsafe_allow_html=True)
    hourly = combined_hourly(report, category, term, metric)

    bar_colors = [BLUE, AQUA, RED, VIOLET, YELLOW, "#8b6fd6", "#4ecbb0", "#f2a6c1", "#6fb1e0"]
    fig = go.Figure()
    for i, (g, full) in enumerate(hourly.items()):
        y = full[1:] if len(full) == len(data["meta"]["time_slots"]) else full
        fig.add_bar(name=g, x=hours, y=[v / 60 for v in y], marker_color=bar_colors[i % len(bar_colors)])
    fig.update_layout(**base_layout(380, showlegend=True, barmode="group"))
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        yaxis=dict(title="소요시간(분)"),
    )
    st.subheader(f"{term} 게이트별 시간대별 {metric_label} (분)")
    st.plotly_chart(fig, use_container_width=True)

    # ---------------------------------------------------------------
    # 03. 게이트별 "전체" 소요시간 비교 (막대) — 요청하신 절차구분 합산 결과가
    #     여기 그대로 반영된다 (절차구분="전체" 선택 시 신분확인+보안검색 합산)
    # ---------------------------------------------------------------
    st.markdown('<p class="section-label">03 · 게이트별 전체 소요시간 비교</p>', unsafe_allow_html=True)
    if category == "전체":
        st.caption("📐 신분확인 + 보안검색 소요시간을 게이트별로 합산한 값입니다 (총 체류시간 개념).")
    combo_all = combined_overall(report, category, term, metric)
    if metric == "전체":
        fig2 = go.Figure()
        metric_colors = {"P95": AQUA, "평균": YELLOW}
        gate_order = [r["gate"] for r in combo_all if r["metric"] == combo_all[0]["metric"]]
        for m in ["P95", "평균"]:
            rows_m = [r for r in combo_all if r["metric"] == m]
            rows_m.sort(key=lambda r: gate_order.index(r["gate"]) if r["gate"] in gate_order else 0)
            fig2.add_bar(name=m, x=[r["gate"] for r in rows_m], y=[r["seconds"] / 60 for r in rows_m],
                         marker_color=metric_colors[m])
        fig2.update_layout(**base_layout(300, showlegend=True, barmode="group"))
    else:
        combo_all.sort(key=lambda r: r["seconds"], reverse=True)
        fig2 = go.Figure(go.Bar(
            x=[r["gate"] for r in combo_all], y=[r["seconds"] / 60 for r in combo_all],
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
            rows_r = combined_overall(r, category, term, single_metric)
            gate_order = combined_overall("전체", category, term, single_metric)
            gate_order_list = [x["gate"] for x in gate_order]
            rows_r.sort(key=lambda x: gate_order_list.index(x["gate"]) if x["gate"] in gate_order_list else 0)
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
            rows_c = combined_overall(report, c, term, single_metric)
            gate_order = combined_overall(report, c, term, single_metric)
            gate_order_list = [x["gate"] for x in gate_order]
            rows_c.sort(key=lambda x: gate_order_list.index(x["gate"]) if x["gate"] in gate_order_list else 0)
            fig4.add_bar(name=c, x=[x["gate"] for x in rows_c], y=[x["seconds"] / 60 for x in rows_c],
                         marker_color=cat_colors.get(c, GRAY))
        fig4.update_layout(**base_layout(300, showlegend=True, barmode="group"))
        fig4.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0), yaxis=dict(title="소요시간(분)"))
        st.plotly_chart(fig4, use_container_width=True)

    # ---------------------------------------------------------------
    # 06. 스마트패스 vs 일반 게이트 그룹 비교
    #     (현재 report/category 선택 기준 — "전체"면 여러 조합을 겹쳐서 비교)
    # ---------------------------------------------------------------
    st.markdown('<p class="section-label">06 · 스마트패스 vs 일반 그룹 비교</p>', unsafe_allow_html=True)
    bgg_all = data.get("by_gate_group", [])
    bgg_reports = resolve_list(report, all_reports)
    bgg_categories = resolve_list(category, all_categories)
    bgg_metrics = resolve_list(metric, ["P95", "평균"])
    bgg_rows = [g for g in bgg_all if g["report"] in bgg_reports and g["category"] in bgg_categories and g["metric"] in bgg_metrics]

    if bgg_rows:
        group_gate_map = {g["group"]: g["gates"] for g in bgg_all
                           if g["report"] == bgg_reports[0] and g["category"] == bgg_categories[0] and g["metric"] == "P95"}
        st.caption(" · ".join(f"{grp}: {', '.join(gates)}" for grp, gates in group_gate_map.items()))

        # 표시 라벨: report/category가 "전체"라 여러 조합이 섞이면 라벨에 구분 표기
        def _label(g):
            parts = []
            if len(bgg_reports) > 1:
                parts.append(g["report"])
            if len(bgg_categories) > 1:
                parts.append(g["category"])
            if len(bgg_metrics) > 1:
                parts.append(g["metric"])
            return " · ".join(parts) if parts else g["group"]

        fig6 = go.Figure()
        group_colors = {"스마트패스": AQUA, "일반": GRAY}
        for grp in ["스마트패스", "일반"]:
            rows_g = [g for g in bgg_rows if g["group"] == grp]
            if not rows_g:
                continue
            fig6.add_bar(
                name=grp, x=[_label(g) for g in rows_g], y=[g["avg_seconds"] / 60 for g in rows_g],
                marker_color=group_colors[grp],
            )
        fig6.update_layout(**base_layout(300, showlegend=True, barmode="group"))
        fig6.update_layout(
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            yaxis=dict(title="평균 소요시간(분, 그룹 내 게이트 단순평균)"),
        )
        st.subheader("스마트패스 vs 일반 — 게이트 단순평균 소요시간")
        st.plotly_chart(fig6, use_container_width=True)
    else:
        st.info("스마트패스/일반 그룹 데이터가 없습니다.")

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

