# -*- coding: utf-8 -*-
"""
출입국 심사 소요시간(모니터링) 분석 스크립트
============================================
입력 : immigration_processing_time.csv
       (보고서 x 절차구분 x 터미널 x 출국장 x 지표(P95/평균) x 시간대별
        소요시간 원자료)
출력 : immigration_data.json - 대시보드용 집계 데이터

원본은 "신분확인_보안검색_대기시간_2026-1-2차.pptx" 리포트의 표 4개를 옮겨
적어 tidy(long) 포맷으로 정리했다.
  report     : 1차(`26.2.12~2.15, 4일간) / 2차(`26.6.20~6.23, 4일간)
  category   : 신분확인 / 보안검색 — 서로 다른 절차의 소요시간이며 표본수도
               다르다(예: 1차 신분확인 19,825건 vs 1차 보안검색 2,387건).
               같은 게이트라도 두 절차는 별도로 비교해야 한다.
  terminal   : T1 / T2
  gate       : N번출국장
  metric     : P95(95% 소요시간) / 평균(평균 소요시간)
  time_slot  : 전체 / 06시~07시 / ... / 17시~18시 (11구간, 11~13시는
               원본 표에 없어 제외됨 — 점심시간 등으로 표본이 없었을 가능성)
  sample_n   : 그 시간대의 전체 처리인원(해당 보고서·절차구분 내 모든
               출국장 합산, 원본 헤더 기준). ⚠ 게이트별로 나뉜 값이 아니므로
               "게이트별 처리인원"은 원본 데이터에 없어 제공하지 않는다.
  mmss       : "h:mm:ss" 원본 표기
  seconds    : mmss를 초로 환산한 값 (계산/차트용)
"""

import pandas as pd
import json

INPUT_PATH = "immigration_processing_time.csv"
JSON_OUTPUT_PATH = "immigration_data.json"

TIME_SLOT_ORDER = ["전체", "06시~07시", "07시~08시", "08시~09시", "09시~10시", "10시~11시",
                   "13시~14시", "14시~15시", "15시~16시", "16시~17시", "17시~18시"]


def load_and_prepare(path) -> pd.DataFrame:
    """tidy CSV를 그대로 읽는다. time_slot을 원본 표 순서의 카테고리로 고정한다."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["time_slot"] = pd.Categorical(df["time_slot"], categories=TIME_SLOT_ORDER, ordered=True)
    return df


def build_dashboard_data(df: pd.DataFrame) -> dict:
    out = {}

    reports = sorted(df["report"].unique().tolist())
    categories = sorted(df["category"].unique().tolist())
    out["meta"] = {
        "reports": reports,
        "categories": categories,
        "terminals": sorted(df["terminal"].unique().tolist()),
        "time_slots": TIME_SLOT_ORDER,
    }

    # 보고서 x 절차구분별 시간대 처리인원(전체 집계, 게이트 구분 없음)
    out["processed"] = {}
    for r in reports:
        out["processed"][r] = {}
        for c in categories:
            sub = df[(df["report"] == r) & (df["category"] == c)][["time_slot", "sample_n"]].drop_duplicates()
            sub = sub.set_index("time_slot").reindex(TIME_SLOT_ORDER)
            out["processed"][r][c] = sub["sample_n"].fillna(0).astype(int).tolist()

    # 보고서 x 절차구분 x 터미널별 게이트 목록
    out["gates_by_terminal"] = {}
    for r in reports:
        out["gates_by_terminal"][r] = {}
        for c in categories:
            out["gates_by_terminal"][r][c] = {
                t: df[(df["report"] == r) & (df["category"] == c) & (df["terminal"] == t)]["gate"]
                .drop_duplicates().tolist()
                for t in out["meta"]["terminals"]
            }

    # 보고서 x 절차구분 x 터미널 x 게이트 x 지표 x 시간대 -> 초 (차트 원자료)
    series = {}
    for (r, c, t, g, m), sub in df.groupby(["report", "category", "terminal", "gate", "metric"]):
        sub = sub.set_index("time_slot").reindex(TIME_SLOT_ORDER)
        series.setdefault(r, {}).setdefault(c, {}).setdefault(t, {}).setdefault(m, {})[g] = \
            sub["seconds"].fillna(0).astype(int).tolist()
    out["series"] = series

    # 보고서 x 절차구분 x 터미널 x 게이트 x 지표의 "전체" 소요시간 요약
    overall = df[df["time_slot"] == "전체"]
    out["overall"] = [
        {"report": r["report"], "category": r["category"], "terminal": r["terminal"], "gate": r["gate"],
         "metric": r["metric"], "seconds": int(r["seconds"])}
        for _, r in overall.iterrows()
    ]

    # 보고서 x 절차구분 x 터미널별 요약 (P95 기준 최장/최단 게이트, "전체" 시간대)
    out["terminal_summary"] = []
    for r in reports:
        for c in categories:
            for t in out["meta"]["terminals"]:
                sub = overall[(overall["report"] == r) & (overall["category"] == c)
                              & (overall["terminal"] == t) & (overall["metric"] == "P95")]
                if sub.empty:
                    continue
                worst = sub.loc[sub["seconds"].idxmax()]
                best = sub.loc[sub["seconds"].idxmin()]
                out["terminal_summary"].append({
                    "report": r, "category": c, "terminal": t,
                    "avg_p95_sec": round(sub["seconds"].mean(), 1),
                    "worst_gate": worst["gate"], "worst_sec": int(worst["seconds"]),
                    "best_gate": best["gate"], "best_sec": int(best["seconds"]),
                })

    return out


if __name__ == "__main__":
    df = load_and_prepare(INPUT_PATH)
    data = build_dashboard_data(df)

    with open(JSON_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[OK] {JSON_OUTPUT_PATH} 저장 완료")
    print("\n=== 요약 ===")
    for s in data["terminal_summary"]:
        print(f"[{s['report']}/{s['category']}] {s['terminal']}: 평균 P95 {s['avg_p95_sec']}초 · "
              f"최장 {s['worst_gate']}({s['worst_sec']}초) · 최단 {s['best_gate']}({s['best_sec']}초)")
