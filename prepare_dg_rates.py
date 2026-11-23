"""Observed tags per DG device-hour; active device counts are tag-based proxies."""
import argparse
from dashboard_paths import APP_DIR, SOURCE_DIR
import csv
import re
from collections import Counter
from pathlib import Path
from prepare_airport_wait import rows
from build_dg_sg_months import write_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?", default=SOURCE_DIR)
    args = parser.parse_args()
    devices = []
    gate_hours = []
    for month in range(2, 11):
        source = args.source / f"{month}\uC6D4.zip"
        for terminal in ("T1", "T2"):
            number = terminal[-1]
            ids = {r["psg_mstr_id"].strip() for r in rows(source, f"T_DST_{terminal}_DPTC_PSG_INFO_E")} - {""}
            first = {}
            for row in rows(source, f"T_DST_{terminal}_DPTGT_ETRY_PSG_INFO_E"):
                match = re.fullmatch(rf"ICN{number}D(\d{{3}})DG\d+", row["tmn_mstr_id"])
                day = row["dptgt_etry_ymd"]
                hm = row["dptgt_etry_hm"].zfill(4)
                passenger = row["psg_mstr_id"].strip()
                if (not match or passenger not in ids or not day.startswith(f"2026{month:02}")
                        or row["dptgt_incmg_dvs_cd"] not in ("0800", "0802")
                        or not re.fullmatch(r"(?:[01]\d|2[0-3])[0-5]\d", hm)):
                    continue
                key = day, int(match[1]), passenger
                value = hm, row["tmn_mstr_id"]
                first[key] = min(value, first.get(key, value))
            counts = Counter((day, gate, hm[:2], device) for (day, gate, _), (hm, device) in first.items())
            tags = Counter()
            active = Counter()
            for (day, gate, hour, device), count in sorted(counts.items()):
                date = f"{day[:4]}-{day[4:6]}-{day[6:]}"
                devices.append(dict(date=date, hour=int(hour), terminal=terminal,
                                    departure_gate=gate, device_id=device, tag_count=count))
                tags[date, gate, int(hour)] += count
                active[date, gate, int(hour)] += 1
            for (date, gate, hour), count in sorted(tags.items()):
                n = active[date, gate, hour]
                gate_hours.append(dict(date=date, hour=hour, terminal=terminal,
                                       departure_gate=gate, tag_count=count,
                                       tagged_dg_count=n, observed_tags_per_dg_hour=count / n))
        print(month, "DG rates complete", flush=True)
    write_csv(APP_DIR / "dg_device_hourly.csv", devices)
    write_csv(APP_DIR / "dg_gate_hourly_rates.csv", gate_hours)


if __name__ == "__main__":
    main()
