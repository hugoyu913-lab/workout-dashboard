from __future__ import annotations

TARGET_REPS_MIN: int = 6
TARGET_REPS_MAX: int = 8
TARGET_SETS: int = 2
TARGET_RIR: int = 1
TRAINING_DAYS_PER_WEEK: int = 6
PHASE: str = "cut"  # cut | bulk | maintain
TARGET_BODY_FAT: int = 10
MIN_MUSCLE_FREQ_PER_WEEK: int = 2
MAX_MUSCLE_FREQ_PER_WEEK: int = 4

DAILY_STEPS_GOAL: int = 10000
DAILY_CALORIES_TARGET: int = 2200
DAILY_PROTEIN_TARGET: int = 180
DAILY_CARBS_TARGET: int = 180
DAILY_FAT_TARGET: int = 60
DAILY_SLEEP_TARGET: float = 8
DAILY_SLEEP_MINIMUM: float = 6.5

CUT_RATE_MIN: float = 0.003
CUT_RATE_MAX: float = 0.01
IDEAL_CUT_RATE_MIN: float = 0.005
IDEAL_CUT_RATE_MAX: float = 0.008

# Key compound lifts used for strength-retention tracking and game plan flagging
ANCHOR_LIFTS: list[str] = [
    "Incline Dumbbell Press",
    "Chest Supported Row",
    "Lat Pulldown",
    "Leg Press",
    "Hack Squat",
    "Lateral Raise",
    "Bicep Curl Machine",
    "Triceps Pushdown",
]
