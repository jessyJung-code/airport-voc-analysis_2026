"""Split Xovis entrance and security observations, using entrance tags as throughput."""
import argparse
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, quantiles

from prepare_airport_wait import build, rows


def aggregate(source, month=None):
    throughput = {
        (r["terminal"], r["departure_gate"], r["date"].replace("-", "") + f'{r["hour"]:02}'): r["tag_count"]
        for r in build(source, month)
    }
    observations = defaultdict(list)
    groups = defaultdict(list)
    for row in rows(source, "T_DTP_PSG_FLW_DPTGT_SNSR_DAT_E"):
        stamp = row["snsr_bdi_dt"]
        if month and not stamp.startswith(month):
            continue
        terminal = {"P01": "T1", "P02": "T2"}.get(row["tmnl_cd"])
        zone = row["snsr_dat_dstgs_nm"].strip()
        if not terminal or zone == "total":
            continue
        if terminal == "T1":
            if zone.startswith("Entrance"):
                stage = "DG"
            elif zone.startswith("Security Check"):
                stage = "SG"
            else:
                continue
        else:
            stage = "UNMAPPED"
        try:
            value = float(row["que_brkaw_psg_wtng_psec_times"])
        except ValueError:
            continue
        if not 0 <= value < float("inf"):
            continue
        gate = int(row["snsr_dat_dstgs_id"])
        observations[terminal, gate, stage, stamp[:10]].append(value)
        groups[terminal, gate, stage].append(value)
    thresholds = {
        key: quantiles(values, n=100, method="inclusive")[94] if len(values) > 1 else values[0]
        for key, values in groups.items()
    }
    keys = set(observations)
    for terminal, gate, hour in throughput:
        stages = ("DG", "SG") if terminal == "T1" else ("UNMAPPED",)
        keys.update((terminal, gate, stage, hour) for stage in stages)
    for terminal, gate, stage, hour in sorted(keys):
        values = observations.get((terminal, gate, stage, hour), [])
        p95 = thresholds.get((terminal, gate, stage))
        trimmed = [value for value in values if value <= p95]
        count = throughput.get((terminal, gate, hour), 0)
        yield {
            "date": datetime.strptime(hour[:8], "%Y%m%d").date().isoformat(),
            "hour": int(hour[8:]), "terminal": terminal, "departure_gate": gate,
            "stage": stage, "throughput_count": count,
            "throughput_basis": "DG_TAG_PROXY",
            "sensor_count": len(values), "sensor_count_p95": len(trimmed),
            "p95_seconds": p95, "wait_minutes": mean(values) / 60 if values else None,
            "wait_minutes_p95": mean(trimmed) / 60 if trimmed else None,
            "matched_throughput": count if values else 0,
            "matched_throughput_p95": count if trimmed else 0,
            "weighted_wait_minutes": count * mean(values) / 60 if values else 0,
            "weighted_wait_minutes_p95": count * mean(trimmed) / 60 if trimmed else 0,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("."))
    parser.add_argument("--month")
    parser.add_argument("--output", type=Path, default=Path("airport_dg_sg_hourly.csv"))
    args = parser.parse_args()
    records = list(aggregate(args.source, args.month))
    if not records:
        parser.error("No eligible sensor observations")
    with args.output.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=records[0])
        writer.writeheader()
        writer.writerows(records)
    print(f"{len(records)} rows: {args.output}")
