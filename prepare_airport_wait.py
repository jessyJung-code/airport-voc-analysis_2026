"""Build a dashboard CSV from one month's source directory or ZIP."""
import argparse
import csv
import re
from collections import Counter, defaultdict
from datetime import datetime
from io import TextIOWrapper
from pathlib import Path
from statistics import mean, quantiles
from zipfile import ZipFile


def rows(root, table):
    if root.suffix.lower() == ".zip":
        pattern = re.compile(rf"{re.escape(table)}(?:_\d+m| \(\d+\))?\.csv", re.I)
        with ZipFile(root) as archive:
            members = [
                name for name in archive.namelist()
                if pattern.fullmatch(Path(name).name)
            ]
            if len(members) != 1:
                raise ValueError(f"{root.name}: expected one {table} CSV, found {len(members)}")
            with TextIOWrapper(archive.open(members[0]), encoding="utf-8-sig", newline="") as source:
                yield from csv.DictReader(source)
        return
    files = list(root.rglob(f"{table}_2m.csv"))
    if len(files) != 1:
        raise ValueError(f"Expected one {table}_2m.csv, found {len(files)}")
    with files[0].open(encoding="utf-8-sig", newline="") as source:
        yield from csv.DictReader(source)


def build(root, month=None):
    waits = defaultdict(list)
    observations = defaultdict(list)
    for row in rows(root, "T_DTP_PSG_FLW_DPTGT_SNSR_DAT_E"):
        if month and not row["snsr_bdi_dt"].startswith(month):
            continue
        terminal = row["tmnl_cd"]
        gate = int(row["snsr_dat_dstgs_id"])
        zone = row["snsr_dat_dstgs_nm"].strip()
        if terminal == "P01":
            if not zone.startswith("Security Check"):
                continue
        elif terminal != "P02" or not re.fullmatch(rf"{gate}[A-D]", zone):
            continue
        try:
            value = float(row["que_brkaw_psg_wtng_psec_times"])
        except ValueError:
            continue
        if not 0 <= value < float("inf"):
            continue
        hour = row["snsr_bdi_dt"][:10]
        waits[terminal, gate, hour].append(value)
        observations[terminal, gate].append(value)

    thresholds = {
        key: quantiles(values, n=100, method="inclusive")[94]
        if len(values) > 1 else values[0]
        for key, values in observations.items()
    }
    days = {hour[:8] for _, _, hour in waits}
    counts = Counter()
    for number in (1, 2):
        terminal = f"P0{number}"
        prefix = f"T_DST_T{number}"
        passenger_ids = {
            row["psg_mstr_id"].strip()
            for row in rows(root, f"{prefix}_DPTC_PSG_INFO_E")
        } - {""}
        first_tag = {}
        device = re.compile(rf"ICN{number}D(\d{{3}})DG\d+")
        for row in rows(root, f"{prefix}_DPTGT_ETRY_PSG_INFO_E"):
            day = row["dptgt_etry_ymd"]
            passenger = row["psg_mstr_id"].strip()
            match = device.fullmatch(row["tmn_mstr_id"])
            in_period = day.startswith(month) if month else day in days
            if not in_period or passenger not in passenger_ids or not match:
                continue
            if row["dptgt_incmg_dvs_cd"] not in {"0800", "0802"}:
                continue
            hm = row["dptgt_etry_hm"].zfill(4)
            if not re.fullmatch(r"(?:[01][0-9]|2[0-3])[0-5][0-9]", hm):
                continue
            key = (int(match[1]), day, passenger)
            first_tag[key] = min(hm, first_tag.get(key, hm))
        counts.update(
            (terminal, gate, day + hm[:2])
            for (gate, day, _), hm in first_tag.items()
        )

    for terminal, gate, hour in sorted(waits.keys() | counts.keys()):
        key = terminal, gate, hour
        values = waits.get(key, [])
        p95 = thresholds.get((terminal, gate))
        trimmed = [value for value in values if value <= p95]
        count = counts[key]
        yield {
            "date": datetime.strptime(hour[:8], "%Y%m%d").date().isoformat(),
            "hour": int(hour[8:]),
            "terminal": {"P01": "T1", "P02": "T2"}[terminal],
            "departure_gate": gate,
            "tag_count": count,
            "sensor_count": len(values),
            "p95_seconds": p95,
            "sensor_count_p95": len(trimmed),
            "sensor_mean_seconds": mean(values) if values else None,
            "sensor_mean_seconds_p95": mean(trimmed) if trimmed else None,
            "matched_tags": count if values else 0,
            "matched_tags_p95": count if trimmed else 0,
            "weighted_seconds": count * mean(values) if values else 0,
            "weighted_seconds_p95": count * mean(trimmed) if trimmed else 0,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("."))
    parser.add_argument("--month", help="Limit sensor observations and tags to YYYYMM")
    parser.add_argument("--output", type=Path, default=Path("airport_wait_hourly.csv"))
    args = parser.parse_args()
    if args.month and not re.fullmatch(r"\d{4}(?:0[1-9]|1[0-2])", args.month):
        parser.error("--month must be YYYYMM")
    records = list(build(args.source, args.month))
    if not records:
        parser.error("No eligible sensor or tag data found")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=records[0])
        writer.writeheader()
        writer.writerows(records)
    print(f"{len(records):,} rows, {args.output.stat().st_size:,} bytes: {args.output}")
