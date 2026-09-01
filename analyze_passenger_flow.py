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
                                    → 실측 완료 대기시간, "평균 대기시간"의 기본값으로 사용
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


def load_and_prepare(path) -> pd.DataFrame:
    """원본 센서 로그를 읽고 시간 파생 컬럼 및 구역 라벨을 생성한다.
    구분자가 콤마(,)인 파일과 탭(\\t)인 파일이 모두 존재해 자동 감지한다."""
    # 첫 줄을 읽어 구분자를 판별 (탭이 콤마보다 많으면 탭 구분으로 판단)
    if hasattr(path, "read"):  # 업로드 파일 객체(file-like)인 경우
        head = path.read(4096)
        path.seek(0)
        head_text = head.decode("utf-8-sig") if isinstance(head, bytes) else head
    else:
        with open(path, "r", encoding="utf-8-sig") as f:
            head_text = f.readline()
    sep = "\t" if head_text.count("\t") > head_text.count(",") else ","

    df = pd.read_csv(path, sep=sep, encoding="utf-8-sig")
    df["dt"] = pd.to_datetime(df["snsr_bdi_dt"].astype(str), format="%Y%m%d%H%M%S")
    df["hour"] = df["dt"].dt.hour
    df["date"] = df["dt"].dt.date
    df["dstgs_nm"] = df["snsr_dat_dstgs_nm"].str.strip()
    df["zone_label"] = df["tmnl_cd"] + " 출국장" + df["snsr_dat_dstgs_id"].astype(str)
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


def build_dashboard_data(df: pd.DataFrame) -> dict:
    queue_df, total_df = split_queue_and_total(df)
    zone_hour = aggregate_by_zone_hour(queue_df, total_df)

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

    out = {}
    nz_wait = queue_df_clean.loc[queue_df_clean["que_brkaw_psg_wtng_psec_times"] > 0, "que_brkaw_psg_wtng_psec_times"]
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

    out["meta"] = {
        "date_min": str(df["date"].min()),
        "date_max": str(df["date"].max()),
        "total_processed": int(zone_hour["processed"].sum()),
        "avg_wait_sec": round(float(nz_wait.median()) if len(nz_wait) else 0.0, 1),
        "peak_hour": int(zone_hour.groupby("hour")["processed"].sum().idxmax()) if zone_hour["processed"].sum() > 0 else 0,
        "busiest_zone": zone_hour.groupby("zone_label")["processed"].sum().idxmax() if zone_hour["processed"].sum() > 0 else "-",
        "terminals": sorted(df["tmnl_cd"].unique().tolist()),
        "zones": sorted(zone_hour["zone_label"].unique().tolist()),
        "data_quality_notes": data_quality_notes,
    }

    def weighted_avg(g, val_col, weight_col="processed"):
        """0-활동 시간대가 섞여도 median-of-median으로 값이 뭉개지지 않도록,
        처리여객수로 가중평균한다(활동이 많았던 시간대의 대기시간을 더 반영)."""
        w = g[weight_col]
        v = g[val_col]
        wsum = w.sum()
        return float((v * w).sum() / wsum) if wsum > 0 else float(v[v > 0].median() if (v > 0).any() else 0)

    # 시간대별 전체 처리여객 / 가중평균 대기시간 / 가중평균 대기열
    #   처리여객수는 전체 구역 합산(결함 센서의 처리인원 카운터 자체는 정상),
    #   대기시간·대기열 가중평균만 결함 센서를 제외해 계산한다.
    by_hour_rows = []
    for h in range(24):
        g_all = zone_hour[zone_hour["hour"] == h]
        g_clean = zone_hour_clean[zone_hour_clean["hour"] == h]
        by_hour_rows.append({
            "hour": h, "processed": g_all["processed"].sum(),
            "wait": weighted_avg(g_clean, "wait_med") if len(g_clean) else 0,
            "queue": weighted_avg(g_clean, "queue_med") if len(g_clean) else 0,
        })
    by_hour = pd.DataFrame(by_hour_rows).set_index("hour").reindex(range(24), fill_value=0)
    out["by_hour"] = {
        "hours": [f"{h:02d}시" for h in range(24)],
        "processed": by_hour["processed"].round(0).astype(int).tolist(),
        "avg_wait_sec": by_hour["wait"].round(1).tolist(),
        "queue_avg": by_hour["queue"].round(1).tolist(),
    }

    # 출국장(터미널+게이트그룹)별 총 처리여객 / 가중평균 대기시간 / 가중평균 대기열
    by_zone_rows = []
    for z, g in zone_hour.groupby("zone_label"):
        by_zone_rows.append({
            "zone_label": z, "processed": g["processed"].sum(),
            "wait": weighted_avg(g, "wait_med"), "queue": weighted_avg(g, "queue_med"),
        })
    by_zone = pd.DataFrame(by_zone_rows).set_index("zone_label").sort_values("processed", ascending=False)
    out["by_zone"] = {
        "zones": by_zone.index.tolist(),
        "processed": by_zone["processed"].round(0).astype(int).tolist(),
        "avg_wait_sec": by_zone["wait"].round(1).tolist(),
        "queue_avg": by_zone["queue"].round(1).tolist(),
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
        by_terminal_rows.append({
            "terminal": t, "processed": int(g_all["processed"].sum()),
            "avg_wait_sec": round(weighted_avg(g_clean, "wait_med") if len(g_clean) else 0, 1),
            "queue_avg": round(weighted_avg(g_clean, "queue_med") if len(g_clean) else 0, 1),
        })
    out["by_terminal"] = by_terminal_rows

    # 측정지점별 집계 (입구 동/서 vs 보안검색대) — 어느 구간에서 지연이 발생하는지 확인
    by_point = queue_df_clean.groupby("measure_point").agg(
        queue_med=("ilnd_que_len", "median"),
        wait_med=("que_brkaw_psg_wtng_psec_times", "median"),
    )
    out["by_measure_point"] = {
        "points": by_point.index.tolist(),
        "queue_avg": by_point["queue_med"].round(1).tolist(),
        "avg_wait_sec": by_point["wait_med"].round(1).tolist(),
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
    print(f"평균 소요시간(중앙값): {data['meta']['avg_wait_sec']/60:.1f}분")
    print(f"피크 시간대: {data['meta']['peak_hour']}시")
    print(f"최다혼잡 출국장: {data['meta']['busiest_zone']}")
    print("\n=== 터미널별 ===")
    for t in data["by_terminal"]:
        print(f"  {t['terminal']}: 처리 {t['processed']:,}명, 소요 {t['avg_wait_sec']/60:.1f}분, 대기열 {t['queue_avg']}명")
