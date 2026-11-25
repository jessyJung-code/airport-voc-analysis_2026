# -*- coding: utf-8 -*-
"""출국장 여객흐름 분석 페이지 — DG 처리 인원(진입 태그)과 SG 대기시간·대기열.

입력(prepare_passenger_flow.py 출력, passenger_flow_data/ 폴더)
  dg_tags_hourly.csv : date, hour, terminal, departure_gate, dg_id, tag_count
  sg_wait_hourly.csv : date, hour, terminal, departure_gate, sg_zone, mapping_status,
                       wait_seconds_*/queue_length_* (sum, count, *_p95, p95)

화면 구성
  - 왼쪽 사이드바: 분석 월(버튼) · 터미널 · 날짜 범위 · 출국장 · DG 장비 · SG 구역 · P95 제외
  - 01 SG(보안검색 구역) 대기시간 · 대기열 (출국장별, 시간대별)
  - 02 DG 처리 인원 / 분당 처리 인원 / 인당 처리 시간
  - 03 출국장별 처리 인원(DG 태그 기준) × SG 대기시간
  - 04 운영 DG·보안검색대(호기) 가동률과 대기 (operation_snapshots.csv: prepare_operation_data.py 출력)
"""
import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# 색상: 최근 SaaS 대시보드에서 많이 쓰는 인디고·에메랄드·앰버·핑크·시안·바이올렛 계열(Tailwind 기반)
INDIGO, EMERALD, AMBER, PINK, CYAN, VIOLET_, ROSE, SLATE = ("#6366F1", "#10B981", "#F59E0B", "#F472B6",
                                                            "#22D3EE", "#A855F7", "#F43F5E", "#94A3B8")
BLUE, ORANGE, AQUA, YELLOW = INDIGO, AMBER, EMERALD, AMBER
MAGENTA, VIOLET, RED, GRAY = PINK, VIOLET_, ROSE, SLATE
GRID, TEXT_SECONDARY = "#e2e8f0", "#475569"
PALETTE = [INDIGO, EMERALD, AMBER, PINK, CYAN, VIOLET_, SLATE]
HEAT = [[0, "#EEF2FF"], [0.5, "#818CF8"], [1, "#3730A3"]]
# 보유 대수(가동률 분모). T2는 엑셀 머리글(호기 17대, 유인 DG 1번 12대·2번 8대).
# T1은 머리글에 없어 호기=엑셀 최대 운영 수(7대), DG=대시보드 장비 수(6대)로 가정 — 실제 보유 대수로 바꾸세요.
CAP_LANES = {("T1", g): 7 for g in range(1, 7)} | {("T2", 1): 17, ("T2", 2): 17}
CAP_DG = {("T1", g): 6 for g in range(1, 7)} | {("T2", 1): 12, ("T2", 2): 8}
FONT = dict(family="Pretendard, Noto Sans KR, sans-serif", size=12, color=TEXT_SECONDARY)

_STATE = {"title": "chart", "n": 0}


def _sub(text, *a, **k):
    _STATE["title"] = str(text)
    return st.subheader(text, *a, **k)


def _fig_frame(fig):
    """차트에 그려진 값을 표로 되돌린다(막대·선은 x/y, 히트맵은 행렬)."""
    frames = []
    for t in fig.data:
        if t.type == "heatmap":
            df = pd.DataFrame(t.z, index=list(t.y), columns=list(t.x))
            df.index.name = "구분"
            frames.append(df.reset_index())
        elif getattr(t, "x", None) is not None and getattr(t, "y", None) is not None:
            frames.append(pd.DataFrame({"계열": t.name or "값", "x": list(t.x), "y": list(t.y)}))
    if not frames:
        return pd.DataFrame()
    if all("계열" in f.columns for f in frames):
        df = pd.concat(frames)
        if df["계열"].nunique() > 1:
            return df.pivot_table(index="x", columns="계열", values="y", sort=False).reset_index().rename(columns={"x": "구분"})
        return df.drop(columns="계열").rename(columns={"x": "구분", "y": df["계열"].iloc[0]})
    return frames[0]


def _show(fig, *a, **k):
    """차트를 그리고 바로 아래에 그 차트의 데이터 다운로드 버튼을 둔다."""
    st.plotly_chart(fig, *a, **k)
    try:
        df = _fig_frame(fig)
        if not df.empty:
            _STATE["n"] += 1
            name = re.sub(r"[^0-9A-Za-z가-힣]+", "_", _STATE["title"]).strip("_")[:40] or "chart"
            st.download_button("⬇ 이 차트 데이터 (CSV)", df.round(3).to_csv(index=False).encode("utf-8-sig"),
                               f"{name}.csv", mime="text/csv", key=f"pf_dl_{_STATE['n']}")
    except Exception:
        pass


@st.cache_data
def load_data(path, modified):
    return pd.read_csv(path, parse_dates=["date"])


def _layout(height, legend=False, barmode=None):
    layout = dict(height=height, margin=dict(l=8, r=8, t=8, b=8), font=FONT,
                  showlegend=legend, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                  xaxis=dict(gridcolor=GRID, zeroline=False), yaxis=dict(gridcolor=GRID, zeroline=False))
    if legend:
        layout["legend"] = dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)
    if barmode:
        layout["barmode"] = barmode
    return layout


def _bar(df, x, y, color, height=260, title_y=None, fmt=None):
    fig = go.Figure(go.Bar(x=df[x], y=df[y], marker_color=color, marker=dict(cornerradius=4),
                           text=df[y].map(fmt) if fmt else None, textposition="outside" if fmt else None))
    fig.update_layout(**_layout(height))
    if title_y:
        fig.update_yaxes(title=title_y)
    return fig


def _bars(fig, df, x, y, group, unit="", order=None, text=False):
    """그룹(출국장 등)별 묶음 막대."""
    for i, (name, g) in enumerate(df.groupby(group)):
        g = g.sort_values(x) if order is None else g.assign(_o=g[x].map({k: n for n, k in enumerate(order)})).sort_values("_o")
        fig.add_trace(go.Bar(x=g[x], y=g[y], name=str(name), marker_color=PALETTE[i % len(PALETTE)],
                             marker=dict(cornerradius=4), text=g[y].map("{:.1f}".format) if text else None,
                             textposition="outside" if text else None,
                             hovertemplate=f"{name}<br>%{{x}} → %{{y:.2f}}{unit}<extra></extra>"))
    return fig


def _trace(x, y, name, i, size=11, unit=""):
    """굵은 곡선 + 흰 테두리가 있는 큰 원 마커."""
    c = PALETTE[i % len(PALETTE)]
    return go.Scatter(x=x, y=y, mode="lines+markers", name=str(name),
                      line=dict(color=c, width=3.5, shape="spline", smoothing=0.5),
                      marker=dict(size=size, color=c, line=dict(color="white", width=2)),
                      hovertemplate=f"{name}<br>%{{x}} → %{{y:.2f}}{unit}<extra></extra>")


def _line_fig(fig, df, x, y, group, unit="", order=None, size=11):
    for i, (name, g) in enumerate(df.groupby(group)):
        g = g.sort_values(x) if order is None else g.assign(_o=g[x].map({k: n for n, k in enumerate(order)})).sort_values("_o")
        fig.add_trace(_trace(g[x], g[y], name, i, size=size, unit=unit))
    return fig


def _lines(df, x, y, group, height=280, title_y=None):
    """시간대별 그룹 비교: 그룹이 8개 이하면 묶음 막대, 그보다 많으면 히트맵."""
    if df[group].nunique() > 8:
        piv = df.pivot_table(index=group, columns=x, values=y).reindex(columns=range(24))
        fig = go.Figure(go.Heatmap(z=piv.values, x=[f"{h}시" for h in piv.columns], y=piv.index.tolist(),
                                   colorscale=HEAT, colorbar=dict(title=title_y or "")))
        fig.update_layout(**_layout(max(280, 24 * len(piv) + 60)))
        fig.update_yaxes(autorange="reversed")
        return fig
    fig = _line_fig(go.Figure(), df, x, y, group, size=9)
    fig.update_layout(**_layout(height, legend=True), hovermode="x unified")
    fig.update_xaxes(dtick=2, title="시간대(시)")
    if title_y:
        fig.update_yaxes(title=title_y)
    return fig


def _section(label):
    st.markdown(f'<p class="section-label">{label}</p>', unsafe_allow_html=True)


def _month_buttons(months_with_data):
    """VOC 분석 페이지와 같은 방식의 월 선택 버튼(1~12월). 데이터가 없는 달은 비활성."""
    if st.session_state.get("pf_month") not in months_with_data:
        st.session_state.pf_month = months_with_data[-1]
    st.sidebar.header("분석 월")
    st.sidebar.caption("데이터 보유: " + ", ".join(f"{m}월" for m in months_with_data))
    for start in range(1, 13, 3):
        cols = st.sidebar.columns(3)
        for col, m in zip(cols, range(start, start + 3)):
            has = m in months_with_data
            if col.button(f"{m}월", key=f"pf_month_btn_{m}", disabled=not has, use_container_width=True,
                          type="primary" if st.session_state.pf_month == m else "secondary"):
                st.session_state.pf_month = m
                st.rerun()
    return st.session_state.pf_month


def render_passenger_flow():
    _STATE["n"] = 0
    st.title("출국장 여객흐름 분석")
    root = Path(__file__).parent / "passenger_flow_data"
    paths = [root / "dg_tags_hourly.csv", root / "sg_wait_hourly.csv"]
    if not all(p.is_file() for p in paths):
        st.info("DG 처리 인원·SG 대기 집계 파일을 준비해 주세요.")
        return
    tags_all, sens_all = [load_data(str(p), p.stat().st_mtime_ns).copy() for p in paths]
    months = sorted(set(tags_all["date"].dt.month) | set(sens_all["date"].dt.month))

    # ---------------- 사이드바 필터 ----------------
    month = _month_buttons(months)
    st.sidebar.header("터미널")
    terminal = st.sidebar.radio("터미널", ["T1", "T2"], horizontal=True, key="pf_terminal",
                                label_visibility="collapsed")
    tags = tags_all[(tags_all["date"].dt.month == month) & (tags_all["terminal"] == terminal)]
    sens = sens_all[(sens_all["date"].dt.month == month) & (sens_all["terminal"] == terminal)]
    dates = sorted(set(tags["date"].dt.date) | set(sens["date"].dt.date))
    if not dates:
        st.info("선택한 월·터미널에 데이터가 없습니다.")
        return
    st.sidebar.header("날짜 범위")
    period = st.sidebar.date_input("날짜 범위", (dates[0], dates[-1]), min_value=dates[0], max_value=dates[-1],
                                   key=f"pf_dates_{month}_{terminal}", label_visibility="collapsed")
    if len(period) != 2:
        st.info("시작일과 종료일을 선택하세요.")
        return
    in_period = lambda d: d[d["date"].between(pd.Timestamp(period[0]), pd.Timestamp(period[1]))]
    tags, sens = in_period(tags), in_period(sens)

    gates = sorted(set(tags["departure_gate"]) | set(sens["departure_gate"]))
    st.sidebar.header("출국장")
    chosen_gates = st.sidebar.multiselect("출국장", gates, default=gates, key=f"pf_gates_{month}_{terminal}",
                                          format_func=lambda g: f"{g}번", label_visibility="collapsed")
    tags = tags[tags["departure_gate"].isin(chosen_gates)]
    sens = sens[sens["departure_gate"].isin(chosen_gates)]

    tags_g = tags  # 04 섹션용: DG 장비 선택과 무관하게 출국장 전체 운영 대수를 계산
    st.sidebar.header("DG 장비 선택")
    dg_all = sorted(tags["dg_id"].unique())
    chosen_dg = st.sidebar.multiselect("DG 장비", dg_all, default=dg_all, key=f"pf_dg_{month}_{terminal}",
                                       label_visibility="collapsed")
    tags = tags[tags["dg_id"].isin(chosen_dg)]

    sens = sens.assign(구역=sens["departure_gate"].astype(str) + "번 / " + sens["sg_zone"])
    st.sidebar.header("보안검색 구역(SG) 선택")
    zone_all = sorted(sens["구역"].unique())
    chosen_zone = st.sidebar.multiselect("보안검색 구역(SG)", zone_all, default=zone_all, key=f"pf_zone_{month}_{terminal}",
                                         label_visibility="collapsed")
    sens = sens[sens["구역"].isin(chosen_zone)]
    trim = st.sidebar.checkbox("P95 초과 대기·대기열 관측 제외", True, key="pf_trim")

    st.caption(f"{month}월 · {terminal} · {period[0]} ~ {period[1]}"
               + (" · P95 초과 관측 제외" if trim else ""))
    if st.session_state.get("developer_authenticated", False):
        st.caption("DG 인원은 진입시분 기준 최초 태그입니다. SG 대기와 대기열 길이는 센서 관측 평균이며, "
                   "태그 인원으로 가중하지 않습니다. P95는 월·출국장·센서 구역별로 계산합니다.")

    # ---------------- DG 집계 ----------------
    dg_hour = tags.groupby(["date", "hour", "departure_gate", "dg_id"], as_index=False)["tag_count"].sum()
    dg_hour = dg_hour[dg_hour["tag_count"] > 0]  # 운영(태그 발생) 시간만
    dg = dg_hour.groupby(["departure_gate", "dg_id"], as_index=False).agg(
        total=("tag_count", "sum"), active_hours=("tag_count", "size"))
    dg["per_hour"] = dg["total"] / dg["active_hours"]
    dg["per_min"] = dg["per_hour"] / 60
    dg["sec_per_pax"] = 3600 / dg["per_hour"]            # 인당 처리 시간(초) = 운영 시간 ÷ 처리 인원
    dg["label"] = dg["dg_id"].str.extract(r"(D\d{3}DG\d+)", expand=False).fillna(dg["dg_id"])
    dg["gate_label"] = dg["departure_gate"].astype(str) + "번"
    days_n = max(1, tags["date"].nunique())              # 데이터가 있는 일수 (일평균의 분모)
    dg["per_day"] = dg["total"] / days_n
    dg = dg.sort_values(["departure_gate", "dg_id"])

    # ---------------- SG 집계 ----------------
    sfx = "_p95" if trim else ""
    def sg_agg(keys):
        r = sens.groupby(keys, as_index=False)[[f"wait_seconds_sum{sfx}", f"wait_seconds_count{sfx}",
                                                 f"queue_length_sum{sfx}", f"queue_length_count{sfx}"]].sum()
        wc, qc = r[f"wait_seconds_count{sfx}"], r[f"queue_length_count{sfx}"]
        r["wait_min"] = r[f"wait_seconds_sum{sfx}"].div(wc.where(wc > 0)).div(60)
        r["queue"] = r[f"queue_length_sum{sfx}"].div(qc.where(qc > 0))
        return r

    # ---------------- KPI ----------------
    total = int(dg["total"].sum()) if not dg.empty else 0
    k1, k2, k3 = st.columns(3)
    k1.metric("일평균 처리 인원(진입 태그)", f"{total / days_n:,.0f}명",
              help=f"선택 기간 합계 {total:,}명 ÷ 데이터가 있는 {days_n}일")
    k2.metric("DG 장비 수", f"{len(dg)}대", help="선택 범위에서 태그가 발생한 DG 장비 수")
    k3.metric("DG당 평균 분당 처리 인원", f"{dg['per_min'].mean():.2f}명" if len(dg) else "-",
              help="DG별 (시간당 처리 인원 ÷ 60)의 평균. 태그가 발생한 시간만 운영 시간으로 계산")
    all_wait = sg_agg(["terminal"]) if not sens.empty else pd.DataFrame()
    k4, k5, k6 = st.columns(3)
    k4.metric("DG 인당 평균 처리 시간", f"{dg['sec_per_pax'].mean():.1f}초" if len(dg) else "-",
              help="DG별 (3,600초 ÷ 시간당 처리 인원)의 평균")
    k5.metric("평균 대기시간", f"{all_wait['wait_min'].iloc[0]:.1f}분" if len(all_wait) else "-")
    k6.metric("평균 대기열", f"{all_wait['queue'].iloc[0]:.1f}명" if len(all_wait) else "-")
    st.divider()

    # ---------------- 공통 보조 ----------------
    def agg_df(df, keys):
        r = df.groupby(keys, as_index=False)[[f"wait_seconds_sum{sfx}", f"wait_seconds_count{sfx}",
                                              f"queue_length_sum{sfx}", f"queue_length_count{sfx}"]].sum()
        wc, qc = r[f"wait_seconds_count{sfx}"], r[f"queue_length_count{sfx}"]
        r["wait_min"] = r[f"wait_seconds_sum{sfx}"].div(wc.where(wc > 0)).div(60)
        r["queue"] = r[f"queue_length_sum{sfx}"].div(qc.where(qc > 0))
        return r

    glabel = lambda s: s.astype(str) + "번"
    tag_gate = tags.groupby("departure_gate", as_index=False)["tag_count"].sum()
    tag_gate["출국장"] = glabel(tag_gate["departure_gate"])
    tag_gate["일평균"] = tag_gate["tag_count"] / days_n
    tag_gh = tags.groupby(["hour", "departure_gate"], as_index=False)["tag_count"].sum()
    tag_gh["일평균"] = tag_gh["tag_count"] / days_n
    tag_gh["출국장"] = glabel(tag_gh["departure_gate"])

    def sec_per_pax_section(num):
        """DG 인당 처리 시간(초) — 출국장별·시간대별."""
        _section(f"{num} · DG 인당 처리 시간")
        if dg.empty:
            st.info("선택 범위에 DG 태그가 없습니다.")
            return
        st.caption("인당 처리 시간(초) = 3,600초 ÷ DG 1대의 시간당 처리 인원. 태그가 발생한 시간만 운영 시간으로 봅니다.")
        gsec = dg.groupby("departure_gate", as_index=False).agg(sec=("sec_per_pax", "mean"))
        gsec["출국장"] = glabel(gsec["departure_gate"])
        hs = dg_hour.groupby(["hour", "departure_gate", "dg_id"], as_index=False)["tag_count"].mean()
        hs = hs.groupby(["hour", "departure_gate"], as_index=False)["tag_count"].mean()
        hs["인당 처리 시간(초)"] = 3600 / hs["tag_count"]
        hs["출국장"] = glabel(hs["departure_gate"])
        a, b = st.columns(2)
        with a:
            _sub("출국장별 DG 인당 평균 처리 시간 (초)")
            _show(_bar(gsec, "출국장", "sec", AMBER, 280, "초", "{:.1f}".format), use_container_width=True,
                            key=f"pf_sec_{num}_1")
        with b:
            _sub("DG 장비별 인당 처리 시간 (초)")
            _show(_bar(dg, "label", "sec_per_pax", PINK, 280, "초", "{:.1f}".format), use_container_width=True,
                            key=f"pf_sec_{num}_2")
        _sub("시간대별 DG 인당 처리 시간 (출국장별, 초)")
        _show(_lines(hs, "hour", "인당 처리 시간(초)", "출국장", 300, "초"), use_container_width=True,
                        key=f"pf_sec_{num}_3")

    def gate_count_section(num):
        _section(f"{num} · 출국장별 처리 인원 (DG 진입 태그 기준)")
        if tags.empty:
            st.info("선택 범위에 DG 태그가 없습니다.")
            return
        st.caption(f"출국장별 진입 태그 인원. 일평균 = 기간 합계 ÷ 데이터가 있는 {days_n}일")
        a, b = st.columns(2)
        with a:
            _sub("출국장별 일평균 처리 인원 (명/일)")
            _show(_bar(tag_gate, "출국장", "일평균", INDIGO, 300, "명/일", "{:,.0f}".format),
                            use_container_width=True, key=f"pf_cnt_{num}_1")
        with b:
            _sub("시간대별 출국장 일평균 처리 인원 (명)")
            _show(_lines(tag_gh, "hour", "일평균", "출국장", 300, "명"), use_container_width=True,
                            key=f"pf_cnt_{num}_2")

    def sg_wait_section(num, by_zone_ab=False):
        _section(f"{num} · 출국장별 보안검색(SG) 대기시간 · 대기열")
        if sens.empty:
            st.info("선택 범위에 Xovis 센서 관측이 없습니다.")
            return
        by_gate = agg_df(sens, ["departure_gate"])
        by_gate["출국장"] = glabel(by_gate["departure_gate"])
        hg = agg_df(sens, ["hour", "departure_gate"])
        hg["출국장"] = glabel(hg["departure_gate"])
        if by_zone_ab:
            st.caption("T2는 출국장마다 보안검색 구역 A–D가 있습니다. 구역은 센서 구역명 기준이며 실제 검색대 위치와의 매핑은 미확인입니다.")
            z = sens.assign(구역=sens["sg_zone"].str[-1], 출국장=glabel(sens["departure_gate"]))
            zg = agg_df(z, ["출국장", "구역"])
            c1, c2 = st.columns(2)
            with c1:
                _sub("출국장·구역(A–D)별 평균 대기시간 (분)")
                fig = _bars(go.Figure(), zg, "구역", "wait_min", "출국장", "분", text=True)
                fig.update_layout(**_layout(300, legend=True, barmode="group"))
                fig.update_yaxes(title="분")
                _show(fig, use_container_width=True, key=f"pf_sgw_{num}_1")
            with c2:
                _sub("출국장·구역(A–D)별 평균 대기열 (명)")
                fig = _bars(go.Figure(), zg, "구역", "queue", "출국장", "명", text=True)
                fig.update_layout(**_layout(300, legend=True, barmode="group"))
                fig.update_yaxes(title="명")
                _show(fig, use_container_width=True, key=f"pf_sgw_{num}_2")
            hz = agg_df(sens.assign(구역=sens["sg_zone"]), ["hour", "구역"])
            e1, e2 = st.columns(2)
            with e1:
                _sub("시간대별 대기시간 (구역별, 분)")
                _show(_lines(hz, "hour", "wait_min", "구역", 300, "분"), use_container_width=True, key=f"pf_sgw_{num}_3")
            with e2:
                _sub("시간대별 대기열 (구역별, 명)")
                _show(_lines(hz, "hour", "queue", "구역", 300, "명"), use_container_width=True, key=f"pf_sgw_{num}_4")
        else:
            s1, s2 = st.columns(2)
            with s1:
                _sub("출국장별 평균 보안검색 대기시간 (분)")
                _show(_bar(by_gate, "출국장", "wait_min", ROSE, 280, "분", "{:.1f}".format), use_container_width=True, key=f"pf_sgw_{num}_1")
            with s2:
                _sub("출국장별 평균 보안검색 대기열 (명)")
                _show(_bar(by_gate, "출국장", "queue", VIOLET_, 280, "명", "{:.1f}".format), use_container_width=True, key=f"pf_sgw_{num}_2")
            s3, s4 = st.columns(2)
            with s3:
                _sub("시간대별 보안검색 대기시간 (출국장별, 분)")
                _show(_lines(hg, "hour", "wait_min", "출국장", 300, "분"), use_container_width=True, key=f"pf_sgw_{num}_3")
            with s4:
                _sub("시간대별 보안검색 대기열 (출국장별, 명)")
                _show(_lines(hg, "hour", "queue", "출국장", 300, "명"), use_container_width=True, key=f"pf_sgw_{num}_4")

    # ================= 터미널별 구성 =================
    if terminal == "T1":
        gate_count_section("01")

        # ---- 02 DG 입구 대기 + 인당 처리 시간
        _section("02 · DG 입구 대기시간 · 대기열 (입구 동·서측)")
        ent_path = root / "entrance_wait_hourly.csv"
        ent = pd.DataFrame()
        if ent_path.is_file():
            ent = load_data(str(ent_path), ent_path.stat().st_mtime_ns).copy()
            ent = ent[(ent["date"].dt.month == month) & ent["departure_gate"].isin(chosen_gates)]
            ent = ent[ent["date"].between(pd.Timestamp(period[0]), pd.Timestamp(period[1]))]
        if ent.empty:
            st.info("선택한 월에는 입구(동·서측) 센서 데이터가 없습니다.")
        else:
            st.caption("입구 대기는 Xovis 'Entrance East/West Departure Gates' 구역 값입니다. 보안검색(SG) 대기와 합산하지 않고 따로 봅니다.")
            ent = ent.assign(출국장=glabel(ent["departure_gate"]))
            eg = agg_df(ent, ["출국장", "sg_zone"])
            c1, c2 = st.columns(2)
            with c1:
                _sub("출국장별 입구 대기시간 (분)")
                fig = _bars(go.Figure(), eg.rename(columns={"sg_zone": "위치"}), "출국장", "wait_min", "위치", "분", text=True)
                fig.update_layout(**_layout(300, legend=True, barmode="group"))
                fig.update_yaxes(title="분")
                _show(fig, use_container_width=True, key="pf_ent_1")
            with c2:
                _sub("출국장별 입구 대기열 길이 (명)")
                fig = _bars(go.Figure(), eg.rename(columns={"sg_zone": "위치"}), "출국장", "queue", "위치", "명", text=True)
                fig.update_layout(**_layout(300, legend=True, barmode="group"))
                fig.update_yaxes(title="명")
                _show(fig, use_container_width=True, key="pf_ent_2")
            eh = agg_df(ent, ["hour", "출국장"])
            h1, h2 = st.columns(2)
            with h1:
                _sub("시간대별 입구 대기시간 (출국장별, 분)")
                _show(_lines(eh, "hour", "wait_min", "출국장", 300, "분"), use_container_width=True, key="pf_ent_3")
            with h2:
                _sub("시간대별 입구 대기열 (출국장별, 명)")
                _show(_lines(eh, "hour", "queue", "출국장", 300, "명"), use_container_width=True, key="pf_ent_4")
        sec_per_pax_section("02-2")

        sg_wait_section("03")

        # ---- 04 보안검색대 처리 인원
        _section("04 · 출국장별 · 보안검색대(호기)별 처리 인원")
        st.caption("출국장별 처리 인원은 DG 진입 태그 기준, 센서 통과 카운터(Xovis total)는 2·4·5번 출국장만 제공됩니다. "
                   "호기별 처리 인원은 호기 단위 계측이 없어 '출국장 시간당 태그 인원 ÷ 해당 시간 운영 호기 수'로 추정한 값입니다.")
        cnt_path = root / "sg_count_hourly.csv"
        k1c, k2c = st.columns(2)
        with k1c:
            _sub("출국장별 일평균 처리 인원 — DG 태그 vs 센서 통과 카운터")
            cmp_df = tag_gate[["출국장", "departure_gate", "일평균"]].rename(columns={"일평균": "DG 태그"})
            if cnt_path.is_file():
                cnt = load_data(str(cnt_path), cnt_path.stat().st_mtime_ns).copy()
                cnt = cnt[(cnt["date"].dt.month == month) & cnt["departure_gate"].isin(chosen_gates)]
                cnt = cnt[cnt["date"].between(pd.Timestamp(period[0]), pd.Timestamp(period[1]))]
                cd = cnt.groupby("departure_gate", as_index=False)["pass_count"].sum()
                cd["센서 카운터"] = cd["pass_count"] / max(1, cnt["date"].nunique())
                cmp_df = cmp_df.merge(cd[["departure_gate", "센서 카운터"]], on="departure_gate", how="left")
            else:
                cmp_df["센서 카운터"] = float("nan")
            fig = go.Figure()
            fig.add_bar(x=cmp_df["출국장"], y=cmp_df["DG 태그"], name="DG 태그", marker_color=INDIGO, marker=dict(cornerradius=4))
            fig.add_bar(x=cmp_df["출국장"], y=cmp_df["센서 카운터"], name="센서 통과 카운터", marker_color=EMERALD,
                        marker=dict(cornerradius=4))
            fig.update_layout(**_layout(300, legend=True, barmode="group"))
            fig.update_yaxes(title="명/일")
            _show(fig, use_container_width=True, key="pf_lane_1")
        # 호기별(추정)
        ops_p = root / "operation_snapshots.csv"
        lane_df = pd.DataFrame()
        if ops_p.is_file():
            o = load_data(str(ops_p), ops_p.stat().st_mtime_ns).copy()
            o = o[(o["terminal"] == terminal) & o["departure_gate"].isin(chosen_gates) & o["lanes"].notna()]
            o = o[o["lanes"] <= CAP_LANES.get((terminal, 1), 7)]
            o = o.groupby(["date", "hour", "departure_gate"], as_index=False)["lanes"].mean()
            fl = tags.groupby(["date", "hour", "departure_gate"], as_index=False)["tag_count"].sum()
            lane_df = fl.merge(o, on=["date", "hour", "departure_gate"], how="inner")
            lane_df = lane_df[lane_df["lanes"] > 0]
            lane_df["per_lane"] = lane_df["tag_count"] / lane_df["lanes"]
        with k2c:
            _sub("보안검색대(호기) 1대당 시간당 처리 인원 — 출국장별 (추정)")
            if lane_df.empty:
                st.info("운영 호기 수 데이터와 겹치는 시간이 없습니다. (엑셀 운영 자료는 첨두시간대 기록)")
            else:
                lg = lane_df.groupby("departure_gate", as_index=False)["per_lane"].mean()
                lg["출국장"] = glabel(lg["departure_gate"])
                _show(_bar(lg, "출국장", "per_lane", AMBER, 300, "명/시간·대", "{:,.0f}".format),
                                use_container_width=True, key="pf_lane_2")
        if not lane_df.empty:
            lane_df["호기 수"] = lane_df["lanes"].round().astype(int)
            lane_df["출국장"] = glabel(lane_df["departure_gate"])
            lh = lane_df.groupby(["hour", "출국장"], as_index=False)["per_lane"].mean()
            l1, l2 = st.columns(2)
            with l1:
                _sub("시간대별 호기 1대당 처리 인원 (출국장별, 추정)")
                _show(_lines(lh, "hour", "per_lane", "출국장", 300, "명/시간·대"), use_container_width=True, key="pf_lane_3")
            with l2:
                _sub("운영 호기 수별 호기 1대당 처리 인원 (추정)")
                ln = lane_df.groupby("호기 수", as_index=False).agg(per_lane=("per_lane", "mean"), 건수=("per_lane", "size"))
                ln["호기"] = ln["호기 수"].astype(str) + "대"
                _show(_bar(ln, "호기", "per_lane", CYAN, 300, "명/시간·대", "{:,.0f}".format),
                                use_container_width=True, key="pf_lane_4")
        sec_n = "05"
    else:
        gate_count_section("01")
        sg_wait_section("02", by_zone_ab=True)
        sec_per_pax_section("03")
        sec_n = "04"


    # ================= 04 운영 DG · 보안검색대(호기) 가동률과 대기 =================
    _section(f"{sec_n} · 운영 DG · 보안검색대(호기) 가동률과 대기")
    ops_path = root / "operation_snapshots.csv"
    ops = pd.DataFrame()
    if ops_path.is_file():
        ops = load_data(str(ops_path), ops_path.stat().st_mtime_ns).copy()
        ops = ops[(ops["terminal"] == terminal) & ops["departure_gate"].isin(chosen_gates)]
        ops = ops[ops["date"].between(pd.Timestamp(period[0]), pd.Timestamp(period[1]))]
        ops["cap_l"] = [CAP_LANES.get((terminal, g)) for g in ops["departure_gate"]]
        ops["cap_d"] = [CAP_DG.get((terminal, g)) for g in ops["departure_gate"]]
        ops.loc[ops["lanes"] > ops["cap_l"], "lanes"] = float("nan")      # 보유 대수 초과 입력은 오기로 보고 제외
        ops["lane_ut"] = ops["lanes"] / ops["cap_l"] * 100
    gate_name = lambda g: f"{g}번"

    # ---- 유인 DG 운영 대수 = 시간당 태그가 발생한 유인 DG 장비 수 (T2는 DG 번호가 보유 대수 이하인 장비만 유인으로 봄)
    man = tags_g[tags_g["tag_count"] > 0].copy()
    man["n"] = man["dg_id"].str.extract(r"DG(\d+)$", expand=False).astype(float)
    man["cap_d"] = [CAP_DG.get((terminal, g), 99) for g in man["departure_gate"]]
    man = man[man["n"] <= man["cap_d"]]
    dgn = man.groupby(["date", "hour", "departure_gate"], as_index=False).agg(dg_n=("dg_id", "nunique"), cap_d=("cap_d", "first"), flow=("tag_count", "sum"))
    dgn["DG 가동률(%)"] = dgn["dg_n"] / dgn["cap_d"] * 100
    dgn["출국장"] = dgn["departure_gate"].map(gate_name)

    _sub("시간대별 유인 DG 가동률 (%)")
    if dgn.empty:
        st.info("선택 범위에 DG 태그가 없습니다.")
    else:
        st.caption("가동률 = 시간당 태그가 발생한 유인 DG 장비 수 ÷ 보유 유인 DG 수 (T1 6대 · T2 1번 12대, 2번 8대). 태그가 없는 시간(미운영)은 제외합니다."
                   + (" T2는 DG01–12(1번)·DG01–08(2번)만 유인 장비로 봅니다." if terminal == "T2" else ""))
        dh = dgn.groupby(["hour", "출국장"], as_index=False)["DG 가동률(%)"].mean()
        d1, d2 = st.columns(2)
        with d1:
            _show(_lines(dh, "hour", "DG 가동률(%)", "출국장", 300, "%"), use_container_width=True, key="pf_op_dg1")
        with d2:
            piv = dh.pivot_table(index="출국장", columns="hour", values="DG 가동률(%)").reindex(columns=range(24))
            fig = go.Figure(go.Heatmap(z=piv.values, x=[f"{h}시" for h in piv.columns], y=piv.index.tolist(),
                                       colorscale=HEAT, zmin=0, zmax=100, colorbar=dict(title="%")))
            fig.update_layout(**_layout(70 + 38 * len(piv)))
            fig.update_yaxes(autorange="reversed")
            _show(fig, use_container_width=True, key="pf_op_dg2")

    # ---- 보안검색대(호기) 가동률 통계
    _sub("보안검색대(호기) 가동률 통계")
    if ops.empty or ops["lane_ut"].notna().sum() == 0:
        st.info("선택 범위에 운영 호기 기록이 없습니다. (operation_snapshots.csv는 첨두 시각 위주 기록이며 월·기간에 따라 없을 수 있습니다.)")
    else:
        st.caption("가동률 = 운영 호기 ÷ 보유 호기 (T2 17대, T1 7대 가정). 엑셀 운영 현황(첨두 시각 스냅샷) 기준이라 기록된 시각만 반영하며, 빈 칸(미운영)은 제외합니다.")
        lu = ops.dropna(subset=["lane_ut"]).copy()
        lu["출국장"] = lu["departure_gate"].map(gate_name)
        rows = []
        for gname, s_ in lu.groupby("출국장"):
            by_slot = s_.groupby("slot")["lane_ut"].mean()
            rows.append({"출국장": gname, "보유 호기": int(s_["cap_l"].iloc[0]), "관측 수": len(s_),
                         "평균 운영 호기(대)": s_["lanes"].mean(), "평균 가동률(%)": s_["lane_ut"].mean(),
                         "가동률 중앙값(%)": s_["lane_ut"].median(),
                         "최대 가동률(%)": s_["lane_ut"].max(),
                         "첨두 시각": by_slot.idxmax(), "첨두 평균(%)": by_slot.max(),
                         "80% 이상(%)": (s_["lane_ut"] >= 80).mean() * 100})
        lt = pd.DataFrame(rows)
        st.dataframe(lt.round(1), hide_index=True, use_container_width=True)
        l1, l2 = st.columns(2)
        with l1:
            st.markdown("**시각별 평균 가동률 (%)**")
            sl = lu.groupby(["slot", "출국장"], as_index=False)["lane_ut"].mean()
            fig = _line_fig(go.Figure(), sl, "slot", "lane_ut", "출국장", "%", size=12)
            fig.update_layout(**_layout(300, legend=True), hovermode="x unified")
            fig.update_xaxes(type="category", title="시각", categoryorder="array", categoryarray=sorted(sl["slot"].unique()))
            fig.update_yaxes(title="%", range=[0, 100])
            _show(fig, use_container_width=True, key="pf_op_ln1")
        with l2:
            st.markdown("**운영 호기 수 분포 (관측 비율 %)**")
            cnt = lu.groupby(["출국장", "lanes"]).size().rename("n").reset_index()
            cnt["비율"] = cnt["n"] / cnt.groupby("출국장")["n"].transform("sum") * 100
            fig = go.Figure()
            for i, (nm, g_) in enumerate(cnt.groupby("출국장")):
                fig.add_bar(x=g_["lanes"].astype(int), y=g_["비율"], name=nm, marker_color=PALETTE[i % len(PALETTE)])
            fig.update_layout(**_layout(300, legend=True, barmode="group"))
            fig.update_xaxes(title="운영 호기 수(대)", dtick=1)
            fig.update_yaxes(title="%")
            _show(fig, use_container_width=True, key="pf_op_ln2")

    # ---- 운영 DG 수 · 운영 호기 수별 대기시간 · 대기 인원
    _sub("운영 DG 수 · 운영 보안검색대(호기) 수별 대기시간 · 대기 인원")
    if sens.empty:
        st.info("선택 범위에 Xovis 센서 관측이 없어 대기시간·대기 인원을 계산할 수 없습니다.")
    else:
        st.caption("같은 날짜·시간·출국장의 센서 대기시간·대기열 평균을 운영 대수별로 묶어 평균했습니다. "
                   "관측이 5건 미만인 구간은 제외합니다. 운영 대수가 많은 시간은 승객도 많아 단순 평균은 왜곡되므로 1대당 값과 처리 인원 구간별 값으로 봅니다."
                   + (" T2는 센서 값이 기간별로 크게 달라(3–6월 대기열 0, 9–10월 급증) 월을 나누어 보세요." if terminal == "T2" else ""))
        gh = sg_agg(["date", "hour", "departure_gate"])[["date", "hour", "departure_gate", "wait_min", "queue"]]

        # 1대당 지표: 분당 처리 인원 = 시간당 태그 ÷ 60 ÷ 운영 대수, 대기 인원 = 센서 대기열 ÷ 운영 대수
        def by_count(df, col):
            j = df.merge(gh, on=["date", "hour", "departure_gate"], how="inner").dropna(subset=[col, "flow"])
            j = j[j[col] > 0].copy()
            j["flow_dev"] = j["flow"] / 60 / j[col]
            j["queue_dev"] = j["queue"] / j[col]
            j["wait_per_dev"] = j["wait_min"] / j[col]
            j["출국장"] = j["departure_gate"].map(gate_name)
            r = j.groupby(["출국장", col], as_index=False).agg(
                n=("wait_min", "size"), wait_min=("wait_min", "mean"), queue=("queue", "mean"),
                flow_dev=("flow_dev", "mean"), queue_dev=("queue_dev", "mean"), wait_per_dev=("wait_per_dev", "mean"))
            return j, r[r["n"] >= 5]

        def draw(r, x, ycol, xtitle, ytitle, key, height=300, order=None, kind="bar"):
            if kind == "line":
                fig = _line_fig(go.Figure(), r, x, ycol, "출국장", order=order, size=13)
                fig.update_layout(**_layout(height, legend=True), hovermode="x unified")
            else:
                fig = _bars(go.Figure(), r, x, ycol, "출국장", order=order)
                fig.update_layout(**_layout(height, legend=True, barmode="group"), hovermode="x unified", bargap=0.2)
            if order:
                fig.update_xaxes(type="category", categoryorder="array", categoryarray=list(order), title=xtitle)
            else:
                fig.update_xaxes(title=xtitle, dtick=1)
            fig.update_yaxes(title=ytitle, rangemode="tozero")
            _show(fig, use_container_width=True, key=key)

        def block(title, j, r, col, unit, key):
            st.markdown(f"**{title}**")
            if r.empty:
                st.info("비교할 관측이 부족합니다.")
                return
            c1, c2 = st.columns(2)
            with c1:
                st.caption(f"운영 {unit} 수별 · 1대당 분당 처리 인원 (명/분·대)")
                draw(r, col, "flow_dev", f"운영 {unit} 수(대)", "명/분·대", key + "a")
            with c2:
                st.caption(f"운영 {unit} 수별 · 1대당 대기 인원 (명/대)")
                draw(r, col, "queue_dev", f"운영 {unit} 수(대)", "명/대", key + "b", kind="line")

        dgn_f = dgn.rename(columns={"dg_n": "운영 DG"})
        j1, r1 = by_count(dgn_f[["date", "hour", "departure_gate", "운영 DG", "flow"]], "운영 DG")
        block("운영 유인 DG 수별 (대시보드 태그 기준)", j1, r1, "운영 DG", "DG", "pf_op_d")
        if ops.empty:
            lane_j, lane_r = pd.DataFrame(), pd.DataFrame()
            st.markdown("**운영 보안검색대(호기) 수별 (엑셀 운영 현황 기준)**")
            st.info("비교할 관측이 부족합니다.")
        else:
            gate_flow = tags_g.groupby(["date", "hour", "departure_gate"], as_index=False)["tag_count"].sum().rename(columns={"tag_count": "flow"})
            lo = ops[["date", "hour", "departure_gate", "lanes"]].rename(columns={"lanes": "운영 호기"}).merge(
                gate_flow, on=["date", "hour", "departure_gate"], how="left")
            lane_j, lane_r = by_count(lo, "운영 호기")
            block("운영 보안검색대(호기) 수별 (엑셀 운영 현황 기준 · 처리 인원은 출국장 전체 DG 태그)", lane_j, lane_r, "운영 호기", "호기", "pf_op_l")
        if True:
            st.markdown("**운영 대수별 상세표**")
            tabs = []
            for nm, r_, c_ in (("운영 DG", r1, "운영 DG"), ("운영 호기", lane_r, "운영 호기")):
                if len(r_):
                    tabs.append(r_.assign(구분=nm).rename(columns={
                        c_: "운영 대수", "n": "관측 수(시간)", "wait_min": "평균 대기시간(분)", "queue": "평균 대기열(명)",
                        "flow_dev": "1대당 분당 처리 인원(명)", "queue_dev": "1대당 대기 인원(명)", "wait_per_dev": "대기시간÷대수(분/대)"})
                        [["구분", "출국장", "운영 대수", "관측 수(시간)", "평균 대기시간(분)", "평균 대기열(명)",
                          "1대당 분당 처리 인원(명)", "1대당 대기 인원(명)", "대기시간÷대수(분/대)"]])
            if tabs:
                tt = pd.concat(tabs)
                st.dataframe(tt.round(2), hide_index=True, use_container_width=True, height=340)  # 표 안에서 아래로 스크롤
                st.download_button("운영 대수별 대기 다운로드", tt.round(3).to_csv(index=False).encode("utf-8-sig"), "operation_wait_queue.csv")


if __name__ == "__main__":
    st.set_page_config(page_title="출국장 여객흐름", layout="wide")
    st.markdown("""<style>.block-container{padding-top:2rem}
    div[data-testid="stMetric"]{background:#f7f7f5;border-radius:10px;padding:14px 16px}
    .section-label{font-size:12px;letter-spacing:.06em;color:#898781;margin:1.5rem 0 .5rem}</style>""",
                unsafe_allow_html=True)
    render_passenger_flow()
