from __future__ import annotations

TARGET_REPS_MIN: int = 6
TARGET_REPS_MAX: int = 8
TARGET_SETS: int = 2
TARGET_RIR: int = 1
TRAINING_DAYS_PER_WEEK: int = 6
PHASE: str = "cut"  # cut | bulk | maintain
MAX_MUSCLE_FREQ_PER_WEEK: int = 4

# Key compound lifts used for strength-retention tracking and game plan flagging
ANCHOR_LIFTS: frozenset[str] = frozenset({
    "bench press", "incline bench press", "decline bench press",
    "squat", "front squat", "deadlift", "romanian deadlift", "sumo deadlift",
    "overhead press", "seated overhead press",
    "barbell row", "pendlay row", "t-bar row",
    "lat pulldown", "pull-up", "chin-up",
    "leg press", "hack squat",
})
