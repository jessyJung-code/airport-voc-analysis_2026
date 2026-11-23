"""Hourly DG load relative to an explicitly supplied service capacity."""
from pathlib import Path

import pandas as pd
import streamlit as st


def render_dg_queue():
    st.title("DG 시간당 혼잡률")
    source = Path(__file__).parent / "airport_dg_sg_monthly" / "airport_dg_sg_hourly.csv"
    if not source.exists():
        st.info("DG·SG 시간별 집계 파일이 필요합니다.")
        return
    data = pd.read_csv(source)
    data = data.loc[data["stage"].eq("DG")].copy()
    months = data["date"].str[:7]
    month = st.selectbox("분석 월", sorted(months.unique()), key="queue_month")
    data = data.loc[months.eq(month)]
    st.caption("혼잡률(%) = 시간당 DG 태그 인원 ÷ 시간당 처리 능력 × 100")
    uploaded = st.file_uploader("DG별 시간당 처리 능력 CSV", type="csv", key="queue_capacity")
    template = "date,hour,terminal,departure_gate,capacity_per_hour\n"
    st.download_button("처리 능력 입력 양식", template.encode("utf-8-sig"), "dg_capacity.csv")
    st.caption("날짜·시간·터미널·출국장별 실제 운영 기준 처리 능력(명/시간)을 입력하세요.")
    if uploaded is None:
        st.info("혼잡률을 계산하려면 운영 게이트 수와 게이트당 처리율로 산정한 처리 능력이 필요합니다.")
        return
    keys = ["date", "hour", "terminal", "departure_gate"]
    try:
        capacity = pd.read_csv(uploaded, dtype={"date": str})
        required = set(keys + ["capacity_per_hour"])
        if not required.issubset(capacity.columns):
            raise ValueError("입력 양식의 다섯 컬럼이 필요합니다.")
        capacity["date"] = pd.to_datetime(capacity["date"], errors="raise").dt.strftime("%Y-%m-%d")
        for column in ["hour", "departure_gate", "capacity_per_hour"]:
            capacity[column] = pd.to_numeric(capacity[column], errors="raise")
        if capacity[keys].isna().any().any() or capacity.duplicated(keys).any():
            raise ValueError("처리 능력 키에 결측값 또는 중복이 있습니다.")
        if (not capacity["hour"].between(0, 23).all()
                or not capacity["hour"].mod(1).eq(0).all()
                or not capacity["departure_gate"].gt(0).all()
                or not capacity["departure_gate"].mod(1).eq(0).all()
                or not capacity["terminal"].isin(["T1", "T2"]).all()
                or not capacity["capacity_per_hour"].ge(0).all()
                or not capacity["capacity_per_hour"].lt(float("inf")).all()):
            raise ValueError("시간·출국장·터미널·처리 능력 범위를 확인하세요.")
    except (ValueError, pd.errors.ParserError) as error:
        st.error(str(error))
        return
    result = data.merge(capacity, on=keys, how="left", validate="one_to_one")
    if not result["throughput_count"].sum():
        st.warning("선택한 월의 태그 집계가 비어 있어 혼잡률을 계산할 수 없습니다.")
        return
    missing = result["capacity_per_hour"].isna()
    if missing.any():
        st.warning(f"{missing.sum()}개 시간·출국장의 처리 능력이 없어 혼잡률을 비워 둡니다.")
    denominator = result["capacity_per_hour"].where(result["capacity_per_hour"] > 0)
    result["혼잡률(%)"] = result["throughput_count"].div(denominator).mul(100)
    result["상태"] = "산출"
    result.loc[missing, "상태"] = "처리 능력 미입력"
    result.loc[result["capacity_per_hour"].eq(0), "상태"] = "처리 능력 0"
    result.loc[result["혼잡률(%)"].ge(100), "상태"] = "수요가 처리 능력 이상"
    # Sensor P95 filtering affects waiting observations, not observed tag demand.
    result["대기 시간(분)"] = result["wait_minutes_p95"]
    result["출국장"] = result["terminal"] + " " + result["departure_gate"].astype(str) + "번"
    result["시각"] = pd.to_datetime(result["date"]) + pd.to_timedelta(result["hour"], unit="h")
    st.line_chart(result, x="시각", y="혼잡률(%)", color="출국장")
    display = result[keys + ["throughput_count", "capacity_per_hour", "혼잡률(%)", "대기 시간(분)", "상태"]]
    st.dataframe(display, hide_index=True)
    st.download_button("혼잡률 결과 다운로드", display.to_csv(index=False).encode("utf-8-sig"), "dg_queue_hourly.csv")


if __name__ == "__main__":
    render_dg_queue()
