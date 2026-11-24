# -*- coding: utf-8 -*-
"""IIAC_operation_2026.xlsx(출국장별 운영 현황: 운영 호기·유인 DG·대기열) → passenger_flow_data/operation_snapshots.csv

사용: python prepare_operation_data.py [엑셀 경로]
  - T1 시트: 출국장 1~6, 열 = 호기 / DG / 대기열(동/서)
  - T2 시트: 출국장 1~2, 열 = 호기 / 유인DG / 대기열(1A,1B,1C,1D). 시트에 2025년으로 적힌 날짜는 2026년 같은 월·일로 보정
  - 정수가 아닌 값(수식 오염), 0 이하 값은 결측 처리. 대기열 "대기열 없음"은 0
"""
import datetime as dt
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("IIAC_operation_2026.xlsx")
OUT = Path(__file__).parent / "passenger_flow_data" / "operation_snapshots.csv"


def minutes(x):
    if isinstance(x, (dt.time, dt.datetime)):
        return x.hour * 60 + x.minute
    if isinstance(x, str):
        m = re.search(r"(\d{1,2}):(\d{2})", x)
        if m:
            return int(m[1]) * 60 + int(m[2])
    return np.nan


def num(x):
    if isinstance(x, (int, np.integer)):
        return float(x)
    if isinstance(x, float):
        return x if (not np.isnan(x) and abs(x - round(x)) < 1e-9) else np.nan
    if isinstance(x, str) and re.fullmatch(r"\d+", x.strip()):
        return float(x.strip())
    return np.nan


def queue(x, n):
    if isinstance(x, str):
        s = x.replace(" ", "")
        if "대기열없음" in s:
            return [0.0] * n
        p = re.findall(r"\d+", s)
        if len(p) == n:
            return [float(v) for v in p]
    return [np.nan] * n


def main():
    rows = []
    t1 = pd.read_excel(SRC, sheet_name="T1", header=None).iloc[3:]
    cur = None
    for _, r in t1.iterrows():
        v = r[0]
        if pd.notna(v):
            if isinstance(v, str):
                m = re.match(r"(\d+)월\s*(\d+)일", v)
                cur = pd.Timestamp(2026, int(m[1]), int(m[2])) if m else cur
            else:
                cur = pd.Timestamp(v)
        t = minutes(r[2])
        if cur is None or np.isnan(t):
            continue
        for g, c in {1: 3, 2: 6, 3: 9, 4: 12, 5: 15, 6: 18}.items():
            q = queue(r[c + 2], 2)
            rows.append(dict(date=cur, minute=t, terminal="T1", departure_gate=g, pax_forecast=r[1],
                             lanes=num(r[c]), dg_manned=num(r[c + 1]), queue_reported=np.nansum(q) if not np.isnan(q).all() else np.nan))
    t2 = pd.read_excel(SRC, sheet_name="T2", header=None).iloc[4:]
    for _, r in t2.iterrows():
        if isinstance(r[0], str):
            continue
        if pd.notna(r[0]):
            d = pd.Timestamp(r[0])
            cur = None if (d.month == 2 and d.day == 29) else pd.Timestamp(2026, d.month, d.day)
        t = minutes(r[2])
        if cur is None or np.isnan(t):
            continue
        for g, c in {1: 3, 2: 6}.items():
            q = queue(r[c + 2], 4)
            rows.append(dict(date=cur, minute=t, terminal="T2", departure_gate=g, pax_forecast=r[1],
                             lanes=num(r[c]), dg_manned=num(r[c + 1]), queue_reported=np.nansum(q) if not np.isnan(q).all() else np.nan))
    x = pd.DataFrame(rows)
    x["hour"] = (x["minute"] // 60).astype(int)
    x["slot"] = x["minute"].map(lambda m: f"{int(m // 60):02d}:{int(m % 60):02d}")
    x["pax_forecast"] = pd.to_numeric(x["pax_forecast"], errors="coerce")
    for c in ("lanes", "dg_manned"):
        x.loc[x[c] < 1, c] = np.nan
    # 기록이 거의 없는 출국장·드문 시각 제외
    x = x[x.groupby(["terminal", "departure_gate"])["lanes"].transform("count") >= 500]
    x = x[x.groupby(["terminal", "departure_gate", "slot"])["slot"].transform("size") >= 100]
    x = x.dropna(subset=["lanes", "dg_manned"], how="all")
    OUT.parent.mkdir(exist_ok=True)
    x[["date", "slot", "hour", "terminal", "departure_gate", "lanes", "dg_manned", "queue_reported", "pax_forecast"]] \
        .to_csv(OUT, index=False, encoding="utf-8-sig")
    print(OUT, len(x))


if __name__ == "__main__":
    main()
