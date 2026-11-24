# -*- coding: utf-8 -*-
"""
출국장 입구(게이트) 혼잡도 분석 — "pax flow" 집계 리포트 엑셀 기반
====================================================================
입력 : pax-flow-zone_dep-history-YYYYMMDD-MMDD.xlsx
       (이미 시간 단위로 집계된 "조회결과" 시트 1개)
출력 : build_dashboard_data(df) -> 대시보드용 dict

원본 컬럼 (시트 "조회결과")
------------------------------------------------------------------
  입구          : 게이트 코드 (예: E-DEP-A, W-DEP-D, E-DEP-L, W-DEP-R)
  구역유형      : 전부 "입구" 한 값만 존재
  동·서편       : 동편 / 서편
  버킷 시각     : 1시간 단위 타임스탬프 ("07. 12. 오후 11:00:00")
  인원(평균/최대/P90) : 해당 시간대 구역 체류 인원(동시 체류, 누적 통과인원 아님)
  체류시간(평균/최대/P90) : "분초" 문자열 (예: "2분 30초")
  대기시간(평균)       : "분초" 문자열
  혼잡          : 원활 / 보통 / 혼잡 / 매우혼잡
  표본 수       : 센서 샘플링 횟수(시간대별로 거의 일정 — 실제 인원수와 무관,
                  처리인원 산출에 쓰지 않음)

⚠ 처리인원(통과 인원수) 산출 방식
------------------------------------------------------------------
Xovis 센서 데이터(analyze_passenger_flow.py)처럼 자정 리셋 누적 카운터가
없어 처리인원을 직접 셀 수 없다. 대신 Little's Law를 적용한다.

    L = λ · W   =>   λ = L / W
    L(평균 체류 인원) = "인원(평균)"
    W(평균 체류시간, 시간 단위로 환산) = "체류시간(평균)" ÷ 3600
    λ = 시간당 처리인원(추정치) [단위: 명/시간]  (λ/60 = 분당 처리인원)

이 값은 실측 카운터가 아닌 **추정치**이며, 사용자(세연님)와 협의해
Xovis의 "total" 카운터가 7·8월 데이터에서 전부 0(집계 불가)인 것을 확인한
뒤 대안으로 도입했다.
"""

import re
import pandas as pd
import openpyxl

INPUT_PATH = "pax_flow_07m.xlsx"  # 기본값 (단일 파일 직접 로드 시 사용)
SHEET_NAME = "조회결과"

COLS = ["gate", "zone_type", "side", "bucket_raw", "occ_avg", "occ_max", "occ_p90",
        "dwell_avg_raw", "dwell_max_raw", "dwell_p90_raw", "wait_avg_raw",
        "congestion", "sample_n"]


def _mmss_to_sec(s):
    """'2분 30초' / '5분' / '49초' / '0초' -> 초(float)"""
    if s is None:
        return 0.0
    s = str(s).strip()
    if s in ("", "0", "0초"):
        return 0.0
    m = re.search(r"(\d+)\s*분", s)
    sec = re.search(r"(\d+)\s*초", s)
    minutes = int(m.group(1)) if m else 0
    seconds = int(sec.group(1)) if sec else 0
    return minutes * 60 + seconds


def _parse_bucket(raw):
    """'07. 12. 오후 11:00:00' -> (month, day, hour24)"""
    mo, da, ampm, hm = raw.split(" ", 3)
    month = int(mo.replace(".", ""))
    day = int(da.replace(".", ""))
    h, _mi, _sec = hm.split(":")
    h = int(h)
    if ampm == "오후" and h != 12:
        h += 12
    if ampm == "오전" and h == 12:
        h = 0
    return month, day, h


def load_and_prepare(path) -> pd.DataFrame:
    """엑셀(또는 업로드 파일 객체)의 '조회결과' 시트를 읽어 분석용 컬럼을 derive한다."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[SHEET_NAME]
    rows = [row for row in ws.iter_rows(min_row=2, values_only=True) if row[0] is not None]
    wb.close()

    df = pd.DataFrame(rows, columns=COLS)
    df["occ_avg"] = pd.to_numeric(df["occ_avg"], errors="coerce").fillna(0.0)
    df["occ_max"] = pd.to_numeric(df["occ_max"], errors="coerce").fillna(0.0)
    df["sample_n"] = pd.to_numeric(
        df["sample_n"].astype(str).str.replace(",", ""), errors="coerce"
    ).fillna(0)

    df["dwell_avg_sec"] = df["dwell_avg_raw"].map(_mmss_to_sec)
    df["wait_avg_sec"] = df["wait_avg_raw"].map(_mmss_to_sec)

    parsed = df["bucket_raw"].map(_parse_bucket)
    df["month"] = parsed.map(lambda t: t[0])
    df["day"] = parsed.map(lambda t: t[1])
    df["hour"] = parsed.map(lambda t: t[2])
    df["date"] = df.apply(lambda r: f"2026-{int(r['month']):02d}-{int(r['day']):02d}", axis=1)
    df["gate_group"] = df["gate"]  # 입구 코드 자체를 게이트 식별자로 사용

    # Little's Law: lambda(명/시간) = L(평균 체류인원) / W(시간)
    dwell_h = df["dwell_avg_sec"] / 3600.0
    df["processed_per_hour_est"] = 0.0
    mask = dwell_h > 0
    df.loc[mask, "processed_per_hour_est"] = df.loc[mask, "occ_avg"] / dwell_h[mask]
    df["processed_per_min_est"] = df["processed_per_hour_est"] / 60.0

    return df


def load_and_combine(paths) -> pd.DataFrame:
    """여러 파일(서로 다른 기간)을 합쳐서 하나의 DataFrame으로 반환한다."""
    dfs = [load_and_prepare(p) for p in paths]
    return pd.concat(dfs, ignore_index=True)


CONGESTION_ORDER = ["원활", "보통", "혼잡", "매우혼잡"]


def build_dashboard_data(df: pd.DataFrame) -> dict:
    """게이트/동서편/시간대별 체류인원·체류시간·대기시간·추정 처리인원을 집계한다."""
    if len(df) == 0:
        return {
            "meta": {"date_min": "-", "date_max": "-", "n_gates": 0, "gates": [],
                      "total_processed_est": 0, "avg_occupancy": 0.0,
                      "avg_dwell_sec": 0.0, "avg_wait_sec": 0.0},
            "by_gate": {"gates": [], "total_processed_est": [], "avg_processed_per_hour": [],
                        "avg_processed_per_min": [], "avg_occupancy": [], "avg_dwell_sec": [],
                        "avg_wait_sec": [], "side": []},
            "by_side": {"sides": [], "total_processed_est": [], "avg_processed_per_hour": [],
                        "avg_processed_per_min": []},
            "by_hour": {"hours": [f"{h:02d}시" for h in range(24)],
                        "avg_processed_per_hour": [0.0] * 24, "avg_occupancy": [0.0] * 24,
                        "avg_wait_sec": [0.0] * 24},
            "heatmap_processed": {"gates": [], "hours": [f"{h:02d}시" for h in range(24)], "matrix": []},
            "congestion_dist": {"labels": CONGESTION_ORDER, "values": [0] * len(CONGESTION_ORDER)},
        }

    out = {}
    out["meta"] = {
        "date_min": str(df["date"].min()),
        "date_max": str(df["date"].max()),
        "n_gates": df["gate_group"].nunique(),
        "gates": sorted(df["gate_group"].unique().tolist()),
        "total_processed_est": round(df["processed_per_hour_est"].sum(), 0),
        "avg_occupancy": round(df["occ_avg"].mean(), 1),
        "avg_dwell_sec": round(df["dwell_avg_sec"].mean(), 1),
        "avg_wait_sec": round(df["wait_avg_sec"].mean(), 1),
    }

    # 게이트별
    bg = (
        df.groupby("gate_group")
        .agg(
            total_processed_est=("processed_per_hour_est", "sum"),
            avg_processed_per_hour=("processed_per_hour_est", "mean"),
            avg_occupancy=("occ_avg", "mean"),
            avg_dwell_sec=("dwell_avg_sec", "mean"),
            avg_wait_sec=("wait_avg_sec", "mean"),
            side=("side", "first"),
            n_hours=("processed_per_hour_est", "size"),
        )
        .reset_index()
        .sort_values("total_processed_est", ascending=False)
    )
    bg["avg_processed_per_min"] = bg["avg_processed_per_hour"] / 60.0
    out["by_gate"] = {
        "gates": bg["gate_group"].tolist(),
        "total_processed_est": bg["total_processed_est"].round(0).tolist(),
        "avg_processed_per_hour": bg["avg_processed_per_hour"].round(1).tolist(),
        "avg_processed_per_min": bg["avg_processed_per_min"].round(2).tolist(),
        "avg_occupancy": bg["avg_occupancy"].round(1).tolist(),
        "avg_dwell_sec": bg["avg_dwell_sec"].round(1).tolist(),
        "avg_wait_sec": bg["avg_wait_sec"].round(1).tolist(),
        "side": bg["side"].tolist(),
        "n_hours": bg["n_hours"].tolist(),
    }

    # 동/서편별
    bs = (
        df.groupby("side")
        .agg(
            total_processed_est=("processed_per_hour_est", "sum"),
            avg_processed_per_hour=("processed_per_hour_est", "mean"),
        )
        .reset_index()
    )
    bs["avg_processed_per_min"] = bs["avg_processed_per_hour"] / 60.0
    out["by_side"] = {
        "sides": bs["side"].tolist(),
        "total_processed_est": bs["total_processed_est"].round(0).tolist(),
        "avg_processed_per_hour": bs["avg_processed_per_hour"].round(1).tolist(),
        "avg_processed_per_min": bs["avg_processed_per_min"].round(2).tolist(),
    }

    # 시간대별 (전체 게이트 평균)
    bh = (
        df.groupby("hour")
        .agg(
            avg_processed_per_hour=("processed_per_hour_est", "mean"),
            avg_occupancy=("occ_avg", "mean"),
            avg_wait_sec=("wait_avg_sec", "mean"),
        )
        .reindex(range(24), fill_value=0.0)
    )
    out["by_hour"] = {
        "hours": [f"{h:02d}시" for h in range(24)],
        "avg_processed_per_hour": bh["avg_processed_per_hour"].round(1).tolist(),
        "avg_occupancy": bh["avg_occupancy"].round(1).tolist(),
        "avg_wait_sec": bh["avg_wait_sec"].round(1).tolist(),
    }

    # 게이트 x 시간대 히트맵 (시간당 추정 처리인원)
    pivot = df.pivot_table(index="gate_group", columns="hour", values="processed_per_hour_est",
                            aggfunc="mean", fill_value=0.0)
    pivot = pivot.reindex(index=bg["gate_group"], columns=range(24), fill_value=0.0)
    out["heatmap_processed"] = {
        "gates": pivot.index.tolist(),
        "hours": [f"{h:02d}시" for h in range(24)],
        "matrix": pivot.values.round(1).tolist(),
    }

    # 혼잡도 분포(시간대 수 기준)
    cvc = df["congestion"].value_counts()
    out["congestion_dist"] = {
        "labels": CONGESTION_ORDER,
        "values": [int(cvc.get(c, 0)) for c in CONGESTION_ORDER],
    }

    return out


if __name__ == "__main__":
    df = load_and_combine(["pax_flow_07m.xlsx", "pax_flow_08m.xlsx"])
    data = build_dashboard_data(df)
    print(f"분석기간: {data['meta']['date_min']} ~ {data['meta']['date_max']}")
    print(f"게이트 수: {data['meta']['n_gates']}")
    print(f"평균 체류인원: {data['meta']['avg_occupancy']}명, "
          f"평균 체류시간: {data['meta']['avg_dwell_sec']}초, "
          f"평균 대기시간: {data['meta']['avg_wait_sec']}초")
    print("\n=== 게이트별 ===")
    for g, h, m in zip(data["by_gate"]["gates"],
                        data["by_gate"]["avg_processed_per_hour"],
                        data["by_gate"]["avg_processed_per_min"]):
        print(f"  {g}: 시간당 {h}명 · 분당 {m}명")
