# -*- coding: utf-8 -*-
"""
출국장 여객 흐름(대기시간/대기열/처리여객) 분석 스크립트 — Xovis 센서 원본 기반
====================================================================
입력 : xovis_flow.csv (Xovis 사람계수 센서 원시 데이터, 분 단위)
출력 : passenger_flow_data.json - 대시보드용 집계 데이터
       여객흐름_대시보드.html     - 출국장별/터미널별/시간대별 대시보드

원본 컬럼
------------------------------------------------------------------
  snsr_bdi_dt                    : 센서 기준일시 (YYYYMMDDHHMMSS, 분 단위)
  tmnl_cd                        : 터미널 코드 (P01, P02 — 실제 2개 터미널 존재)
  snsr_dat_dstgs_id              : 출국장(게이트 그룹) 번호 (1~6, 터미널마다 다름)
  snsr_dat_dstgs_nm              : 측정지점 구분
                                      - "Entrance East Departure Gates" (동측 입구)
                                      - "Entrance West Departure Gates" (서측 입구)
                                      - "Security Check of Departure Gates" (보안검색대)
                                      - "total" (해당 출국장의 일일 누적 처리 인원,
                                                 자정 리셋 · 대기열/대기시간 값 없음)
  ilnd_que_len                   : 현재 대기열 길이(명) — "total" 행에서는 대신
                                    당일 누적 처리 인원으로 사용됨(자정 리셋)
  que_brkaw_psg_wtng_psec_times  : 대기열을 빠져나간(처리완료) 여객의 대기시간(초)
                                    → 실측 완료 대기시간, "평균 소요시간"(처리인원
                                    가중평균)과 "P95 소요시간"(95번째 백분위수,
                                    출입국 심사 모니터링 리포트와 동일한 정의)의
                                    기본값으로 사용
  que_jing_psg_wtng_psec_times   : 현재 대기열에 진입해 있는 여객의 (추정) 대기시간(초)
                                    → 참고용 실시간 추정치

⚠ 데이터 품질 참고사항
------------------------------------------------------------------
파일마다 구분자(콤마/탭)와 측정지점 구성이 다를 수 있어 두 가지를 자동
처리한다.
  - 구분자 자동감지: 첫 줄의 콤마/탭 개수를 비교해 판단한다.
  - 결함 센서 자동탐지: 단일 게이트 대기열 길이가 비정상적으로 큰(300명↑)
    스트림을 자동으로 찾아 시간대별·터미널별 등 합산 통계에서 제외하고,
    출국장별 비교에는 그대로 남겨 확인할 수 있게 한다(detect_anomalous_streams
    참고). 어떤 스트림이 제외됐는지는 build_dashboard_data() 결과의
    meta.data_quality_notes 에 매번 다시 기록된다.
  - "total"(당일 누적 처리인원) 행이 없는 터미널은 처리여객수를 집계할 수
    없다는 점도 같은 방식으로 안내한다.
"""

import pandas as pd
import json
import gzip

INPUT_PATH = "xovis_flow.csv"
JSON_OUTPUT_PATH = "passenger_flow_data.json"

MEASURE_POINT_LABELS = {
    "Entrance East Departure Gates": "입구(동측)",
    "Entrance West Departure Gates": "입구(서측)",
    "Security Check of Departure Ga": "보안검색대",
    "1A": "P02 게이트그룹1-A", "1B": "P02 게이트그룹1-B",
    "1C": "P02 게이트그룹1-C", "1D": "P02 게이트그룹1-D",
    "2A": "P02 게이트그룹2-A", "2B": "P02 게이트그룹2-B",
    "2C": "P02 게이트그룹2-C", "2D": "P02 게이트그룹2-D",
}

# 스마트패스(생체인증 기반 패스트트랙) 전용 출국장. 원본 센서 데이터에는 이
# 구분이 없어(측정지점명·게이트번호 어디에도 표시 안 됨) 사용자가 지정한
# 목록을 그대로 상수로 고정한다. 다른 공항/기간 데이터를 쓸 경우 이 목록부터
# 다시 확인해야 한다.
SMART_PASS_ZONES = {"P01 출국장2", "P01 출국장5", "P02 출국장1", "P02 출국장2"}


def gate_group_of(zone_label: str) -> str:
    return "스마트패스" if zone_label in SMART_PASS_ZONES else "일반"


def load_and_prepare(path) -> pd.DataFrame:
    """원본 센서 로그를 읽고 시간 파생 컬럼 및 구역 라벨을 생성한다.
    구분자가 콤마(,)인 파일과 탭(\\t)인 파일이 모두 존재해 자동 감지한다.
    파일이 gzip 압축(.csv.gz)이어도 그대로 읽는다 — GitHub 업로드 용량을
    줄이기 위해 원본 CSV를 gzip으로 압축해 두는 경우가 많아서다."""
    if hasattr(path, "read"):  # 업로드 파일 객체(file-like)인 경우
        is_gz = str(getattr(path, "name", "")).endswith(".gz")
        if is_gz:
            with gzip.open(path, "rt", encoding="utf-8-sig") as f:
                head_text = f.readline()
            path.seek(0)
        else:
            head = path.read(4096)
            path.seek(0)
            head_text = head.decode("utf-8-sig") if isinstance(head, bytes) else head
    else:
        path_str = str(path)
        opener = gzip.open if path_str.endswith(".gz") else open
        with opener(path_str, "rt", encoding="utf-8-sig") as f:
            head_text = f.readline()
    sep = "\t" if head_text.count("\t") > head_text.count(",") else ","

    df = pd.read_csv(path, sep=sep, encoding="utf-8-sig", compression="infer")
    df["dt"] = pd.to_datetime(df["snsr_bdi_dt"].astype(str), format="%Y%m%d%H%M%S")
    df["hour"] = df["dt"].dt.hour
    df["date"] = df["dt"].dt.date
    df["dstgs_nm"] = df["snsr_dat_dstgs_nm"].str.strip()
    df["zone_label"] = df["tmnl_cd"] + " 출국장" + df["snsr_dat_dstgs_id"].astype(str)
    df["gate_group"] = df["zone_label"].map(gate_group_of)
    df["measure_point"] = df["dstgs_nm"].map(MEASURE_POINT_LABELS).fillna(df["dstgs_nm"])
    return df


def split_queue_and_total(df: pd.DataFrame):
    """대기열/대기시간 측정 행(queue_df)과 일일누적 처리인원 행(total_df)을 분리한다."""
    queue_df = df[df["dstgs_nm"] != "total"].copy()

    total_df = df[df["dstgs_nm"] == "total"].copy()
    total_df = total_df.sort_values(["tmnl_cd", "snsr_dat_dstgs_id", "dt"])
    grp = total_df.groupby(["tmnl_cd", "snsr_dat_dstgs_id"])
    # 자정 리셋되는 누적 카운터의 분당 증분 = 그 분에 처리된 여객수
    total_df["processed"] = grp["ilnd_que_len"].diff().clip(lower=0).fillna(0)

    return queue_df, total_df


def aggregate_by_zone_hour(queue_df: pd.DataFrame, total_df: pd.DataFrame) -> pd.DataFrame:
    """터미널 x 출국장 x 시간대 단위로 처리여객/대기시간/대기열을 집계한다.
    분 단위 원시데이터는 대부분 '통행 없음(0)' 구간이 많아 0을 포함한 단순
    median/mean은 실제 체감 대기시간을 과소평가한다. 따라서 대기시간·대기열은
    값이 실제로 발생한(>0) 구간만 골라 median을 취해 "대기가 있을 때 얼마나
    걸렸는지"를 대표하도록 하고, 동시에 이상치(센서 결함)에도 견고하게 한다."""
    proc = total_df.groupby(["tmnl_cd", "snsr_dat_dstgs_id", "zone_label", "hour"])["processed"] \
        .sum().reset_index()

    def nz_median(s):
        nz = s[s > 0]
        return float(nz.median()) if len(nz) else 0.0

    qh = queue_df.groupby(["tmnl_cd", "snsr_dat_dstgs_id", "zone_label", "hour"]).agg(
        queue_med=("ilnd_que_len", nz_median),
        wait_med=("que_brkaw_psg_wtng_psec_times", nz_median),
        wait_cur_med=("que_jing_psg_wtng_psec_times", nz_median),
    ).reset_index()

    merged = proc.merge(qh, on=["tmnl_cd", "snsr_dat_dstgs_id", "zone_label", "hour"], how="outer").fillna(0)
    return merged


def detect_anomalous_streams(queue_df: pd.DataFrame, threshold: float = 300.0) -> pd.DataFrame:
    """단일 게이트 대기열 길이로는 물리적으로 불가능한 수준(threshold 이상)까지
    치솟는 센서 스트림을 자동으로 찾아낸다. 특정 파일에 존재하는 특정 센서를
    하드코딩하지 않고, 매번 새 데이터가 들어와도 같은 기준으로 재탐지한다."""
    stats = queue_df.groupby(["tmnl_cd", "snsr_dat_dstgs_id", "dstgs_nm", "zone_label", "measure_point"]) \
        ["ilnd_que_len"].max().reset_index(name="max_queue")
    return stats[stats["max_queue"] >= threshold]


def _empty_dashboard_data() -> dict:
    """선택한 필터(터미널 등)에 해당하는 데이터가 원본에 아예 없을 때(예: 이
    달 데이터에 P02 자체가 없는데 터미널을 P02로 필터링) 빈 결과를 안전하게
    반환한다. 나머지 로직이 빈 DataFrame에서 set_index 등을 호출하다 죽는
    것을 막는다."""
    return {
        "meta": {
            "date_min": "-", "date_max": "-", "total_processed": 0,
            "avg_wait_sec": 0.0, "p95_wait_sec": 0.0, "peak_hour": 0,
            "busiest_zone": "-", "terminals": [], "zones": [],
            "smart_pass_zones": [],
            "data_quality_notes": ["선택한 조건(터미널 등)에 해당하는 데이터가 이 기간에는 없습니다."],
        },
        "by_hour": {"hours": [f"{h:02d}시" for h in range(24)],
                    "processed": [0] * 24, "avg_wait_sec": [0.0] * 24,
                    "p95_wait_sec": [0.0] * 24, "queue_avg": [0.0] * 24},
        "by_zone": {"zones": [], "processed": [], "avg_wait_sec": [],
                    "p95_wait_sec": [], "queue_avg": [], "gate_group": []},
        "heatmap_processed": {"zones": [], "hours": [f"{h:02d}시" for h in range(24)], "matrix": []},
        "by_terminal": [],
        "by_gate_group": [],
        "gate_group_by_hour": {},
        "by_measure_point": {"points": [], "queue_avg": [], "avg_wait_sec": [], "p95_wait_sec": []},
    }


def build_dashboard_data(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return _empty_dashboard_data()

    queue_df, total_df = split_queue_and_total(df)
    zone_hour = aggregate_by_zone_hour(queue_df, total_df)
    zone_hour["gate_group"] = zone_hour["zone_label"].map(gate_group_of)

    # 결함 의심 센서(비정상적으로 큰 대기열 값)를 자동 탐지한다. by_zone에는
    # 그대로 남겨 개별 구역 지표로 확인할 수 있게 하되, 시간대별/전체 통계처럼
    # 여러 구역을 함께 묶는 집계에서는 제외해 이상치가 전체 그래프를 왜곡하지
    # 않도록 한다.
    anomalies = detect_anomalous_streams(queue_df)
    if len(anomalies):
        bad_keys = set(zip(anomalies["tmnl_cd"], anomalies["snsr_dat_dstgs_id"], anomalies["dstgs_nm"]))
        bad_zone_labels = set(anomalies["zone_label"])
        queue_df_clean = queue_df[~queue_df.apply(
            lambda r: (r["tmnl_cd"], r["snsr_dat_dstgs_id"], r["dstgs_nm"]) in bad_keys, axis=1
        )]
        zone_hour_clean = zone_hour[~zone_hour["zone_label"].isin(bad_zone_labels)]
    else:
        queue_df_clean = queue_df
        zone_hour_clean = zone_hour

    # "total" 행이 없거나(구조적 부재) 있어도 값이 전부 0이라 실질적으로
    # 처리여객수를 집계할 수 없는 터미널을 감지한다.
    processed_by_terminal = zone_hour.groupby("tmnl_cd")["processed"].sum()
    terminals_without_total = sorted([
        t for t in df["tmnl_cd"].unique()
        if processed_by_terminal.get(t, 0) == 0
    ])

    def weighted_avg(g, val_col, weight_col="processed"):
        """0-활동 시간대가 섞여도 median-of-median으로 값이 뭉개지지 않도록,
        처리여객수로 가중평균한다(활동이 많았던 시간대의 대기시간을 더 반영)."""
        w = g[weight_col]
        v = g[val_col]
        wsum = w.sum()
        return float((v * w).sum() / wsum) if wsum > 0 else float(v[v > 0].median() if (v > 0).any() else 0)

    def nz_percentile(s, q=0.95):
        """활동이 없는(0) 구간을 제외한 값들의 q분위수를 구한다. 평균/가중평균은
        '평상시 체감'을 보여주지만, 극단적으로 오래 걸린 상위 케이스(피크 혼잡)는
        다른 정상적인 값들 사이에 희석돼 버린다. P95는 이런 극단값을 직접 보여줘서,
        95%(원본 리포트와 같은 정의)를 그대로 적용했다."""
        nz = s[s > 0]
        return float(nz.quantile(q)) if len(nz) else 0.0

    out = {}
    data_quality_notes = []
    for _, row in anomalies.iterrows():
        data_quality_notes.append(
            f"{row['zone_label']}의 '{row['measure_point']}' 센서는 대기열 값이 {int(row['max_queue']):,}명까지 "
            "치솟는 등 단일 게이트로는 물리적으로 불가능한 패턴을 보여 결함으로 판단했습니다. "
            "출국장별 비교에는 표시되지만, 시간대별·터미널별 등 합산 통계에서는 자동으로 제외했습니다."
        )
    if terminals_without_total:
        data_quality_notes.append(
            f"{', '.join(terminals_without_total)} 터미널은 당일 누적 처리인원(total) 값이 "
            "0으로 고정되어 있어(또는 해당 항목 자체가 없어) 처리여객수를 집계할 수 없습니다 "
            "(대기열·대기시간 지표는 정상 집계됩니다)."
        )

    # 전체 대표 소요시간: 시간대별 대기시간을 그 시간대 처리여객수로 가중평균한다.
    #   (예전에는 개별 측정값 전체의 median을 썼는데, 대기줄이 비어있는 순간까지
    #   포함되면서 실제 체감보다 훨씬 짧게 나오는 문제가 있었다. 출국장별·
    #   터미널별 차트와 동일한 가중평균 방식으로 통일해 일관성을 맞춘다.)
    overall_avg_wait = weighted_avg(zone_hour_clean, "wait_med") if len(zone_hour_clean) else 0.0
    overall_p95_wait = nz_percentile(queue_df_clean["que_brkaw_psg_wtng_psec_times"])

    out["meta"] = {
        "date_min": str(df["date"].min()),
        "date_max": str(df["date"].max()),
        "total_processed": int(zone_hour["processed"].sum()),
        "avg_wait_sec": round(overall_avg_wait, 1),
        "p95_wait_sec": round(overall_p95_wait, 1),
        "peak_hour": int(zone_hour.groupby("hour")["processed"].sum().idxmax()) if zone_hour["processed"].sum() > 0 else 0,
        "busiest_zone": zone_hour.groupby("zone_label")["processed"].sum().idxmax() if zone_hour["processed"].sum() > 0 else "-",
        "terminals": sorted(df["tmnl_cd"].unique().tolist()),
        "zones": sorted(zone_hour["zone_label"].unique().tolist()),
        "smart_pass_zones": sorted(SMART_PASS_ZONES & set(zone_hour["zone_label"].unique())),
        "data_quality_notes": data_quality_notes,
    }

    # 시간대별 전체 처리여객 / 가중평균 대기시간 / 가중평균 대기열
    #   처리여객수는 전체 구역 합산(결함 센서의 처리인원 카운터 자체는 정상),
    #   대기시간·대기열 가중평균만 결함 센서를 제외해 계산한다.
    by_hour_rows = []
    for h in range(24):
        g_all = zone_hour[zone_hour["hour"] == h]
        g_clean = zone_hour_clean[zone_hour_clean["hour"] == h]
        q_clean = queue_df_clean[queue_df_clean["hour"] == h]
        by_hour_rows.append({
            "hour": h, "processed": g_all["processed"].sum(),
            "wait": weighted_avg(g_clean, "wait_med") if len(g_clean) else 0,
            "p95_wait": nz_percentile(q_clean["que_brkaw_psg_wtng_psec_times"]) if len(q_clean) else 0,
            "queue": weighted_avg(g_clean, "queue_med") if len(g_clean) else 0,
        })
    by_hour = pd.DataFrame(by_hour_rows).set_index("hour").reindex(range(24), fill_value=0)
    out["by_hour"] = {
        "hours": [f"{h:02d}시" for h in range(24)],
        "processed": by_hour["processed"].round(0).astype(int).tolist(),
        "avg_wait_sec": by_hour["wait"].round(1).tolist(),
        "p95_wait_sec": by_hour["p95_wait"].round(1).tolist(),
        "queue_avg": by_hour["queue"].round(1).tolist(),
    }

    # 출국장(터미널+게이트그룹)별 총 처리여객 / 가중평균 대기시간 / 가중평균 대기열
    by_zone_rows = []
    for z, g in zone_hour.groupby("zone_label"):
        q_zone = queue_df[queue_df["zone_label"] == z]
        by_zone_rows.append({
            "zone_label": z, "processed": g["processed"].sum(),
            "wait": weighted_avg(g, "wait_med"),
            "p95_wait": nz_percentile(q_zone["que_brkaw_psg_wtng_psec_times"]) if len(q_zone) else 0,
            "queue": weighted_avg(g, "queue_med"),
            "gate_group": gate_group_of(z),
        })
    by_zone = pd.DataFrame(by_zone_rows).set_index("zone_label").sort_values("processed", ascending=False)
    out["by_zone"] = {
        "zones": by_zone.index.tolist(),
        "processed": by_zone["processed"].round(0).astype(int).tolist(),
        "avg_wait_sec": by_zone["wait"].round(1).tolist(),
        "p95_wait_sec": by_zone["p95_wait"].round(1).tolist(),
        "queue_avg": by_zone["queue"].round(1).tolist(),
        "gate_group": by_zone["gate_group"].tolist(),
    }

    # 출국장 x 시간대 히트맵 (처리여객수)
    pivot = zone_hour.pivot_table(index="zone_label", columns="hour", values="processed", aggfunc="sum", fill_value=0)
    pivot = pivot.reindex(index=by_zone.index, columns=range(24), fill_value=0)
    out["heatmap_processed"] = {
        "zones": pivot.index.tolist(),
        "hours": [f"{h:02d}시" for h in range(24)],
        "matrix": pivot.values.round(0).astype(int).tolist(),
    }

    # 터미널별 집계 (P01 / P02 실측 비교) — processed는 전체, 대기시간/대기열은 결함 센서 제외
    by_terminal_rows = []
    for t in sorted(zone_hour["tmnl_cd"].unique()):
        g_all = zone_hour[zone_hour["tmnl_cd"] == t]
        g_clean = zone_hour_clean[zone_hour_clean["tmnl_cd"] == t]
        q_clean = queue_df_clean[queue_df_clean["tmnl_cd"] == t]
        by_terminal_rows.append({
            "terminal": t, "processed": int(g_all["processed"].sum()),
            "avg_wait_sec": round(weighted_avg(g_clean, "wait_med") if len(g_clean) else 0, 1),
            "p95_wait_sec": round(nz_percentile(q_clean["que_brkaw_psg_wtng_psec_times"]) if len(q_clean) else 0, 1),
            "queue_avg": round(weighted_avg(g_clean, "queue_med") if len(g_clean) else 0, 1),
        })
    out["by_terminal"] = by_terminal_rows

    # 스마트패스 vs 일반 출국장 그룹 비교 — 처리량은 전체 합산(카운터 자체는
    # 정상), 소요시간/대기열은 결함 센서 제외(zone_hour_clean/queue_df_clean) 후
    # 가중평균·P95를 낸다. 터미널별 집계와 동일한 패턴이다.
    by_group_rows = []
    for grp in ["스마트패스", "일반"]:
        g_all = zone_hour[zone_hour["gate_group"] == grp]
        if not len(g_all):
            continue
        g_clean = zone_hour_clean[zone_hour_clean["zone_label"].map(gate_group_of) == grp]
        q_clean = queue_df_clean[queue_df_clean["gate_group"] == grp]
        by_group_rows.append({
            "group": grp,
            "zones": sorted(g_all["zone_label"].unique().tolist()),
            "processed": int(g_all["processed"].sum()),
            "avg_wait_sec": round(weighted_avg(g_clean, "wait_med") if len(g_clean) else 0, 1),
            "p95_wait_sec": round(nz_percentile(q_clean["que_brkaw_psg_wtng_psec_times"]) if len(q_clean) else 0, 1),
            "queue_avg": round(weighted_avg(g_clean, "queue_med") if len(g_clean) else 0, 1),
        })
    out["by_gate_group"] = by_group_rows

    # 스마트패스 vs 일반 그룹의 시간대별(0~23시) 비교 — 결함 센서 제외한
    # zone_hour_clean/queue_df_clean 기준으로, 어느 시간대에 격차가 벌어지는지
    # 확인할 수 있게 한다. (전체 평균만 보면 "왜 이런 차이가 나는지" 알기
    # 어려워서, 이걸 보고 나서 추가했다.)
    gate_group_by_hour = {}
    for grp in ["스마트패스", "일반"]:
        hourly_wait, hourly_p95, hourly_queue = [], [], []
        for h in range(24):
            g_h = zone_hour_clean[(zone_hour_clean["zone_label"].map(gate_group_of) == grp)
                                   & (zone_hour_clean["hour"] == h)]
            q_h = queue_df_clean[(queue_df_clean["gate_group"] == grp) & (queue_df_clean["hour"] == h)]
            hourly_wait.append(round(weighted_avg(g_h, "wait_med") if len(g_h) else 0, 1))
            hourly_p95.append(round(nz_percentile(q_h["que_brkaw_psg_wtng_psec_times"]) if len(q_h) else 0, 1))
            hourly_queue.append(round(weighted_avg(g_h, "queue_med") if len(g_h) else 0, 1))
        if any(hourly_wait) or any(hourly_p95):
            gate_group_by_hour[grp] = {
                "hours": [f"{h:02d}시" for h in range(24)],
                "avg_wait_sec": hourly_wait,
                "p95_wait_sec": hourly_p95,
                "queue_avg": hourly_queue,
            }
    out["gate_group_by_hour"] = gate_group_by_hour

    # 측정지점별 집계 (입구 동/서 vs 보안검색대) — 어느 구간에서 지연이 발생하는지 확인
    by_point = queue_df_clean.groupby("measure_point").agg(
        queue_med=("ilnd_que_len", lambda s: float(s[s > 0].median()) if (s > 0).any() else 0.0),
        wait_med=("que_brkaw_psg_wtng_psec_times", lambda s: float(s[s > 0].median()) if (s > 0).any() else 0.0),
        wait_p95=("que_brkaw_psg_wtng_psec_times", nz_percentile),
    )
    out["by_measure_point"] = {
        "points": by_point.index.tolist(),
        "queue_avg": by_point["queue_med"].round(1).tolist(),
        "avg_wait_sec": by_point["wait_med"].round(1).tolist(),
        "p95_wait_sec": by_point["wait_p95"].round(1).tolist(),
    }

    return out


if __name__ == "__main__":
    df = load_and_prepare(INPUT_PATH)
    data = build_dashboard_data(df)

    with open(JSON_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[OK] {JSON_OUTPUT_PATH} 저장 완료")
    print("\n=== 요약 ===")
    print(f"분석기간: {data['meta']['date_min']} ~ {data['meta']['date_max']}")
    print(f"터미널: {', '.join(data['meta']['terminals'])}")
    print(f"총 처리 여객: {data['meta']['total_processed']:,}명")
    print(f"평균 소요시간(처리인원 가중평균): {data['meta']['avg_wait_sec']/60:.1f}분")
    print(f"P95 소요시간(95번째 백분위수): {data['meta']['p95_wait_sec']/60:.1f}분")
    print(f"피크 시간대: {data['meta']['peak_hour']}시")
    print(f"최다혼잡 출국장: {data['meta']['busiest_zone']}")
    print("\n=== 터미널별 ===")
    for t in data["by_terminal"]:
        print(f"  {t['terminal']}: 처리 {t['processed']:,}명, 소요 {t['avg_wait_sec']/60:.1f}분, 대기열 {t['queue_avg']}명")
