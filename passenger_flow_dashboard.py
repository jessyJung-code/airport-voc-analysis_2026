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
"""
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
MAGENTA, VIOLET, RED, GRAY = "#e87ba4", "#4a3aa7", "#e34948", "#898781"
GRID, TEXT_SECONDARY = "#e1e0d9", "#52514e"
PALETTE = [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, VIOLET, RED, GRAY]
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


def _lines(df, x, y, group, height=280, title_y=None):
    fig = go.Figure()
    for i, (name, g) in enumerate(df.groupby(group)):
        g = g.sort_values(x)
        fig.add_trace(go.Scatter(x=g[x], y=g[y], mode="lines+markers", name=str(name),
                                 line=dict(color=PALETTE[i % len(PALETTE)], width=2), marker=dict(size=4)))
    fig.update_layout(**_layout(height, legend=True))
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
                                   colorscale="Purples", colorbar=dict(title="명")))
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
    st.caption("보안검색 구역(SG) 센서는 인원을 직접 세지 않으므로, 처리 인원은 해당 출국장의 DG 진입 태그 합계를 사용하고 같은 출국장의 SG 대기시간과 함께 봅니다. "
               "T2는 출국장마다 보안검색 구역이 A–D 4개이고 DG 태그는 구역 구분이 없어, 처리 인원은 출국장 단위로만 표시합니다.")
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
                                     mode="lines+markers", line=dict(color=RED, width=2), yaxis="y2"))
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


if __name__ == "__main__":
    st.set_page_config(page_title="출국장 여객흐름", layout="wide")
    st.markdown("""<style>.block-container{padding-top:2rem}
    div[data-testid="stMetric"]{background:#f7f7f5;border-radius:10px;padding:14px 16px}
    .section-label{font-size:12px;letter-spacing:.06em;color:#898781;margin:1.5rem 0 .5rem}</style>""",
                unsafe_allow_html=True)
    render_passenger_flow()
