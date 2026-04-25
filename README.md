# Sortify

Sortify is a personalized task-priority dashboard that turns messages, deadlines, and manual inputs into a ranked queue. It combines a React frontend, a Flask backend, and a priority pipeline that learns from user feedback over time.

## Production

Live app: https://thankful-stone-0c17fc20f.7.azurestaticapps.net/

## What the project does

- Connects message sources such as Gmail and Outlook
- Extracts task signals from raw messages
- Merges duplicate signals into canonical tasks
- Applies baseline scoring using deadline, sender, urgency, and task-type signals
- Personalizes ranking using onboarding context and learned behavior
- Shows users a task queue with rationale, action windows, and tags
- Feeds user actions back into the profile so prioritization improves over time

## Architecture

The project is split into three main parts:

- `frontend/`: React app for onboarding, queue display, settings, Kanban, and statistics
- `backend/`: Flask API for auth, integrations, onboarding, task actions, and pipeline orchestration
- `pipeline/`: extraction, deduplication, scoring, reasoning, post-processing, and profile learning

## High-level pipeline

The system flow is:

`raw messages -> task extraction -> deduplication -> baseline scoring -> personalization check -> reasoning -> task cards -> user feedback -> profile update`

In practice:

1. Linked providers store formatted messages.
2. The pipeline extracts structured task signals from those messages.
3. Similar signals are merged into canonical tasks.
4. Tasks receive a baseline priority score.
5. Onboarding context, calendar context, and profile history are used to personalize decisions.
6. Final task cards are saved and shown in the frontend.
7. User feedback updates the behavior profile for future runs.

## Repository structure

```text
task-priority-sorter/
|-- backend/
|   |-- app/
|   |-- config.py
|   |-- requirements.txt
|   `-- run.py
|-- frontend/
|   |-- src/
|   |-- package.json
|   `-- vite.config.js
|-- pipeline/
|   |-- src/pipeline/
|   |-- tests/
|   `-- pyproject.toml
|-- requirements.txt
`-- README.md
```

## Local development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

The Flask API runs at `http://127.0.0.1:5000`.

### Frontend

Open a second terminal:

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

The frontend runs at `http://localhost:5173`.

### Development workflow

- Keep the Flask server running in one terminal
- Keep the Vite dev server running in another terminal
- React hot reloads during development
- Flask restarts automatically in debug mode

## Core user flow

1. The user signs up or logs in.
2. The user completes onboarding preferences.
3. The user can optionally upload calendar context.
4. The user links message providers such as Gmail or Outlook.
5. The backend syncs messages and runs the priority pipeline.
6. The frontend displays prioritized task cards.
7. The user accepts, rejects, completes, or corrects task priority.
8. The learned profile updates and improves future ranking.

## Key features

### Personalized prioritization

Sortify starts with onboarding preferences, then gradually learns from real user behavior. The profile tracks patterns such as preferred task types, important entities, sender importance, tags, and action timing.

### Task extraction

The extractor turns unstructured message content into structured task signals by identifying:

- deadlines
- task verbs
- urgency terms
- sender roles
- task type
- topic or entity context

It also filters out likely noise such as spam, bulk newsletters, and irrelevant promotional messages.

### Calendar-aware context

Users can upload `.ics` files during onboarding or later in settings. The app uses this to extract busy windows, recurring notes, and a timetable summary for better action-window recommendations.

### Feedback loop

User actions on task cards are written back into the behavior profile. This lets the system move from generic ranking toward stronger personalization once enough observations are collected.

## Main API areas

### Onboarding

- `PUT /api/onboarding`
- `GET /api/onboarding/context`
- `POST /api/onboarding/calendar`
- `DELETE /api/onboarding/calendar`

### Tasks

- `POST /api/tasks/sync`
- `GET /api/tasks`
- `POST /api/tasks/<canonical_task_id>/feedback`
- `GET /api/tasks/profile`

### Integrations

- Gmail linking and sync endpoints
- Outlook linking and sync endpoints
- Telegram settings, linking, and test-message endpoints

## Testing

Backend and pipeline tests are included in the repository.

Examples:

```bash
cd backend
python -m pytest
```

```bash
cd pipeline
python -m pytest
```

## Notes

- Telegram inbound webhooks require a public HTTPS URL, not plain localhost.
- The pipeline stores both task output and learned profile state in the shared database layer.
- `GET /api/tasks/profile` is useful for debugging profile evolution during development.
