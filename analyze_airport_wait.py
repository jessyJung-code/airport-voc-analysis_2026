# -*- coding: utf-8 -*-
"""airport_wait_hourly*.csv(시간 단위 집계) 로딩·집계 로직.

입력 형식(prepare_airport_wait.py 출력): date, hour, terminal, departure_gate,
tag_count, sensor_count, p95_seconds, ..., matched_tags(_p95), weighted_seconds(_p95)
월별 파일(airport_wait_hourly_02m.csv 등)이나 1~11월 통합 파일 모두 허용한다.
"""
from pathlib import Path
import pandas as pd

FILE_PATTERN = "airport_wait_hourly*.csv"
KEY = ["date", "hour", "terminal", "departure_gate"]
WEEKDAYS = "월화수목금토일"


def find_files(app_dir):
    root = Path(app_dir)
    paths = []
    for base in (root, root / "data", root / "airport_wait_monthly"):
        paths.extend(sorted(base.glob(FILE_PATTERN)))
    return list(dict.fromkeys(str(path.resolve()) for path in paths))


def load_and_prepare(sources):
    frames = [pd.read_csv(s, parse_dates=["date"]) for s in sources]
    # A later monthly file replaces the entire corresponding month.
    by_month = {}
    for frame in frames:
        for period, data in frame.groupby(frame["date"].dt.to_period("M")):
            by_month[period] = data
    df = pd.concat(by_month.values(), ignore_index=True).drop_duplicates(KEY, keep="last")
    df["month"] = df["date"].dt.month
    df["gate"] = df["terminal"] + " " + df["departure_gate"].astype(str) + "번"
    df["weekday"] = df["date"].dt.weekday.map(lambda i: WEEKDAYS[i])
    return df.sort_values(KEY).reset_index(drop=True)


def _suffix(trim):
    return "_p95" if trim else ""


def _wavg(g, trim):
    s = _suffix(trim)
    m, w = g[f"matched_tags{s}"].sum(), g[f"weighted_seconds{s}"].sum()
    return float(w / m / 60) if m > 0 else None


def _agg(df, keys, trim):
    s = _suffix(trim)
    r = df.groupby(keys, as_index=False).agg(
        tags=("tag_count", "sum"), matched=(f"matched_tags{s}", "sum"),
        weighted=(f"weighted_seconds{s}", "sum"))
    r["avg_wait_min"] = (r["weighted"] / r["matched"].where(r["matched"] > 0) / 60).round(2)
    return r.drop(columns="weighted")


def build_dashboard_data(df, trim=True):
    """필터링된 df → 대시보드용 집계. 처리인원=출국장 진입 태그 인원(실측)."""
    total = int(df["tag_count"].sum())
    avg = _wavg(df, trim)
    # P95: 출국장별 기준값(관측 전체의 95번째 백분위수)을 태그 인원으로 가중 평균
    gp = df.dropna(subset=["p95_seconds"]).assign(weighted_p95=lambda x: x["p95_seconds"] * x["tag_count"])
    p95 = float(gp["weighted_p95"].sum() / gp["tag_count"].sum() / 60) if gp["tag_count"].sum() > 0 else None
    by_gate = _agg(df, ["terminal", "gate"], trim)
    gate_p95 = gp.groupby("gate")[["weighted_p95", "tag_count"]].sum()
    p95_gate = gate_p95["weighted_p95"].div(gate_p95["tag_count"].where(gate_p95["tag_count"] > 0)).div(60).round(2)
    by_gate["p95_min"] = by_gate["gate"].map(p95_gate)
    by_gate["variability"] = (by_gate["p95_min"] / by_gate["avg_wait_min"].where(by_gate["avg_wait_min"] > 0)).round(2)
    by_term = _agg(df, ["terminal"], trim)
    by_hour = _agg(df, ["hour"], trim)
    by_hour_term = _agg(df, ["hour", "terminal"], trim)
    by_date = _agg(df.assign(day=df["date"].dt.strftime("%m-%d ") + df["weekday"]), ["day"], trim)
    heat = df.pivot_table(index="gate", columns="hour", values="tag_count", aggfunc="sum").reindex(columns=range(24)).fillna(0)
    active = by_gate.dropna(subset=["avg_wait_min"])
    busiest = active.sort_values("avg_wait_min", ascending=False).iloc[0]["gate"] if len(active) else "-"
    peak = int(by_hour.sort_values("tags", ascending=False).iloc[0]["hour"]) if total > 0 else None
    return dict(total=total, avg=avg, p95=p95,
                variability=round(p95 / avg, 2) if avg and p95 else None,
                peak_hour=peak, busiest=busiest,
                days=int(df["date"].nunique()), gates=int(df["gate"].nunique()),
                period=(df["date"].min().date(), df["date"].max().date()),
                by_gate=by_gate, by_term=by_term, by_hour=by_hour,
                by_hour_term=by_hour_term, by_date=by_date, heat=heat)
