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
    k1.metric("처리 인원(진입 태그)", f"{total:,}명")
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

    # ================= 01 SG =================
    _section("01 · 보안검색 구역(SG) 대기시간 · 대기열 (출국장별)")
    if sens.empty:
        st.info("선택 범위에 Xovis 센서 관측이 없습니다.")
    else:
        if terminal == "T2":
            st.caption("T2는 출국장마다 보안검색 구역(SG) A–D 4개가 있습니다. 출국장 단위 값은 선택한 구역의 평균이며, "
                       "아래 '보안검색 구역(A–D)별' 차트에서 구역별로 볼 수 있습니다.")
        by_gate = sg_agg(["departure_gate"]).assign(gate_label=lambda x: x["departure_gate"].astype(str) + "번")
        by_zone = sg_agg(["구역"])
        s1, s2 = st.columns(2)
        with s1:
            st.subheader("출국장별 평균 대기시간 (분)")
            st.plotly_chart(_bar(by_gate, "gate_label", "wait_min", RED, 260, "분", "{:.1f}".format), use_container_width=True)
        with s2:
            st.subheader("출국장별 평균 대기열 (명)")
            st.plotly_chart(_bar(by_gate, "gate_label", "queue", VIOLET, 260, "명", "{:.1f}".format), use_container_width=True)

        if terminal == "T2":
            zone_df = sens.assign(구역코드=sens["sg_zone"]).copy()
            zr = zone_df.groupby("구역코드", as_index=False)[[f"wait_seconds_sum{sfx}", f"wait_seconds_count{sfx}",
                                                           f"queue_length_sum{sfx}", f"queue_length_count{sfx}"]].sum()
            zr["wait_min"] = zr[f"wait_seconds_sum{sfx}"].div(zr[f"wait_seconds_count{sfx}"].where(zr[f"wait_seconds_count{sfx}"] > 0)) / 60
            zr["queue"] = zr[f"queue_length_sum{sfx}"].div(zr[f"queue_length_count{sfx}"].where(zr[f"queue_length_count{sfx}"] > 0))
            z1, z2 = st.columns(2)
            with z1:
                st.subheader("보안검색 구역(A–D)별 평균 대기시간 (분)")
                st.plotly_chart(_bar(zr, "구역코드", "wait_min", RED, 260, "분", "{:.1f}".format), use_container_width=True, key="pf_t2z_1")
            with z2:
                st.subheader("보안검색 구역(A–D)별 평균 대기열 (명)")
                st.plotly_chart(_bar(zr, "구역코드", "queue", VIOLET, 260, "명", "{:.1f}".format), use_container_width=True, key="pf_t2z_2")

        hour_gate = sg_agg(["hour", "departure_gate"]).assign(출국장=lambda x: x["departure_gate"].astype(str) + "번")
        s3, s4 = st.columns(2)
        with s3:
            st.subheader("시간대별 대기시간 (출국장별, 분)")
            st.plotly_chart(_lines(hour_gate, "hour", "wait_min", "출국장", 300, "분"), use_container_width=True)
        with s4:
            st.subheader("시간대별 대기열 (출국장별, 명)")
            st.plotly_chart(_lines(hour_gate, "hour", "queue", "출국장", 300, "명"), use_container_width=True)

        st.subheader("출국장 × 시간대 평균 대기열 (명)")
        piv = hour_gate.pivot_table(index="출국장", columns="hour", values="queue").reindex(columns=range(24))
        fig = go.Figure(go.Heatmap(z=piv.values, x=[f"{h}시" for h in piv.columns], y=piv.index.tolist(),
                                   colorscale=HEAT, colorbar=dict(title="명")))
        fig.update_layout(**_layout(70 + 38 * len(piv)))
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)

        with st.expander("보안검색 구역(SG)별 상세표"):
            zt = by_zone[["구역", "wait_min", "queue"]].rename(columns={"wait_min": "대기 시간(분)", "queue": "평균 대기열(명)"})
            st.dataframe(zt.round(2), hide_index=True, use_container_width=True)
            st.download_button("보안검색 구역(SG)별 대기·대기열 다운로드", zt.round(3).to_csv(index=False).encode("utf-8-sig"),
                               "sg_wait_queue.csv")

    # ================= 02 DG =================
    _section("02 · DG 장비별 처리 인원 · 분당 처리 인원 · 인당 처리 시간")
    if dg.empty:
        st.info("선택 범위에 DG 태그가 없습니다.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("DG별 처리 인원")
            fig = go.Figure(go.Bar(x=dg["label"], y=dg["total"], marker=dict(cornerradius=4),
                                   marker_color=[PALETTE[(g - 1) % len(PALETTE)] for g in dg["departure_gate"]],
                                   text=dg["total"].map("{:,}".format), textposition="outside"))
            fig.update_layout(**_layout(300))
            fig.update_yaxes(title="처리 인원(명)")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            st.subheader("DG별 분당 처리 인원 (명/분)")
            st.caption("시간당 처리 인원 ÷ 60 — 태그가 발생한 시간만 운영 시간으로 계산")
            st.plotly_chart(_bar(dg, "label", "per_min", AQUA, 280, "명/분", "{:.2f}".format), use_container_width=True)

        st.subheader("시간대별 DG 분당 처리 인원")
        hr = dg_hour.groupby(["hour", "dg_id"], as_index=False)["tag_count"].mean()
        hr["per_min"] = hr["tag_count"] / 60
        hr["DG"] = hr["dg_id"].str.extract(r"(D\d{3}DG\d+)", expand=False).fillna(hr["dg_id"])
        st.plotly_chart(_lines(hr, "hour", "per_min", "DG", 300, "명/분"), use_container_width=True)

        with st.expander("DG별 상세표"):
            show = dg[["gate_label", "label", "total", "active_hours", "per_hour", "per_min", "sec_per_pax"]].rename(
                columns={"gate_label": "출국장", "label": "DG 장비", "total": "처리 인원", "active_hours": "운영 시간(h)",
                         "per_hour": "시간당 처리 인원", "per_min": "분당 처리 인원", "sec_per_pax": "인당 처리 시간(초)"})
            st.dataframe(show.round(2), hide_index=True, use_container_width=True)
            st.download_button("DG 상세표 다운로드", show.round(3).to_csv(index=False).encode("utf-8-sig"),
                               "dg_throughput_summary.csv")

    # ================= 03 SG 처리 인원 =================
    _section("03 · 출국장별 처리 인원 (DG 태그 기준) × 보안검색 구역(SG) 대기")
    if sens.empty or tags.empty:
        st.info("SG 대기 관측 또는 DG 태그가 없어 출국장별 처리 인원과 대기시간을 함께 볼 수 없습니다.")
    else:
        gate_tag = tags.groupby("departure_gate", as_index=False)["tag_count"].sum()
        gate_tag["출국장"] = gate_tag["departure_gate"].astype(str) + "번"
        gate_wait = sg_agg(["departure_gate"])[["departure_gate", "wait_min", "queue"]]
        gate_tag = gate_tag.merge(gate_wait, on="departure_gate", how="left")
        p1, p2 = st.columns(2)
        with p1:
            st.subheader("출국장별 처리 인원 — DG 진입 태그 기준")
            st.plotly_chart(_bar(gate_tag, "출국장", "tag_count", BLUE, 280, "명", "{:,}".format),
                            use_container_width=True, key="pf_sgp_1")
        with p2:
            st.subheader("처리 인원 대비 평균 대기시간")
            st.caption("막대=처리 인원, 선=평균 대기시간(분)")
            fig = go.Figure()
            fig.add_bar(x=gate_tag["출국장"], y=gate_tag["tag_count"], name="처리 인원(명)",
                        marker_color=BLUE, marker=dict(cornerradius=4))
            fig.add_trace(go.Scatter(x=gate_tag["출국장"], y=gate_tag["wait_min"], name="평균 대기(분)",
                                     mode="lines+markers", line=dict(color=RED, width=3.5, shape="spline", smoothing=0.5),
                                     marker=dict(size=12, color=RED, line=dict(color="white", width=2)), yaxis="y2"))
            fig.update_layout(**_layout(260, legend=True), yaxis2=dict(overlaying="y", side="right", showgrid=False, title="분"))
            st.plotly_chart(fig, use_container_width=True, key="pf_sgp_2")
        # ---- 승객 기준 평균 대기시간: 태그가 찍힌 시간대·출국장의 SG 평균 대기시간을 태그 인원으로 가중 ----
        st.subheader("출국장별 승객 기준 평균 대기시간")
        pw = tags.groupby(["date", "hour", "departure_gate"], as_index=False)["tag_count"].sum().merge(
            sg_agg(["date", "hour", "departure_gate"])[["date", "hour", "departure_gate", "wait_min"]],
            on=["date", "hour", "departure_gate"], how="left")
        pw["matched"] = pw["wait_min"].notna()
        pw["w"] = pw["tag_count"] * pw["wait_min"].fillna(0)
        pw["m_tag"] = pw["tag_count"].where(pw["matched"], 0)
        pg = pw.groupby("departure_gate", as_index=False)[["tag_count", "m_tag", "w"]].sum()
        pg["승객 기준 평균 대기(분)"] = pg["w"].div(pg["m_tag"].where(pg["m_tag"] > 0))
        pg["반영 비율(%)"] = pg["m_tag"].div(pg["tag_count"].where(pg["tag_count"] > 0)) * 100
        pg = pg.merge(gate_wait[["departure_gate", "wait_min"]].rename(columns={"wait_min": "센서 단순 평균 대기(분)"}),
                      on="departure_gate", how="left")
        pg["출국장"] = pg["departure_gate"].astype(str) + "번"
        q1, q2 = st.columns(2)
        with q1:
            fig = go.Figure()
            fig.add_bar(x=pg["출국장"], y=pg["센서 단순 평균 대기(분)"], name="센서 단순 평균", marker_color=GRAY,
                        marker=dict(cornerradius=4), text=pg["센서 단순 평균 대기(분)"].map("{:.1f}".format), textposition="outside")
            fig.add_bar(x=pg["출국장"], y=pg["승객 기준 평균 대기(분)"], name="승객 기준(태그 가중)", marker_color=RED,
                        marker=dict(cornerradius=4), text=pg["승객 기준 평균 대기(분)"].map("{:.1f}".format), textposition="outside")
            fig.update_layout(**_layout(280, legend=True, barmode="group"))
            fig.update_yaxes(title="분")
            st.plotly_chart(fig, use_container_width=True, key="pf_pw_1")
        with q2:
            ph = pw.dropna(subset=["wait_min"]).groupby(["hour", "departure_gate"], as_index=False)[["tag_count", "w"]].sum()
            ph["승객 기준 대기(분)"] = ph["w"] / ph["tag_count"].where(ph["tag_count"] > 0)
            ph["출국장"] = ph["departure_gate"].astype(str) + "번"
            st.plotly_chart(_lines(ph, "hour", "승객 기준 대기(분)", "출국장", 280, "분"),
                            use_container_width=True, key="pf_pw_2")
        st.dataframe(pg[["출국장", "tag_count", "센서 단순 평균 대기(분)", "승객 기준 평균 대기(분)", "반영 비율(%)"]]
                     .rename(columns={"tag_count": "처리 인원(명)"}).round(2), hide_index=True, use_container_width=True)
        st.caption("\\* 승객 기준(태그 가중): 승객이 많았던 시간대의 대기시간에 더 큰 비중을 두어 계산한 평균입니다.")

        tag_gh = tags.groupby(["hour", "departure_gate"], as_index=False)["tag_count"].sum().assign(
            출국장=lambda x: x["departure_gate"].astype(str) + "번")
        st.subheader("시간대별 출국장 처리 인원 (태그 기준)")
        st.plotly_chart(_lines(tag_gh, "hour", "tag_count", "출국장", 300, "명"),
                        use_container_width=True, key="pf_sgp_3")

        th = tags.groupby(["hour", "departure_gate"], as_index=False)["tag_count"].sum()

        with st.expander("참고: Little's Law 추정 처리 인원 (신뢰도 낮음)"):
            st.caption("시간별 평균 대기열 ÷ 평균 대기시간(시간). 대기가 1분 미만인 시간은 값이 폭주하므로 제외했습니다. "
                       "센서 대기열 길이와 DG 태그의 측정 범위가 달라 태그 인원과 크게 어긋날 수 있어 비교용으로만 보세요.")
            zh = sens.groupby(["hour", "departure_gate"], as_index=False)[
                [f"wait_seconds_sum{sfx}", f"wait_seconds_count{sfx}", f"queue_length_sum{sfx}", f"queue_length_count{sfx}"]].sum()
            wc, qc = zh[f"wait_seconds_count{sfx}"], zh[f"queue_length_count{sfx}"]
            zh["wait_h"] = zh[f"wait_seconds_sum{sfx}"].div(wc.where(wc > 0)) / 3600
            zh["queue"] = zh[f"queue_length_sum{sfx}"].div(qc.where(qc > 0))
            zh = zh[(zh["wait_h"] >= 1 / 60) & (zh["queue"] > 0)]
            zh["est_per_hour"] = zh["queue"] / zh["wait_h"]
            n_days = max(1, (pd.Timestamp(period[1]) - pd.Timestamp(period[0])).days + 1)
            est = zh.groupby("departure_gate", as_index=False)["est_per_hour"].mean()
            est["추정 처리 인원(시간평균, 명/시간)"] = est["est_per_hour"]
            tg = th.groupby("departure_gate", as_index=False)["tag_count"].sum()
            tg["태그 처리 인원(시간평균, 명/시간)"] = tg["tag_count"] / (n_days * 24)
            cmp_ = est.merge(tg, on="departure_gate", how="outer").rename(columns={"departure_gate": "출국장"})
            st.dataframe(cmp_[["출국장", "추정 처리 인원(시간평균, 명/시간)", "태그 처리 인원(시간평균, 명/시간)"]].round(1),
                         hide_index=True, use_container_width=True)


    # ================= 04 운영 DG · 보안검색대(호기) 가동률과 대기 =================
    _section("04 · 운영 DG · 보안검색대(호기) 가동률과 대기")
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

    st.subheader("시간대별 유인 DG 가동률 (%)")
    if dgn.empty:
        st.info("선택 범위에 DG 태그가 없습니다.")
    else:
        st.caption("가동률 = 시간당 태그가 발생한 유인 DG 장비 수 ÷ 보유 유인 DG 수 (T1 6대 · T2 1번 12대, 2번 8대). 태그가 없는 시간(미운영)은 제외합니다."
                   + (" T2는 DG01–12(1번)·DG01–08(2번)만 유인 장비로 봅니다." if terminal == "T2" else ""))
        dh = dgn.groupby(["hour", "출국장"], as_index=False)["DG 가동률(%)"].mean()
        d1, d2 = st.columns(2)
        with d1:
            st.plotly_chart(_lines(dh, "hour", "DG 가동률(%)", "출국장", 300, "%"), use_container_width=True, key="pf_op_dg1")
        with d2:
            piv = dh.pivot_table(index="출국장", columns="hour", values="DG 가동률(%)").reindex(columns=range(24))
            fig = go.Figure(go.Heatmap(z=piv.values, x=[f"{h}시" for h in piv.columns], y=piv.index.tolist(),
                                       colorscale=HEAT, zmin=0, zmax=100, colorbar=dict(title="%")))
            fig.update_layout(**_layout(70 + 38 * len(piv)))
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True, key="pf_op_dg2")

    # ---- 보안검색대(호기) 가동률 통계
    st.subheader("보안검색대(호기) 가동률 통계")
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
            st.plotly_chart(fig, use_container_width=True, key="pf_op_ln1")
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
            st.plotly_chart(fig, use_container_width=True, key="pf_op_ln2")

    # ---- 운영 DG 수 · 운영 호기 수별 대기시간 · 대기 인원
    st.subheader("운영 DG 수 · 운영 보안검색대(호기) 수별 대기시간 · 대기 인원")
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
            st.plotly_chart(fig, use_container_width=True, key=key)

        def block(title, j, r, col, unit, key):
            st.markdown(f"**{title}**")
            if r.empty:
                st.info("비교할 관측이 부족합니다.")
                return
            c1, c2, c3 = st.columns(3)
            with c1:
                st.caption(f"운영 {unit} 수별 · 1대당 분당 처리 인원 (명/분·대)")
                draw(r, col, "flow_dev", f"운영 {unit} 수(대)", "명/분·대", key + "a")
            with c2:
                st.caption(f"운영 {unit} 수별 · 1대당 대기 인원 (명/대)")
                draw(r, col, "queue_dev", f"운영 {unit} 수(대)", "명/대", key + "b", kind="line")
            with c3:
                st.caption(f"1대당 분당 처리 인원 구간별 · 평균 대기시간 (분)")
                jj = j.copy()
                names = ["1 (낮음)", "2", "3", "4", "5 (높음)"]
                try:
                    q_ = pd.qcut(jj["flow_dev"], 5, labels=False, duplicates="drop")
                    jj["구간"] = q_.map(lambda k: names[int(k)])
                except ValueError:
                    jj["구간"] = "1 (낮음)"
                rb = jj.groupby(["출국장", "구간"], observed=True).agg(
                    n=("wait_min", "size"), x=("flow_dev", "mean"), wait_min=("wait_min", "mean")).reset_index()
                rb = rb[rb["n"] >= 5]
                if rb.empty:
                    st.info("관측 부족")
                else:
                    draw(rb, "구간", "wait_min", "1대당 분당 처리 인원 5분위 (낮음→높음)", "평균 대기시간(분)", key + "c", order=names)

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
