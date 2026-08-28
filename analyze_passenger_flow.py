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
탐색 결과 P02 / 출국장1 / "Security Check of Departure Gates" 센서 스트림은
ilnd_que_len 값이 다른 센서처럼 등락하지 않고 자정마다 리셋되며 하루 종일
누적 증가하는 비정상 패턴을 보였다(다른 센서는 정상적으로 0~130명 사이를
오르내림). 특정 센서 한 개의 결함으로 판단되어, 평균(mean) 대신 중앙값
(median)을 집계 통계량으로 사용해 이런 이상치가 전체 지표를 왜곡하지
않도록 했다. 실무 반영 전 해당 센서를 별도로 점검할 것을 권장한다.
"""

import pandas as pd
import json

INPUT_PATH = "xovis_flow.csv"
JSON_OUTPUT_PATH = "passenger_flow_data.json"

MEASURE_POINT_LABELS = {
    "Entrance East Departure Gates": "입구(동측)",
    "Entrance West Departure Gates": "입구(서측)",
    "Security Check of Departure Ga": "보안검색대",
}


def load_and_prepare(path: str = INPUT_PATH) -> pd.DataFrame:
    """원본 센서 로그를 읽고 시간 파생 컬럼 및 구역 라벨을 생성한다."""
    df = pd.read_csv(path)
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


def build_dashboard_data(df: pd.DataFrame) -> dict:
    queue_df, total_df = split_queue_and_total(df)
    zone_hour = aggregate_by_zone_hour(queue_df, total_df)

    # 알려진 결함 센서(P02 출국장1 보안검색대)는 by_zone에는 그대로 남겨 개별
    # 구역 지표로 확인할 수 있게 하되, 시간대별/전체 통계처럼 여러 구역을 함께
    # 묶는 집계에서는 제외해 이상치가 전체 그래프를 왜곡하지 않도록 한다.
    FLAGGED_ZONE = "P02 출국장1"
    zone_hour_clean = zone_hour[zone_hour["zone_label"] != FLAGGED_ZONE]
    queue_df_clean = queue_df[
        ~((queue_df["tmnl_cd"] == "P02") & (queue_df["snsr_dat_dstgs_id"] == 1)
          & (queue_df["dstgs_nm"] == "Security Check of Departure Ga"))
    ]

    out = {}
    nz_wait = queue_df_clean.loc[queue_df_clean["que_brkaw_psg_wtng_psec_times"] > 0, "que_brkaw_psg_wtng_psec_times"]
    out["meta"] = {
        "date_min": str(df["date"].min()),
        "date_max": str(df["date"].max()),
        "total_processed": int(zone_hour["processed"].sum()),
        "avg_wait_sec": round(float(nz_wait.median()) if len(nz_wait) else 0.0, 1),
        "peak_hour": int(zone_hour.groupby("hour")["processed"].sum().idxmax()),
        "busiest_zone": zone_hour.groupby("zone_label")["processed"].sum().idxmax(),
        "terminals": sorted(df["tmnl_cd"].unique().tolist()),
        "zones": sorted(zone_hour["zone_label"].unique().tolist()),
        "data_quality_notes": [
            "P02 출국장1의 보안검색대 센서는 대기열 수치가 자정마다 리셋 후 하루 종일 "
            "누적 증가하는 비정상 패턴을 보여, 해당 구역의 대기열/대기시간이 과대 계상되었을 "
            "가능성이 있습니다(센서 점검 권장). 이 구역은 출국장별 비교에는 표시되지만, "
            "시간대별·터미널별 등 여러 구역을 합산하는 통계에서는 제외했습니다.",
            "P01 출국장1·3·6은 당일 누적 처리인원(total) 값이 0으로 고정되어 있어 "
            "처리여객수 지표가 집계되지 않습니다(해당 구역엔 입구 대기열 센서만 있고 "
            "보안검색 처리량 센서가 없는 것으로 보입니다).",
        ],
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
    print(f"평균 대기시간(중앙값): {data['meta']['avg_wait_sec']}초")
    print(f"피크 시간대: {data['meta']['peak_hour']}시")
    print(f"최다혼잡 출국장: {data['meta']['busiest_zone']}")
    print("\n=== 터미널별 ===")
    for t in data["by_terminal"]:
        print(f"  {t['terminal']}: 처리 {t['processed']:,}명, 대기 {t['avg_wait_sec']}초, 대기열 {t['queue_avg']}명")
