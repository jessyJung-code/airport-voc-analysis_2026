"""Build stage aggregates from monthly archives and record missing source coverage."""
import argparse
from dashboard_paths import APP_DIR, SOURCE_DIR
import csv
from pathlib import Path
from prepare_dg_sg import aggregate
from prepare_airport_wait import rows


def write_csv(path, records):
    if not records:
        raise ValueError(f"No records for {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=records[0])
        writer.writeheader()
        writer.writerows(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?", default=SOURCE_DIR)
    parser.add_argument("--output", type=Path, default=APP_DIR / "airport_dg_sg_monthly")
    args = parser.parse_args()
    args.output.mkdir(exist_ok=True, parents=True)
    combined = []
    coverage = []
    for month in range(2, 11):
        source = args.source / f"{month}月.zip"
        if not source.exists():
            source = args.source / f"{month}\uC6D4.zip"
        records = list(aggregate(source, f"2026{month:02}"))
        write_csv(args.output / f"airport_dg_sg_2026_{month:02}.csv", records)
        combined.extend(records)
        for terminal in ("T1", "T2"):
            selected = [r for r in records if r["terminal"] == terminal]
            tag_months = sorted({
                r["dptgt_etry_ymd"][:6]
                for r in rows(source, f"T_DST_{terminal}_DPTGT_ETRY_PSG_INFO_E")
            })
            coverage.append({
                "month": f"2026-{month:02}", "terminal": terminal,
                "tag_source_months": ",".join(tag_months),
                "sensor_count": sum(r["sensor_count"] for r in selected),
                "tag_count": sum(r["throughput_count"] for r in selected if r["stage"] in ("DG", "UNMAPPED")),
                "stage_mapping": "DG=Entrance;SG=Security Check" if terminal == "T1" else "UNMAPPED",
            })
        print(month, len(records), flush=True)
    write_csv(args.output / "airport_dg_sg_hourly.csv", combined)
    write_csv(args.output / "coverage.csv", coverage)


if __name__ == "__main__":
    main()
