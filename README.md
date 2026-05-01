# Workout Dashboard - AI Training Coach

## Overview
Workout Dashboard is a Streamlit-based AI fitness analytics and coaching system that transforms raw workout logs and daily check-ins into actionable training decisions.

It combines performance data, recovery signals, and behavioral inputs to generate a daily training recommendation similar to a real coach.

## Core Idea
Instead of just tracking workouts, the system answers:

"What should I do today to maximize progress while avoiding burnout?"

## Key Features

### Training Decision Engine (v2)
Generates a daily recommendation:
- Train / Train Smart / Recovery
- Recommended split
- Intensity guidance
- Volume adjustments
- Confidence level
- Reasoning behind decision

Inputs:
- Readiness score
- Sleep
- Energy
- Soreness
- Stress
- Steps
- Strength regression signals
- Deload flags

### Readiness Scoring System
Dynamic score based on:
- Sleep quality
- Daily activity (steps)
- Energy levels
- Soreness and stress
- Combined recovery strain signals

### Workout Analytics
- Volume tracking
- PR detection
- Strength trends
- Muscle group frequency
- Performance grading

### Bodyweight & Recovery Tracking
- Bodyweight trends
- Weekly loss rate
- Sleep averages
- Recovery warnings

### Session Grading
Each workout is scored based on:
- Effort
- Volume
- Target adherence

## Data System
- Google Sheets integration for workouts + check-ins
- Flexible schema handling (backward compatible)
- Clean parsing + metrics pipeline

## Tech Stack
- Python
- Streamlit
- Pandas
- Google Sheets API

## Project Structure
- app.py -> main app
- src/coach.py -> decision engine + readiness logic
- src/metrics.py -> analytics + calculations
- src/sheets_client.py -> data access
- src/pages/dashboard.py -> UI dashboards

## AI Workflow System
This project uses a structured AI development loop:

Codex (builder) -> Reviewer (Claude/ChatGPT) -> Fix -> Verify -> Commit

Includes:
- Auto-trigger review loop
- Risk classification (low/medium/high)
- No-API fallback system
- AGENTS.md for consistent behavior

## Future Improvements
- Trend-based readiness scoring
- Adaptive training recommendations
- Automated deload detection
- Nutrition integration (separate module)
- Full automation of AI review loop

## Running the App
```bash
pip install -r requirements.txt
streamlit run app.py
```
