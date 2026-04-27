"""
Stream-parse data/export.xml and write per-metric daily CSVs to data/health/.

Metrics extracted:
  steps            daily total (deduplicated: per-minute max across sources)
  body_weight      daily mean  (lbs)
  resting_hr       daily mean  (bpm)
  hrv              daily mean  (ms SDNN)
  active_calories  daily sum   (Cal → stored as kcal, same unit)
  sleep            nightly total asleep hours + quality % (if stage data exists)
  nutrition        daily sum calories + protein
  vo2max           most recent reading per day

Run:
    python scripts\\parse_health.py
"""

from __future__ import annotations

import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
EXPORT_PATH = ROOT / "data" / "export.xml"
HEALTH_DIR = ROOT / "data" / "health"

# ── Record type → internal key ─────────────────────────────────────────────────

QUANTITY_TYPES = {
    "HKQuantityTypeIdentifierBodyMass":                 "body_weight",
    "HKQuantityTypeIdentifierStepCount":                "steps",
    "HKQuantityTypeIdentifierRestingHeartRate":         "resting_hr",
    "HKQuantityTypeIdentifierActiveEnergyBurned":       "active_calories",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "hrv",
    "HKQuantityTypeIdentifierDietaryEnergyConsumed":    "calories_in",
    "HKQuantityTypeIdentifierDietaryProtein":           "protein",
    "HKQuantityTypeIdentifierVO2Max":                   "vo2max",
}

SLEEP_TYPE = "HKCategoryTypeIdentifierSleepAnalysis"

ASLEEP_VALUES = frozenset({
    "HKCategoryValueSleepAnalysisAsleep",       # iOS < 16 catch-all
    "HKCategoryValueSleepAnalysisAsleepCore",
    "HKCategoryValueSleepAnalysisAsleepDeep",
    "HKCategoryValueSleepAnalysisAsleepREM",
})

QUALITY_VALUES = frozenset({
    "HKCategoryValueSleepAnalysisAsleepDeep",
    "HKCategoryValueSleepAnalysisAsleepREM",
})

# ── Timestamp parsing ─────────────────────────────────────────────────────────

def _ts(s: str) -> pd.Timestamp | None:
    try:
        ts = pd.Timestamp(s)
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        return ts
    except Exception:
        return None


# ── Accumulator buckets ───────────────────────────────────────────────────────
# steps: list of (date, minute_bucket, value)  — minute bucket for dedup
# weight: list of (date, value_lbs)
# rhr:   list of (date, value)
# hrv:   list of (date, value)
# acal:  list of (date, value)
# sleep: list of (wake_date, duration_h, stage)
# nutri: list of (date, category, value)
# vo2:   list of (date, value)

def parse(xml_path: Path) -> dict[str, list]:
    buckets: dict[str, list] = {
        "steps": [], "weight": [], "rhr": [], "hrv": [],
        "acal": [], "sleep": [], "nutri": [], "vo2": [],
    }

    n = 0
    t0 = time.time()

    with open(xml_path, "rb") as f:
        for _ev, el in ET.iterparse(f, events=("end",)):
            if el.tag != "Record":
                el.clear()
                continue

            rtype = el.get("type", "")
            key   = QUANTITY_TYPES.get(rtype)
            n    += 1

            if n % 50_000 == 0:
                elapsed = time.time() - t0
                print(f"  {n:,} records … {elapsed:.0f}s", flush=True)

            # ── Quantity records ───────────────────────────────────────
            if key is not None:
                start_ts = _ts(el.get("startDate", ""))
                if start_ts is None:
                    el.clear(); continue
                try:
                    val = float(el.get("value", "nan"))
                except ValueError:
                    el.clear(); continue

                unit = el.get("unit", "").lower()
                date = start_ts.date()

                if key == "body_weight":
                    if unit in ("kg", "kilogram", "kilograms"):
                        val *= 2.20462
                    buckets["weight"].append((date, val))

                elif key == "steps":
                    minute = start_ts.replace(second=0, microsecond=0)
                    buckets["steps"].append((date, minute, val))

                elif key == "resting_hr":
                    buckets["rhr"].append((date, val))

                elif key == "hrv":
                    buckets["hrv"].append((date, val))

                elif key == "active_calories":
                    buckets["acal"].append((date, val))

                elif key in ("calories_in", "protein"):
                    buckets["nutri"].append((date, key, val))

                elif key == "vo2max":
                    buckets["vo2"].append((date, val))

            # ── Sleep records ──────────────────────────────────────────
            elif rtype == SLEEP_TYPE:
                stage    = el.get("value", "")
                start_ts = _ts(el.get("startDate", ""))
                end_ts   = _ts(el.get("endDate", ""))
                if start_ts is None or end_ts is None:
                    el.clear(); continue
                dur_h = (end_ts - start_ts).total_seconds() / 3600.0
                if dur_h <= 0:
                    el.clear(); continue
                wake_date = end_ts.date()
                if stage in ASLEEP_VALUES:
                    buckets["sleep"].append((wake_date, dur_h, stage))

            el.clear()

    elapsed = time.time() - t0
    print(f"  Parsed {n:,} records in {elapsed:.1f}s", flush=True)
    return buckets


# ── Aggregators ────────────────────────────────────────────────────────────────

def agg_steps(rows: list) -> pd.DataFrame:
    """Daily step total; per-minute max across sources to avoid double-counting."""
    if not rows:
        return pd.DataFrame(columns=["date", "steps"])
    df = pd.DataFrame(rows, columns=["date", "minute", "value"])
    # Max per (date, minute) → handles iPhone+Watch same-interval overlap
    deduped = df.groupby(["date", "minute"])["value"].max().reset_index()
    daily = deduped.groupby("date")["value"].sum().reset_index()
    daily.columns = ["date", "steps"]
    daily["steps"] = daily["steps"].round().astype(int)
    return daily


def agg_simple_mean(rows: list, col: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", col])
    df = pd.DataFrame(rows, columns=["date", "value"])
    daily = df.groupby("date")["value"].mean().reset_index()
    daily.columns = ["date", col]
    return daily


def agg_simple_sum(rows: list, col: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", col])
    df = pd.DataFrame(rows, columns=["date", "value"])
    daily = df.groupby("date")["value"].sum().reset_index()
    daily.columns = ["date", col]
    return daily


def agg_sleep(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", "sleep_hours", "sleep_quality_pct"])
    df = pd.DataFrame(rows, columns=["date", "duration_h", "stage"])
    total   = df.groupby("date")["duration_h"].sum()
    quality = df[df["stage"].isin(QUALITY_VALUES)].groupby("date")["duration_h"].sum()
    result  = pd.DataFrame({"sleep_hours": total})
    result["sleep_quality_pct"] = (quality / total.replace(0, np.nan) * 100).round(1)
    result = result.reset_index()
    result.columns = ["date", "sleep_hours", "sleep_quality_pct"]
    return result


def agg_nutrition(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", "calories_kcal", "protein_g"])
    df = pd.DataFrame(rows, columns=["date", "category", "value"])
    cal  = df[df["category"] == "calories_in"].groupby("date")["value"].sum()
    prot = df[df["category"] == "protein"].groupby("date")["value"].sum()
    result = pd.DataFrame({"calories_kcal": cal, "protein_g": prot}).reset_index()
    result.columns = ["date", "calories_kcal", "protein_g"]
    return result


def agg_vo2max(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", "vo2max"])
    df = pd.DataFrame(rows, columns=["date", "value"])
    daily = df.groupby("date")["value"].mean().reset_index()
    daily.columns = ["date", "vo2max"]
    return daily


# ── Save helpers ───────────────────────────────────────────────────────────────

def save(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df.to_csv(path, index=False)
    print(f"  Saved {path.name}: {len(df):,} rows  "
          f"({df['date'].min().date()} to {df['date'].max().date()})")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not EXPORT_PATH.exists():
        print(f"ERROR: {EXPORT_PATH} not found.")
        sys.exit(1)

    size_mb = EXPORT_PATH.stat().st_size / 1e6
    print(f"Parsing {EXPORT_PATH.name} ({size_mb:.0f} MB) …")
    buckets = parse(EXPORT_PATH)

    print("\nAggregating & saving …")

    steps_df   = agg_steps(buckets["steps"])
    weight_df  = agg_simple_mean(buckets["weight"], "body_weight_lbs")
    rhr_df     = agg_simple_mean(buckets["rhr"],    "resting_hr_bpm")
    hrv_df     = agg_simple_mean(buckets["hrv"],    "hrv_ms")
    acal_df    = agg_simple_sum( buckets["acal"],   "active_calories_kcal")
    sleep_df   = agg_sleep(buckets["sleep"])
    nutri_df   = agg_nutrition(buckets["nutri"])
    vo2_df     = agg_vo2max(buckets["vo2"])

    save(steps_df,  HEALTH_DIR / "steps.csv")
    save(weight_df, HEALTH_DIR / "body_weight.csv")
    save(rhr_df,    HEALTH_DIR / "resting_hr.csv")
    save(hrv_df,    HEALTH_DIR / "hrv.csv")
    save(acal_df,   HEALTH_DIR / "active_calories.csv")
    save(sleep_df,  HEALTH_DIR / "sleep.csv")
    save(nutri_df,  HEALTH_DIR / "nutrition.csv")
    save(vo2_df,    HEALTH_DIR / "vo2max.csv")

    print("\nSummary:")
    print(f"  Steps:           {len(steps_df):>5,} days  avg {steps_df['steps'].mean():,.0f} steps/day")
    if not weight_df.empty:
        print(f"  Body weight:     {len(weight_df):>5,} entries  range {weight_df['body_weight_lbs'].min():.1f}–{weight_df['body_weight_lbs'].max():.1f} lbs")
    if not rhr_df.empty:
        print(f"  Resting HR:      {len(rhr_df):>5,} days  avg {rhr_df['resting_hr_bpm'].mean():.0f} bpm")
    if not hrv_df.empty:
        print(f"  HRV:             {len(hrv_df):>5,} days  avg {hrv_df['hrv_ms'].mean():.1f} ms")
    if not acal_df.empty:
        print(f"  Active calories: {len(acal_df):>5,} days  avg {acal_df['active_calories_kcal'].mean():,.0f} kcal/day")
    if not sleep_df.empty:
        avg_sleep = sleep_df["sleep_hours"].mean()
        print(f"  Sleep:           {len(sleep_df):>5,} nights  avg {avg_sleep:.1f} hrs")
    if not nutri_df.empty:
        print(f"  Nutrition:       {len(nutri_df):>5,} days  avg {nutri_df['calories_kcal'].mean():,.0f} kcal, {nutri_df['protein_g'].mean():.0f}g protein")
    if not vo2_df.empty:
        print(f"  VO2 Max:         {len(vo2_df):>5,} readings  range {vo2_df['vo2max'].min():.1f}–{vo2_df['vo2max'].max():.1f} mL/min·kg")

    print("\nDone.")


if __name__ == "__main__":
    main()
