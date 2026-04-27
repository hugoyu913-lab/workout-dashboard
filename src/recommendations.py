from __future__ import annotations

from pathlib import Path

import pandas as pd

from config.profile import TARGET_REPS_MIN, TARGET_REPS_MAX, TARGET_SETS

EXERCISE_RECOMMENDATIONS_PATH = Path("config/exercise_recommendations.csv")
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_STABLE_CATEGORY_TERMS = ("machine", "supported", "cable", "pulldown", "row", "press")


def _load_exercise_recommendations(path: Path = EXERCISE_RECOMMENDATIONS_PATH) -> pd.DataFrame:
    columns = ["muscle_group", "category", "exercise", "priority"]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    try:
        recs = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame(columns=columns)
    recs.columns = [str(c).strip().lower() for c in recs.columns]
    for col in columns:
        if col not in recs.columns:
            recs[col] = ""
    recs = recs[columns].copy()
    recs["muscle_group_key"] = recs["muscle_group"].str.strip().str.lower()
    recs["priority_key"] = recs["priority"].str.strip().str.lower()
    recs["priority_rank"] = recs["priority_key"].map(_PRIORITY_ORDER).fillna(99)
    recs["stable_rank"] = recs.apply(
        lambda row: 0
        if any(
            term in f"{row['category']} {row['exercise']}".strip().lower()
            for term in _STABLE_CATEGORY_TERMS
        )
        else 1,
        axis=1,
    )
    return recs


def _focus_for_muscle_group(muscle_group: str) -> str:
    group = muscle_group.lower()
    if group in {"back", "biceps"}:
        return "Pull"
    if group in {"chest", "shoulders", "triceps"}:
        return "Push"
    if group == "legs":
        return "Legs"
    return "Upper"


def _rep_range_for_category(category: str) -> str:
    cat = category.lower()
    if any(t in cat for t in ("lateral", "rear", "fly", "calves", "core")):
        return "10-15"
    return f"{TARGET_REPS_MIN}-{TARGET_REPS_MAX}"


def _recommended_exercise_rows(
    muscle_groups: list[str],
    fatigue_sensitive: bool,
    limit: int = 3,
) -> list[dict[str, str]]:
    recs = _load_exercise_recommendations()
    if recs.empty:
        return []
    selected: list[dict[str, str]] = []
    used: set[str] = set()
    for group in muscle_groups:
        group_recs = recs[recs["muscle_group_key"] == group.lower()].copy()
        if group_recs.empty:
            continue
        sort_cols = (
            ["stable_rank", "priority_rank", "exercise"]
            if fatigue_sensitive
            else ["priority_rank", "exercise"]
        )
        for row in group_recs.sort_values(sort_cols).itertuples(index=False):
            exercise = str(row.exercise).strip()
            key = exercise.lower()
            if not exercise or key in used:
                continue
            selected.append({
                "muscle_group": str(row.muscle_group).strip(),
                "category": str(row.category).strip(),
                "exercise": exercise,
                "sets_reps": f"{TARGET_SETS} sets of {_rep_range_for_category(str(row.category))}",
            })
            used.add(key)
            if len(selected) >= limit:
                return selected
    return selected


def _least_trained_groups(work: pd.DataFrame, latest_week: pd.Timestamp) -> list[str]:
    if "MuscleGroup" not in work.columns:
        return ["back"]
    latest = work[work["Week"] == latest_week].dropna(subset=["MuscleGroup"]).copy()
    if latest.empty:
        return ["back"]
    frequency = (
        latest.assign(MuscleGroup=latest["MuscleGroup"].astype(str).str.lower())
        .groupby("MuscleGroup", as_index=False)["Date"]
        .nunique()
        .sort_values(["Date", "MuscleGroup"], ascending=[True, True])
    )
    return [
        str(row.MuscleGroup)
        for row in frequency.itertuples(index=False)
        if row.MuscleGroup not in {"other", "unknown"}
    ]


def build_recommendations(
    scores: list[dict[str, object]],
    frequency_flags: list[dict[str, object]],
    balance: dict[str, object],
) -> list[str]:
    recommendations: list[str] = []
    declining_rows = [item for item in scores if item["status"] == "declining"]
    declining_groups = sorted(
        {str(item.get("muscle_group", "")).lower() for item in declining_rows if item.get("muscle_group")}
    )
    for muscle_group in declining_groups[:2]:
        recommendations.append(
            f"{muscle_group.title()} exercises regressing - consider more recovery or a slight frequency increase."
        )
    for row in declining_rows[:3]:
        if row.get("same_weight_reps_down"):
            recommendations.append(
                f"{row['exercise']} reps dropped at the same weight - increase RIR by 1-2 or add recovery before pushing load."
            )
        else:
            recommendations.append(
                f"{row['exercise']} strength is regressing - keep load conservative and prioritize recovery this week."
            )
    for item in frequency_flags[:4]:
        muscle_group = str(item["muscle_group"])
        if item["status"] == "neglected":
            recommendations.append(
                f"{muscle_group.title()} not trained this week - add {TARGET_SETS} hard sets to preserve muscle."
            )
        else:
            recommendations.append(
                f"{muscle_group.title()} trained only once - increase frequency to preserve muscle."
            )
    for row in [
        item for item in scores
        if item["status"] == "stable" and item.get("maintained_strength")
    ][:2]:
        recommendations.append(f"{row['exercise']} strength maintained during cut - good.")
    progressing = [item for item in scores if item["status"] == "progressing"]
    if progressing and not recommendations:
        recommendations.append(
            f"{progressing[0]['exercise']} is progressing - keep 0-1 RIR but avoid adding unnecessary volume."
        )
    if not recommendations:
        low_bucket = str(balance.get("low_bucket", "pull"))
        recommendations.append(
            f"Maintain current loads and add one {low_bucket} exposure if recovery stays stable."
        )
    return recommendations[:6]


def build_suggested_exercises(
    frequency_flags: list[dict[str, object]],
    scores: list[dict[str, object]],
    recommendations: list[str],
) -> list[str]:
    recs = _load_exercise_recommendations()
    if recs.empty:
        return ["No exercise recommendation config found."]

    target_groups: list[tuple[str, bool]] = []
    seen_targets: set[str] = set()
    for row in frequency_flags:
        group = str(row.get("muscle_group", "")).strip().lower()
        if group and group not in seen_targets:
            target_groups.append((group, False))
            seen_targets.add(group)
    for row in scores:
        if row.get("status") != "declining":
            continue
        group = str(row.get("muscle_group", "")).strip().lower()
        if group and group not in seen_targets:
            target_groups.append((group, True))
            seen_targets.add(group)

    fatigue_high = any("risk" in item.lower() and "high" in item.lower() for item in recommendations)
    if any("reps dropped" in item.lower() or "recovery" in item.lower() for item in recommendations):
        fatigue_high = True

    output: list[str] = []
    used_exercises: set[str] = set()
    for group, regression_related in target_groups[:5]:
        group_recs = recs[recs["muscle_group_key"] == group].copy()
        if group_recs.empty:
            continue
        sort_cols = (
            ["stable_rank", "priority_rank", "exercise"]
            if (regression_related or fatigue_high)
            else ["priority_rank", "exercise"]
        )
        selected: list[str] = []
        for row in group_recs.sort_values(sort_cols).itertuples(index=False):
            exercise = str(row.exercise).strip()
            key = exercise.lower()
            if not exercise or key in used_exercises:
                continue
            selected.append(exercise)
            used_exercises.add(key)
            if len(selected) >= 3:
                break
        if selected:
            output.append(f"{group.title()}: {', '.join(selected)}")

    return output or ["No targeted exercise substitutions needed this week."]


def build_next_workout(
    work: pd.DataFrame,
    latest_week: pd.Timestamp,
    scores: list[dict[str, object]],
    frequency_flags: list[dict[str, object]],
    fatigue: dict[str, object],
    retention: dict[str, object],
) -> dict[str, object]:
    """Deterministic next-workout recommendation from pre-computed components."""
    fatigue_high = fatigue["risk"] == "High"
    fatigue_moderate = fatigue["risk"] == "Moderate"
    low_retention = float(retention.get("score", 0)) < 70 and int(retention.get("exercise_count", 0)) > 0

    gap_groups = [str(row["muscle_group"]).lower() for row in frequency_flags]
    declining_groups = [
        str(row.get("muscle_group", "")).lower()
        for row in scores
        if row.get("status") == "declining" and row.get("muscle_group")
    ]
    target_groups: list[str] = []
    for group in gap_groups + declining_groups:
        if group and group not in target_groups and group not in {"other", "unknown"}:
            target_groups.append(group)
    if not target_groups:
        target_groups = _least_trained_groups(work, latest_week)

    if fatigue_high:
        focus = "Recovery"
        reason = "Fatigue risk is high — next session should reduce recovery cost while preserving movement practice."
        intensity = "Train at 1-2 RIR. Avoid grinding reps and heavy compounds."
        exercises = _recommended_exercise_rows(target_groups, fatigue_sensitive=True, limit=3)
        if not exercises:
            exercises = [{
                "exercise": "Easy walk or mobility work",
                "sets_reps": "20-30 minutes",
                "category": "Recovery",
                "muscle_group": "Recovery",
            }]
    elif target_groups:
        primary_group = target_groups[0]
        focus = _focus_for_muscle_group(primary_group)
        if frequency_flags:
            reason = f"{primary_group.title()} frequency is below target and fatigue risk is {fatigue['risk'].lower()}."
        elif low_retention:
            reason = "Strength retention is below target; prioritize key movement patterns with conservative volume."
        else:
            reason = f"{primary_group.title()} is the least-trained or most recovery-sensitive area this week."
        intensity = "Train at 0-1 RIR on stable movements. Stop before form breaks."
        if fatigue_moderate or low_retention:
            intensity = "Train at 1 RIR. Avoid grinding reps."
        exercises = _recommended_exercise_rows(
            target_groups, fatigue_sensitive=(fatigue_moderate or low_retention), limit=3
        )
    else:
        focus = "Upper"
        reason = "Frequency, fatigue, and strength retention look acceptable; use a balanced low-volume session."
        intensity = "Train at 0-1 RIR, but avoid adding extra volume."
        exercises = _recommended_exercise_rows(["back", "chest", "shoulders"], fatigue_sensitive=False, limit=3)

    return {
        "recommended_focus": focus,
        "reason": reason,
        "suggested_exercises": [f"{r['exercise']} - {r['sets_reps']}" for r in exercises],
        "recommended_sets_reps": f"{TARGET_SETS} working sets per exercise",
        "intensity_guidance": intensity,
    }
