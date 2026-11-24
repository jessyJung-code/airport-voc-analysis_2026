"""DG throughput and SG sensor observations in the passenger-flow page."""
from pathlib import Path
import pandas as pd
import streamlit as st


@st.cache_data
def load_data(path, modified):
    return pd.read_csv(path, parse_dates=["date"])


def render_passenger_flow():
    st.title("출국장 여객흐름 분석")
    root = Path(__file__).parent / "passenger_flow_data"
    paths = [root / "dg_tags_hourly.csv", root / "sg_wait_hourly.csv"]
    if not all(p.is_file() for p in paths):
        st.info("DG 처리 인원·SG 대기 집계 파일을 준비해 주세요.")
        return
    tags, sensors = [load_data(str(p), p.stat().st_mtime_ns).copy() for p in paths]
    months = sorted(set(tags["date"].dt.strftime("%Y-%m")) | set(sensors["date"].dt.strftime("%Y-%m")))
    month = st.sidebar.selectbox("분석 월", months, key="passenger_month")
    terminal = st.sidebar.radio("터미널", ["T1", "T2"], key="passenger_terminal")
    tags = tags[tags["date"].dt.strftime("%Y-%m").eq(month) & tags["terminal"].eq(terminal)]
    sensors = sensors[sensors["date"].dt.strftime("%Y-%m").eq(month) & sensors["terminal"].eq(terminal)]
    dates = sorted(set(tags["date"].dt.date) | set(sensors["date"].dt.date))
    if not dates:
        st.info("선택한 기간의 데이터가 없습니다.")
        return
    period = st.sidebar.date_input("날짜 범위", (dates[0], dates[-1]),
                                   min_value=dates[0], max_value=dates[-1], key="passenger_dates")
    if len(period) != 2:
        st.info("시작일과 종료일을 선택하세요.")
        return
    tags = tags[tags["date"].between(pd.Timestamp(period[0]), pd.Timestamp(period[1]))]
    sensors = sensors[sensors["date"].between(pd.Timestamp(period[0]), pd.Timestamp(period[1]))]
    gates = sorted(set(tags["departure_gate"]) | set(sensors["departure_gate"]))
    chosen = st.sidebar.multiselect("출국장", gates, default=gates, key="passenger_gates")
    tags = tags[tags["departure_gate"].isin(chosen)]
    sensors = sensors[sensors["departure_gate"].isin(chosen)]
    trim = st.sidebar.checkbox("P95 초과 대기·대기열 관측 제외", True, key="passenger_trim")
    daily = st.sidebar.checkbox("날짜별 시간대 표시", False, key="passenger_daily")
    keys = ["date", "hour"] if daily else ["hour"]
    caption = f"{month} · {terminal} · {period[0]} ~ {period[1]}"
    st.caption(caption)
    if st.session_state.get("developer_authenticated", False):
        st.caption("DG 인원은 진입시분 기준 최초 태그입니다. SG 대기와 대기열 길이는 센서 관측 평균이며, 태그 인원으로 가중하지 않습니다. P95는 월·출국장·센서 구역별로 계산합니다.")
    dg_tab, sg_tab = st.tabs(["DG별 처리 인원", "SG별 대기 시간·대기열"])
    with dg_tab:
        if tags.empty:
            st.info("선택 범위에 DG 태그가 없습니다.")
        else:
            devices = st.multiselect("DG 장비", sorted(tags["dg_id"].unique()),
                                     default=sorted(tags["dg_id"].unique()), key="passenger_devices")
            selected = tags[tags["dg_id"].isin(devices)]
            result = selected.groupby(keys + ["departure_gate", "dg_id"], as_index=False)["tag_count"].sum()
            st.metric("처리 인원(진입 태그)", f'{selected["tag_count"].sum():,}명')
            chart_x = "hour"
            if daily:
                result["시각"] = result["date"] + pd.to_timedelta(result["hour"], unit="h")
                chart_x = "시각"
            st.bar_chart(result, x=chart_x, y="tag_count", color="dg_id")
            display = result.rename(columns={"date": "날짜", "hour": "시간", "departure_gate": "출국장",
                                             "dg_id": "DG 장비", "tag_count": "처리 인원"})
            st.dataframe(display, hide_index=True)
            st.download_button("DG 시간별 처리 인원 다운로드", display.to_csv(index=False).encode("utf-8-sig"),
                               "dg_tag_throughput.csv")
    with sg_tab:
        if sensors.empty:
            st.info("선택 범위에 Xovis 센서 관측이 없습니다.")
        else:
            if terminal == "T2":
                st.warning("T2는 원본 A~D 구역명을 표시합니다. SG 위치 대응은 확인이 필요합니다.")
            sensors["구역"] = sensors["departure_gate"].astype(str) + "번 / " + sensors["sg_zone"]
            zones = st.multiselect("센서 구역", sorted(sensors["구역"].unique()),
                                   default=sorted(sensors["구역"].unique()), key="passenger_zones")
            selected = sensors[sensors["구역"].isin(zones)]
            suffix = "_p95" if trim else ""
            metrics = [f"{metric}_{ending}{suffix}" for metric in ("wait_seconds", "queue_length")
                       for ending in ("sum", "count")]
            result = selected.groupby(keys + ["구역"], as_index=False)[metrics].sum()
            for metric, label, scale in (("wait_seconds", "대기 시간(분)", 60), ("queue_length", "평균 대기열(명)", 1)):
                count = result[f"{metric}_count{suffix}"]
                result[label] = result[f"{metric}_sum{suffix}"].div(count.where(count > 0)).div(scale)
            chart_x = "hour"
            if daily:
                result["시각"] = result["date"] + pd.to_timedelta(result["hour"], unit="h")
                chart_x = "시각"
            st.line_chart(result, x=chart_x, y="대기 시간(분)", color="구역")
            st.line_chart(result, x=chart_x, y="평균 대기열(명)", color="구역")
            display = result.drop(columns=metrics).rename(columns={"date": "날짜", "hour": "시간"})
            st.dataframe(display, hide_index=True)
            st.download_button("SG 시간별 대기·대기열 다운로드", display.to_csv(index=False).encode("utf-8-sig"),
                               "sg_wait_queue.csv")


if __name__ == "__main__":
    render_passenger_flow()
