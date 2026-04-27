from __future__ import annotations

from typing import Collection

import pandas as pd

from config.profile import DAILY_CALORIES_TARGET, DAILY_PROTEIN_TARGET
from src.retention import strength_retention_score


def compute_guardrails(
    df: pd.DataFrame,
    checkins: pd.DataFrame,
    deload_dates: Collection[pd.Timestamp] | None = None,
) -> dict[str, object]:
    """Composite cut-risk score.

    Weights:
      Retention component  (max 40 pts): (100 - retention_score) * 0.4
      Pace component       (raw pts):    ideal=0, slow=-10, aggressive=+30
      Recovery component   (raw pts):    sleep<6h +20, soreness>7 +15, stress>7 +15

    Thresholds: Green 0-30 / Yellow 31-60 / Red 61+
    """
    retention = strength_retention_score(df, deload_dates=deload_dates)
    retention_score = float(retention.get("score", 50))
    retention_component = (100.0 - retention_score) * 0.4  # 0-40

    # Resolve checkin metrics without a circular import
    cut_pace = "unknown"
    avg_sleep: float | None = None
    avg_soreness: float | None = None
    avg_stress: float | None = None

    if not checkins.empty:
        df_c = checkins.sort_values("Date").copy() if "Date" in checkins.columns else checkins.copy()
        recent = df_c.tail(14)
        if "Bodyweight" in df_c.columns:
            weights = df_c["Bodyweight"].dropna()
            if len(weights) >= 2:
                bw_rolling = df_c["Bodyweight"].rolling(7, min_periods=1).mean()
                current_avg = bw_rolling.dropna().iloc[-1] if not bw_rolling.dropna().empty else None
                if len(bw_rolling.dropna()) >= 8:
                    previous_avg = bw_rolling.dropna().iloc[-8]
                    weekly_rate = float(previous_avg) - float(current_avg) if current_avg is not None else None
                else:
                    first = float(weights.iloc[0])
                    last = float(weights.iloc[-1])
                    days = max((df_c["Date"].dropna().iloc[-1] - df_c["Date"].dropna().iloc[0]).days, 1) if "Date" in df_c.columns else 7
                    weekly_rate = (first - last) / days * 7
                if weekly_rate is not None:
                    if pd.isna(weekly_rate):
                        cut_pace = "unknown"
                    elif weekly_rate < 0.25:
                        cut_pace = "slow"
                    elif weekly_rate <= 1.25:
                        cut_pace = "ideal"
                    else:
                        cut_pace = "aggressive"

        if "SleepHours" in recent.columns:
            val = recent["SleepHours"].dropna().mean()
            if pd.notna(val):
                avg_sleep = float(val)
        if "Soreness" in recent.columns:
            val = recent["Soreness"].dropna().mean()
            if pd.notna(val):
                avg_soreness = float(val)
        if "Stress" in recent.columns:
            val = recent["Stress"].dropna().mean()
            if pd.notna(val):
                avg_stress = float(val)

    pace_risk = {"ideal": 0, "slow": -10, "aggressive": 30, "unknown": 0}.get(cut_pace, 0)

    recovery_raw = 0
    recovery_flags: list[str] = []
    if avg_sleep is not None and avg_sleep < 6:
        recovery_raw += 20
        recovery_flags.append(f"avg sleep {avg_sleep:.1f}h (<6h)")
    if avg_soreness is not None and avg_soreness > 7:
        recovery_raw += 15
        recovery_flags.append(f"avg soreness {avg_soreness:.1f}/10 (>7)")
    if avg_stress is not None and avg_stress > 7:
        recovery_raw += 15
        recovery_flags.append(f"avg stress {avg_stress:.1f}/10 (>7)")

    nutrition_flags: list[str] = []
    if not checkins.empty:
        df_c = checkins.sort_values("Date").copy() if "Date" in checkins.columns else checkins.copy()
        if "Protein" in df_c.columns:
            protein = pd.to_numeric(df_c["Protein"], errors="coerce").dropna()
            if len(protein) >= 3 and protein.tail(3).lt(DAILY_PROTEIN_TARGET * 0.8).all():
                nutrition_flags.append("Low protein - muscle loss risk on this cut")
        if "Calories" in df_c.columns:
            calories = pd.to_numeric(df_c["Calories"], errors="coerce").dropna()
            if not calories.empty:
                latest_calories = float(calories.iloc[-1])
                if latest_calories < DAILY_CALORIES_TARGET * 0.7:
                    nutrition_flags.append("Too aggressive deficit - increase food intake")
                if latest_calories > DAILY_CALORIES_TARGET * 1.1:
                    nutrition_flags.append("Surplus detected - check against cut goal")

    composite = max(0.0, retention_component + pace_risk + recovery_raw)
    composite_rounded = round(composite)

    if composite_rounded <= 30:
        level = "Green"
        color = "#22c55e"
        bg = "#0a1f10"
        border = "#166534"
        action = "Training load is sustainable. Maintain current approach."
    elif composite_rounded <= 60:
        level = "Yellow"
        color = "#f59e0b"
        bg = "#1c1500"
        border = "#92400e"
        action = "Moderate risk. Consider reducing training intensity or improving sleep/recovery."
    else:
        level = "Red"
        color = "#ef4444"
        bg = "#1f0a0a"
        border = "#7f1d1d"
        action = "High risk. Reduce cut aggression, add a recovery day, or take a deload."

    return {
        "composite_risk": composite_rounded,
        "level": level,
        "color": color,
        "bg": bg,
        "border": border,
        "action": action,
        "retention_score": retention_score,
        "cut_pace": cut_pace,
        "recovery_flags": recovery_flags + nutrition_flags,
        "nutrition_flags": nutrition_flags,
    }
