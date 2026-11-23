"""Streamlit panel for entrance and security stage aggregates."""
from pathlib import Path
import pandas as pd
import streamlit as st


def render_dg_sg():
    st.title("DG·SG 시간별 여객 흐름")
    path = Path(__file__).parent / "airport_dg_sg_monthly" / "airport_dg_sg_hourly.csv"
    if not path.exists():
        st.info("DG·SG 집계 CSV가 필요합니다.")
        return
    data = pd.read_csv(path)
    data["month"] = data["date"].str[:7]
    month = st.selectbox("분석 월", sorted(data["month"].unique()))
    terminal = st.radio("터미널", ["T1", "T2"], horizontal=True)
    data = data[(data["month"] == month) & (data["terminal"] == terminal)]
    if data.empty:
        st.info("선택한 월·터미널의 센서 관측이 없습니다.")
        return
    if terminal == "T2":
        st.warning("T2 A~D 구역은 DG·SG 대응 관계 확인이 필요합니다.")
    if not data["throughput_count"].sum():
        st.warning("선택 기간의 진입 태그 집계가 비어 있어 처리 인원 가중 대기를 계산할 수 없습니다.")
    if not data["sensor_count"].sum():
        st.warning("선택 기간의 Xovis 대기 관측이 없습니다. 처리 인원만 표시합니다.")
    stage = st.selectbox("구간", sorted(data["stage"].unique()))
    data = data[data["stage"] == stage]
    gates = st.multiselect("출국장", sorted(data["departure_gate"].unique()),
                           default=sorted(data["departure_gate"].unique()))
    data = data[data["departure_gate"].isin(gates)]
    by_date = st.checkbox("날짜별 시간대 표시", value=False)
    trim = st.checkbox("출국장·구간별 P95 초과 관측 제외", value=True)
    suffix = "_p95" if trim else ""
    keys = ["date", "hour", "departure_gate"] if by_date else ["hour", "departure_gate"]
    result = data.groupby(keys, as_index=False).agg(
        throughput=("throughput_count", "sum"),
        matched=(f"matched_throughput{suffix}", "sum"),
        weighted=(f"weighted_wait_minutes{suffix}", "sum"),
    )
    result["대기 시간(분)"] = result["weighted"].div(result["matched"].where(result["matched"] > 0))
    result = result.rename(columns={"hour": "시간", "departure_gate": "출국장",
                                    "throughput": "처리 인원", "matched": "대기 산출 반영 인원"})
    result["출국장"] = result["출국장"].astype(str) + "번"
    x = "시간"
    if by_date:
        result["시각"] = pd.to_datetime(result["date"]) + pd.to_timedelta(result["시간"], unit="h")
        x = "시각"
    if st.session_state.get("developer_authenticated", False):
        st.caption("처리 인원은 같은 시간대 DG 진입 태그 기준입니다. DG·SG 인원을 합산하면 중복됩니다.")
    st.line_chart(result, x=x, y="대기 시간(분)", color="출국장")
    st.bar_chart(result, x=x, y="처리 인원", color="출국장")
    st.dataframe(result.drop(columns="weighted"), hide_index=True)
    st.download_button("현재 시간별 결과 다운로드",
                       result.drop(columns="weighted").to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"dg_sg_{month}_{terminal}_{stage}.csv")
    rate_path = Path(__file__).with_name("dg_gate_hourly_rates.csv")
    if rate_path.exists() and stage == "DG":
        rates = pd.read_csv(rate_path)
        rates = rates[rates["date"].str.startswith(month) & rates["terminal"].eq(terminal)
                      & rates["departure_gate"].isin(gates)]
        st.subheader("DG 장비당 시간당 관측 처리율")
        if st.session_state.get("developer_authenticated", False):
            st.caption("시간당 태그 인원 ÷ 해당 시간에 태그가 발생한 DG 수. 태그가 없는 운영 DG와 운영 분 수는 확인되지 않습니다.")
        st.dataframe(rates, hide_index=True)
        st.download_button("DG 장비당 관측 처리율 다운로드",
                           rates.to_csv(index=False).encode("utf-8-sig"), "dg_observed_rate.csv")


if __name__ == "__main__":
    render_dg_sg()
