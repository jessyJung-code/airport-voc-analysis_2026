"""Produce independent DG tag counts and SG/Xovis-zone observations."""
import argparse
import csv
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import quantiles
from prepare_airport_wait import rows


def write(path, records, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (ValueError, TypeError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    all_tags, all_sensors, audit = [], [], []
    for month in range(2, 11):
        archive = args.source / f"{month}\uC6D4.zip"
        prefix = f"2026{month:02}"
        tag_rows = []
        for terminal in ("T1", "T2"):
            device = re.compile(rf"ICN{terminal[-1]}D(\d{{3}})DG\d+")
            first = {}
            rejected = Counter()
            for row in rows(archive, f"T_DST_{terminal}_DPTGT_ETRY_PSG_INFO_E"):
                match = device.fullmatch(row["tmn_mstr_id"].strip())
                day, hm = row["dptgt_etry_ymd"].strip(), row["dptgt_etry_hm"].strip().zfill(4)
                passenger = row["psg_mstr_id"].strip()
                if not match:
                    rejected["non_DG"] += 1
                    continue
                if not day.startswith(prefix):
                    rejected["other_month"] += 1
                    continue
                if not passenger or not re.fullmatch(r"(?:[01]\d|2[0-3])[0-5]\d", hm):
                    rejected["invalid_key_or_time"] += 1
                    continue
                if row["dptgt_incmg_dvs_cd"] not in ("0800", "0802"):
                    rejected["other_entry_code"] += 1
                    continue
                datetime.strptime(day, "%Y%m%d")
                key = day, int(match[1]), passenger
                value = hm, row["tmn_mstr_id"].strip()
                first[key] = min(value, first.get(key, value))
            counts = Counter((d, g, hm[:2], dev) for (d, g, _), (hm, dev) in first.items())
            for (d, g, hour, dev), count in sorted(counts.items()):
                tag_rows.append(dict(date=f"{d[:4]}-{d[4:6]}-{d[6:]}", hour=int(hour),
                                     terminal=terminal, departure_gate=g, dg_id=dev, tag_count=count))
            audit.append(dict(month=month, terminal=terminal, tag_count=sum(counts.values()),
                              non_dg_records=rejected["non_DG"], other_month_records=rejected["other_month"],
                              invalid_records=rejected["invalid_key_or_time"], other_entry_codes=rejected["other_entry_code"]))

        observations = defaultdict(list)
        by_zone = defaultdict(list)
        for row in rows(archive, "T_DTP_PSG_FLW_DPTGT_SNSR_DAT_E"):
            stamp = row["snsr_bdi_dt"]
            terminal = {"P01": "T1", "P02": "T2"}.get(row["tmnl_cd"])
            zone = row["snsr_dat_dstgs_nm"].strip()
            if not terminal or not stamp.startswith(prefix) or zone == "total":
                continue
            # T1 Security Check is explicit. T2 keeps its original zone identity.
            if terminal == "T1" and not zone.startswith("Security Check"):
                continue
            gate = int(row["snsr_dat_dstgs_id"])
            wait = number(row["que_brkaw_psg_wtng_psec_times"])
            length = number(row["ilnd_que_len"])
            key = terminal, gate, zone
            observations[*key, stamp[:10]].append((wait, length))
            by_zone[key].append((wait, length))
        limits = {}
        for key, values in by_zone.items():
            thresholds = []
            for i in (0, 1):
                valid = [v[i] for v in values if v[i] is not None]
                thresholds.append(quantiles(valid, n=100, method="inclusive")[94]
                                  if len(valid) > 1 else valid[0] if valid else None)
            limits[key] = thresholds
        sensors = []
        for (terminal, gate, zone, stamp), values in sorted(observations.items()):
            record = dict(date=datetime.strptime(stamp[:8], "%Y%m%d").date().isoformat(),
                          hour=int(stamp[8:]), terminal=terminal, departure_gate=gate,
                          sg_zone=zone, mapping_status="SG" if terminal == "T1" else "XOVIS_ZONE_UNCONFIRMED")
            for i, label in enumerate(("wait_seconds", "queue_length")):
                valid = [v[i] for v in values if v[i] is not None]
                limit = limits[terminal, gate, zone][i]
                filtered = [v for v in valid if v <= limit]
                record.update({f"{label}_sum": sum(valid), f"{label}_count": len(valid),
                               f"{label}_sum_p95": sum(filtered), f"{label}_count_p95": len(filtered),
                               f"{label}_p95": limit})
            sensors.append(record)
        write(args.output / f"dg_tags_2026_{month:02}.csv", tag_rows, TAG_FIELDS)
        write(args.output / f"sg_wait_2026_{month:02}.csv", sensors, SENSOR_FIELDS)
        all_tags.extend(tag_rows)
        all_sensors.extend(sensors)
        print(month, len(tag_rows), len(sensors), flush=True)
    write(args.output / "dg_tags_hourly.csv", all_tags, TAG_FIELDS)
    write(args.output / "sg_wait_hourly.csv", all_sensors, SENSOR_FIELDS)
    write(args.output / "source_quality.csv", audit, list(audit[0]))


TAG_FIELDS = ["date", "hour", "terminal", "departure_gate", "dg_id", "tag_count"]
SENSOR_FIELDS = ["date", "hour", "terminal", "departure_gate", "sg_zone", "mapping_status"]
for metric in ("wait_seconds", "queue_length"):
    SENSOR_FIELDS.extend(f"{metric}_{ending}" for ending in ("sum", "count", "sum_p95", "count_p95", "p95"))

if __name__ == "__main__":
    main()
