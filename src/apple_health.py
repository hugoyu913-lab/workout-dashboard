"""Apple Health export.xml parser and loader.

Parsing (one-time, ~5s on 354MB):
    from src.apple_health import parse_and_save, HEALTH_DIR, DEFAULT_EXPORT
    parse_and_save(DEFAULT_EXPORT, HEALTH_DIR)

Loading (fast, reads pre-built CSVs):
    from src.apple_health import load_health_data
    hd = load_health_data()
    hd.steps          # date, steps
    hd.resting_hr     # date, resting_hr_bpm
    hd.merged()       # all metrics joined on date

Streamlit sidebar widget:
    from src.apple_health import render_sidebar_widget
    hd = render_sidebar_widget()
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import streamlit as st

# ── Paths ─────────────────────────────────────────────────────────────────────

HEALTH_DIR = Path("data/health")
DEFAULT_EXPORT = Path("data/export.xml")

_CSVS = {
    "steps":           HEALTH_DIR / "steps.csv",
    "body_weight":     HEALTH_DIR / "body_weight.csv",
    "resting_hr":      HEALTH_DIR / "resting_hr.csv",
    "hrv":             HEALTH_DIR / "hrv.csv",
    "active_calories": HEALTH_DIR / "active_calories.csv",
    "sleep":           HEALTH_DIR / "sleep.csv",
    "nutrition":       HEALTH_DIR / "nutrition.csv",
    "vo2max":          HEALTH_DIR / "vo2max.csv",
}

# ── Apple Health record types ─────────────────────────────────────────────────

_QUANTITY_TYPES = {
    "HKQuantityTypeIdentifierBodyMass":                 "body_weight",
    "HKQuantityTypeIdentifierStepCount":                "steps",
    "HKQuantityTypeIdentifierRestingHeartRate":         "resting_hr",
    "HKQuantityTypeIdentifierActiveEnergyBurned":       "active_calories",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "hrv",
    "HKQuantityTypeIdentifierDietaryEnergyConsumed":    "calories_in",
    "HKQuantityTypeIdentifierDietaryProtein":           "protein",
    "HKQuantityTypeIdentifierVO2Max":                   "vo2max",
}

_SLEEP_TYPE = "HKCategoryTypeIdentifierSleepAnalysis"

_ASLEEP = frozenset({
    "HKCategoryValueSleepAnalysisAsleep",
    "HKCategoryValueSleepAnalysisAsleepCore",
    "HKCategoryValueSleepAnalysisAsleepDeep",
    "HKCategoryValueSleepAnalysisAsleepREM",
})

_QUALITY = frozenset({
    "HKCategoryValueSleepAnalysisAsleepDeep",
    "HKCategoryValueSleepAnalysisAsleepREM",
})


# ── HealthData container ──────────────────────────────────────────────────────

@dataclass
class HealthData:
    steps:           pd.DataFrame = field(default_factory=pd.DataFrame)
    body_weight:     pd.DataFrame = field(default_factory=pd.DataFrame)
    resting_hr:      pd.DataFrame = field(default_factory=pd.DataFrame)
    hrv:             pd.DataFrame = field(default_factory=pd.DataFrame)
    active_calories: pd.DataFrame = field(default_factory=pd.DataFrame)
    sleep:           pd.DataFrame = field(default_factory=pd.DataFrame)
    nutrition:       pd.DataFrame = field(default_factory=pd.DataFrame)
    vo2max:          pd.DataFrame = field(default_factory=pd.DataFrame)

    def has(self, name: str) -> bool:
        df = getattr(self, name, None)
        return isinstance(df, pd.DataFrame) and not df.empty

    def merged(self) -> pd.DataFrame:
        """All per-metric DataFrames outer-joined on date into one wide frame."""
        _order = ("steps", "body_weight", "resting_hr", "hrv",
                  "active_calories", "sleep", "nutrition", "vo2max")
        parts = []
        for name in _order:
            df = getattr(self, name)
            if isinstance(df, pd.DataFrame) and not df.empty:
                parts.append(df.set_index("date"))
        if not parts:
            return pd.DataFrame()
        base = parts[0]
        for p in parts[1:]:
            base = base.join(p, how="outer")
        return base.sort_index().reset_index()


# ── Timestamp helper ──────────────────────────────────────────────────────────

def _ts(s: str) -> pd.Timestamp | None:
    try:
        t = pd.Timestamp(s)
        return t.tz_convert("UTC").tz_localize(None) if t.tzinfo else t
    except Exception:
        return None


# ── Core iterparse ────────────────────────────────────────────────────────────

def _parse_records(xml_path: Path, progress_cb: Callable[[int], None] | None = None) -> dict:
    """Single-pass iterparse; returns raw accumulator buckets."""
    buckets: dict[str, list] = {
        "steps": [], "weight": [], "rhr": [], "hrv": [],
        "acal": [], "sleep": [], "nutri": [], "vo2": [],
    }
    n = 0
    with open(xml_path, "rb") as f:
        for _ev, el in ET.iterparse(f, events=("end",)):
            if el.tag != "Record":
                el.clear()
                continue
            n += 1
            if progress_cb and n % 50_000 == 0:
                progress_cb(n)

            rtype = el.get("type", "")
            key   = _QUANTITY_TYPES.get(rtype)

            if key is not None:
                start = _ts(el.get("startDate", ""))
                if start is None:
                    el.clear(); continue
                try:
                    val = float(el.get("value", "nan"))
                except ValueError:
                    el.clear(); continue
                unit = el.get("unit", "").lower()
                d = start.date()

                if key == "body_weight":
                    if unit in ("kg", "kilogram", "kilograms"):
                        val *= 2.20462
                    buckets["weight"].append((d, val))
                elif key == "steps":
                    minute = start.replace(second=0, microsecond=0)
                    buckets["steps"].append((d, minute, val))
                elif key == "resting_hr":
                    buckets["rhr"].append((d, val))
                elif key == "hrv":
                    buckets["hrv"].append((d, val))
                elif key == "active_calories":
                    buckets["acal"].append((d, val))
                elif key in ("calories_in", "protein"):
                    buckets["nutri"].append((d, key, val))
                elif key == "vo2max":
                    buckets["vo2"].append((d, val))

            elif rtype == _SLEEP_TYPE:
                stage = el.get("value", "")
                if stage not in _ASLEEP:
                    el.clear(); continue
                s = _ts(el.get("startDate", ""))
                e = _ts(el.get("endDate", ""))
                if s is None or e is None:
                    el.clear(); continue
                dur_h = (e - s).total_seconds() / 3600.0
                if dur_h > 0:
                    buckets["sleep"].append((e.date(), dur_h, stage))

            el.clear()

    if progress_cb:
        progress_cb(n)
    return buckets


# ── Per-metric aggregators ────────────────────────────────────────────────────

def _agg_steps(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", "steps"])
    df = pd.DataFrame(rows, columns=["date", "minute", "value"])
    deduped = df.groupby(["date", "minute"])["value"].max().reset_index()
    daily = deduped.groupby("date")["value"].sum().reset_index()
    daily.columns = ["date", "steps"]
    daily["steps"] = daily["steps"].round().astype(int)
    return daily


def _agg_mean(rows: list, col: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", col])
    df = pd.DataFrame(rows, columns=["date", "value"])
    out = df.groupby("date")["value"].mean().reset_index()
    out.columns = ["date", col]
    return out


def _agg_sum(rows: list, col: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", col])
    df = pd.DataFrame(rows, columns=["date", "value"])
    out = df.groupby("date")["value"].sum().reset_index()
    out.columns = ["date", col]
    return out


def _agg_sleep(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", "sleep_hours", "sleep_quality_pct"])
    df = pd.DataFrame(rows, columns=["date", "duration_h", "stage"])
    total   = df.groupby("date")["duration_h"].sum()
    quality = df[df["stage"].isin(_QUALITY)].groupby("date")["duration_h"].sum()
    out = pd.DataFrame({"sleep_hours": total})
    out["sleep_quality_pct"] = (quality / total.replace(0, np.nan) * 100).round(1)
    return out.reset_index().rename(columns={"index": "date"})


def _agg_nutrition(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", "calories_kcal", "protein_g"])
    df = pd.DataFrame(rows, columns=["date", "category", "value"])
    cal  = df[df["category"] == "calories_in"].groupby("date")["value"].sum()
    prot = df[df["category"] == "protein"].groupby("date")["value"].sum()
    out = pd.DataFrame({"calories_kcal": cal, "protein_g": prot}).reset_index()
    return out


def _agg_vo2(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", "vo2max"])
    df = pd.DataFrame(rows, columns=["date", "value"])
    out = df.groupby("date")["value"].mean().reset_index()
    out.columns = ["date", "vo2max"]
    return out


# ── Save / load CSVs ──────────────────────────────────────────────────────────

def _write_csv(df: pd.DataFrame, path: Path) -> pd.DataFrame:
    path.parent.mkdir(parents=True, exist_ok=True)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df.to_csv(path, index=False)
    return df


def parse_and_save(
    xml_path: Path = DEFAULT_EXPORT,
    health_dir: Path = HEALTH_DIR,
    progress_cb: Callable[[int], None] | None = None,
) -> HealthData:
    """Parse export.xml and write per-metric CSVs. Returns a loaded HealthData."""
    buckets = _parse_records(xml_path, progress_cb)

    steps   = _write_csv(_agg_steps(buckets["steps"]),                     health_dir / "steps.csv")
    weight  = _write_csv(_agg_mean(buckets["weight"], "body_weight_lbs"),   health_dir / "body_weight.csv")
    rhr     = _write_csv(_agg_mean(buckets["rhr"],    "resting_hr_bpm"),    health_dir / "resting_hr.csv")
    hrv     = _write_csv(_agg_mean(buckets["hrv"],    "hrv_ms"),            health_dir / "hrv.csv")
    acal    = _write_csv(_agg_sum( buckets["acal"],   "active_calories_kcal"), health_dir / "active_calories.csv")
    sleep   = _write_csv(_agg_sleep(buckets["sleep"]),                      health_dir / "sleep.csv")
    nutri   = _write_csv(_agg_nutrition(buckets["nutri"]),                  health_dir / "nutrition.csv")
    vo2     = _write_csv(_agg_vo2(buckets["vo2"]),                          health_dir / "vo2max.csv")

    return HealthData(
        steps=steps, body_weight=weight, resting_hr=rhr, hrv=hrv,
        active_calories=acal, sleep=sleep, nutrition=nutri, vo2max=vo2,
    )


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, parse_dates=["date"])
    except Exception:
        return pd.DataFrame()


def load_health_data(health_dir: Path = HEALTH_DIR) -> HealthData:
    """Load all per-metric CSVs from health_dir into a HealthData object."""
    return HealthData(
        steps           = _read_csv(health_dir / "steps.csv"),
        body_weight     = _read_csv(health_dir / "body_weight.csv"),
        resting_hr      = _read_csv(health_dir / "resting_hr.csv"),
        hrv             = _read_csv(health_dir / "hrv.csv"),
        active_calories = _read_csv(health_dir / "active_calories.csv"),
        sleep           = _read_csv(health_dir / "sleep.csv"),
        nutrition       = _read_csv(health_dir / "nutrition.csv"),
        vo2max          = _read_csv(health_dir / "vo2max.csv"),
    )


# ── Streamlit sidebar widget ──────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _load_cached() -> HealthData:
    return load_health_data()


def render_sidebar_widget() -> HealthData:
    """Render Apple Health status + re-parse button in the sidebar.

    Returns the current HealthData (from cache or freshly parsed).
    """
    hd = _load_cached()

    with st.sidebar.expander("Apple Health", expanded=False):
        if hd.has("steps"):
            s = hd.steps
            st.caption(
                f"{s['date'].min().date()} to {s['date'].max().date()}  "
                f"| {len(s):,} step-days"
            )
            parts = []
            if hd.has("resting_hr"):
                parts.append(f"HR {len(hd.resting_hr)}d")
            if hd.has("hrv"):
                parts.append(f"HRV {len(hd.hrv)}d")
            if hd.has("sleep"):
                parts.append(f"Sleep {len(hd.sleep)}n")
            if hd.has("nutrition"):
                parts.append(f"Nutrition {len(hd.nutrition)}d")
            if parts:
                st.caption("  |  ".join(parts))
        else:
            st.caption("No health data loaded.")

        export_path = Path("data/export.xml")
        btn_label = "Re-parse export.xml" if hd.has("steps") else "Parse export.xml"
        if export_path.exists():
            if st.button(btn_label, key="btn_reparse_health"):
                _load_cached.clear()
                placeholder = st.empty()
                t0 = time.time()

                def _progress(n: int) -> None:
                    placeholder.caption(f"Parsing... {n:,} records")

                hd = parse_and_save(export_path, HEALTH_DIR, progress_cb=_progress)
                _load_cached.clear()
                placeholder.success(f"Parsed in {time.time()-t0:.1f}s")
                st.rerun()
        else:
            st.caption("Place export.xml in data/ to enable parsing.")

    return hd
