from __future__ import annotations

from typing import Collection

import pandas as pd

from config.profile import ANCHOR_LIFTS


def _normalise_exercise(name: str) -> str:
    return str(name).strip().lower()


def _anchor_lift_names() -> set[str]:
    if isinstance(ANCHOR_LIFTS, dict):
        anchors = [lift for lifts in ANCHOR_LIFTS.values() for lift in lifts]
    else:
        anchors = list(ANCHOR_LIFTS)
    return {_normalise_exercise(lift) for lift in anchors}


def fatigue_risk_detector(
    df: pd.DataFrame,
    weeks: int = 3,
    deload_dates: Collection[pd.Timestamp] | None = None,
    checkins: pd.DataFrame | None = None,
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

    # Deload suppression — filter deload weeks from ALL workout-based signals
    deload_periods: set = set()
    if deload_dates:
        deload_periods = {pd.Timestamp(d).to_period("W") for d in deload_dates}
        work = work[~work["Date"].dt.to_period("W").isin(deload_periods)].copy()

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
    anchor_rep_drops: list[str] = []
    regression_dates_by_group: dict[str, list] = {}
    anchor_names = _anchor_lift_names()

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
                message = (
                    f"{exercise}: reps dropped from {prev_row['Reps']:.0f} to "
                    f"{curr_row['Reps']:.0f} at {curr_row['Weight']:.0f} lbs."
                )
                if _normalise_exercise(exercise) in anchor_names:
                    anchor_rep_drops.append(f"Anchor lift regression - {message}")
                else:
                    same_weight_rep_drops.append(message)
                mg = str(curr_row.get("MuscleGroup", "unknown")).strip().lower() or "unknown"
                if mg not in {"unknown", "other"}:
                    regression_dates_by_group.setdefault(mg, []).append(curr_row["Date"])

    # Muscle groups with 2+ regressions within any 14-day window
    clustered_groups: list[str] = []
    for mg, dates in sorted(regression_dates_by_group.items()):
        if len(dates) < 2:
            continue
        dates_sorted = sorted(set(pd.Timestamp(d) for d in dates))
        for i in range(len(dates_sorted) - 1):
            if (dates_sorted[i + 1] - dates_sorted[i]).days <= 14:
                clustered_groups.append(mg)
                break

    reasons: list[str] = []
    if anchor_rep_drops:
        reasons.extend(anchor_rep_drops[:3])
    if same_weight_rep_drops:
        remaining = max(0, 3 - len(reasons))
        reasons.extend(same_weight_rep_drops[:remaining])
    for g in clustered_groups:
        count = len(regression_dates_by_group[g])
        reasons.append(
            f"{g.title()} has {count} same-load rep regressions within 14 days."
        )

    # Checkin-based signals (suppressed during deload weeks)
    checkin_reasons: list[str] = []
    if checkins is not None and not checkins.empty and "Date" in checkins.columns:
        c = checkins.copy()
        c["Date"] = pd.to_datetime(c["Date"], errors="coerce")
        c = c.dropna(subset=["Date"]).sort_values("Date")
        if not c.empty:
            latest_row = c.iloc[-1]
            in_deload = bool(
                deload_periods
                and latest_row["Date"].to_period("W") in deload_periods
            )
            if not in_deload:
                sleep = pd.to_numeric(latest_row.get("SleepHours"), errors="coerce")
                energy = pd.to_numeric(latest_row.get("Energy"), errors="coerce")
                soreness = pd.to_numeric(latest_row.get("Soreness"), errors="coerce")
                if pd.notna(sleep) and float(sleep) < 6:
                    checkin_reasons.append(
                        f"Sleep was {float(sleep):.1f}h (below 6h threshold)."
                    )
                if pd.notna(energy) and float(energy) <= 2:
                    checkin_reasons.append(
                        f"Energy level is {float(energy):.0f}/10 (critically low)."
                    )
                if pd.notna(soreness) and float(soreness) >= 4:
                    checkin_reasons.append(
                        f"Soreness is {float(soreness):.0f}/10 (elevated)."
                    )
    reasons.extend(checkin_reasons)

    # Risk scoring: any anchor regression triggers High immediately
    if anchor_rep_drops:
        risk = "High"
        suggested_action = (
            "Anchor lift regression detected — deload or form check recommended immediately."
        )
    else:
        risk_points = (
            len(same_weight_rep_drops)
            + len(clustered_groups) * 2
            + len(checkin_reasons)
        )
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
