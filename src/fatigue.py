from __future__ import annotations

from typing import Collection

import pandas as pd

from config.profile import MAX_MUSCLE_FREQ_PER_WEEK


def fatigue_risk_detector(
    df: pd.DataFrame,
    weeks: int = 3,
    deload_dates: Collection[pd.Timestamp] | None = None,
) -> dict[str, object]:
    empty: dict[str, object] = {
        "risk": "Low",
        "reasons": ["No repeat-performance fatigue signals detected."],
        "suggested_action": "Maintain current loads and recovery habits.",
    }
    if df.empty or "Date" not in df.columns or "Exercise" not in df.columns:
        return empty

    work = df.dropna(subset=["Date", "Exercise", "Weight", "Reps"]).copy()
    if work.empty:
        return empty

    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work = work.dropna(subset=["Date"])
    if work.empty:
        return empty

    if deload_dates:
        deload_weeks = {pd.Timestamp(d).to_period("W") for d in deload_dates}
        work = work[~work["Date"].dt.to_period("W").isin(deload_weeks)].copy()

    latest_date = work["Date"].max()
    cutoff = latest_date - pd.Timedelta(weeks=weeks)
    recent = work[work["Date"] >= cutoff].copy()
    if recent.empty:
        return empty

    agg_dict: dict[str, tuple[str, str]] = {
        "Weight": ("Weight", "max"),
        "Reps": ("Reps", "max"),
    }
    if "MuscleGroup" in recent.columns:
        agg_dict["MuscleGroup"] = ("MuscleGroup", "first")

    session_best = (
        recent.groupby(["Date", "Exercise"], as_index=False)
        .agg(**agg_dict)
        .sort_values(["Exercise", "Date"])
    )

    same_weight_rep_drops: list[str] = []
    regression_groups: dict[str, int] = {}
    for exercise, group in session_best.groupby("Exercise"):
        ordered = group.sort_values("Date").reset_index(drop=True)
        if len(ordered) < 2:
            continue
        for idx in range(1, len(ordered)):
            prev_row = ordered.iloc[idx - 1]
            curr_row = ordered.iloc[idx]
            if (
                pd.notna(prev_row["Weight"])
                and pd.notna(curr_row["Weight"])
                and pd.notna(prev_row["Reps"])
                and pd.notna(curr_row["Reps"])
                and abs(float(curr_row["Weight"]) - float(prev_row["Weight"])) < 0.01
                and float(curr_row["Reps"]) < float(prev_row["Reps"])
            ):
                same_weight_rep_drops.append(
                    f"{exercise}: reps dropped from {prev_row['Reps']:.0f} to "
                    f"{curr_row['Reps']:.0f} at {curr_row['Weight']:.0f} lbs."
                )
                mg = str(curr_row.get("MuscleGroup", "unknown")).strip().lower() or "unknown"
                regression_groups[mg] = regression_groups.get(mg, 0) + 1

    reasons: list[str] = []
    if same_weight_rep_drops:
        reasons.extend(same_weight_rep_drops[:3])

    clustered_groups = [
        g for g, count in sorted(regression_groups.items())
        if count >= 2 and g not in {"unknown", "other"}
    ]
    for g in clustered_groups:
        reasons.append(
            f"{g.title()} has {regression_groups[g]} same-load rep regressions in the recent window."
        )

    # Per-muscle-group weekly frequency check (replaces total-session count heuristic)
    freq_penalty = 0
    if "MuscleGroup" in recent.columns:
        freq_work = recent.copy()
        freq_work["Week"] = freq_work["Date"].dt.to_period("W").dt.start_time
        mg_weekly = (
            freq_work.dropna(subset=["MuscleGroup"])
            .groupby(["Week", "MuscleGroup"], as_index=False)["Date"]
            .nunique()
            .rename(columns={"Date": "Days"})
        )
        overfrequent = mg_weekly[
            (mg_weekly["Days"] > MAX_MUSCLE_FREQ_PER_WEEK)
            & (~mg_weekly["MuscleGroup"].str.lower().isin({"unknown", "other"}))
        ]
        for _, row in overfrequent.iterrows():
            week_str = (
                row["Week"].strftime("%b %d")
                if hasattr(row["Week"], "strftime")
                else str(row["Week"])
            )
            reasons.append(
                f"{str(row['MuscleGroup']).title()} trained {row['Days']}x in week of "
                f"{week_str} (>{MAX_MUSCLE_FREQ_PER_WEEK}x/week)."
            )
            freq_penalty += 1

    risk_points = len(same_weight_rep_drops) + len(clustered_groups) * 2 + freq_penalty
    if risk_points >= 4:
        risk = "High"
        suggested_action = (
            "Reduce fatigue: add recovery, increase RIR by 1-2, or trim intensity "
            "for regressing muscle groups."
        )
    elif risk_points >= 2:
        risk = "Moderate"
        suggested_action = (
            "Monitor recovery and avoid pushing load on exercises with same-weight rep drops."
        )
    else:
        risk = "Low"
        suggested_action = "Maintain current recovery habits and keep loads stable."

    return {
        "risk": risk,
        "reasons": reasons or list(empty["reasons"]),
        "suggested_action": suggested_action,
    }
