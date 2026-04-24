# Sortify

React + Flask setup for the hackathon project.

## Project structure

```text
sortify/
|-- backend/
|   |-- app/
|   |   `-- __init__.py
|   |-- .env.example
|   |-- config.py
|   |-- requirements.txt
|   `-- run.py
|-- frontend/
|   |-- src/
|   |-- .env.example
|   |-- index.html
|   |-- package.json
|   `-- vite.config.js
`-- README.md
```

## Backend setup

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
python run.py
```

The Flask app will run on `http://127.0.0.1:5000`.

If you want Telegram inbound bot messages to work, `localhost` is not enough by itself. Telegram can only call a public HTTPS webhook, so you also need to expose your backend and set `TELEGRAM_WEBHOOK_URL` to your public `https://.../api/telegram/webhook` address.

## Frontend setup

Open a second terminal:

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

The React app will run on `http://localhost:5173`.

## How development works

- Keep the Flask server running in one terminal.
- Keep the React dev server running in another terminal.
- You usually do not need to restart both after every code change. React hot reloads, and Flask restarts automatically in debug mode.

## Priority pipeline integration

The sibling `pipeline/` package now acts as middleware inside the Flask backend:

- email sync providers write formatted messages into `stored_emails`
- Flask reads `stored_emails` and passes those rows into the pipeline
- the pipeline writes prioritized task output tables into the same Neon database
- React reads the current task cards through Flask `/api/tasks`
- user feedback is posted back through Flask and stored in the pipeline profile tables

### Task endpoints

- `POST /api/tasks/sync`
  Runs the pipeline for the authenticated user using emails already stored in `stored_emails`.

- `GET /api/tasks`
  Returns the current prioritized task cards for the authenticated user.

- `POST /api/tasks/<canonical_task_id>/feedback`
  Sends one of `GOT_IT`, `RESCHEDULE`, `ALREADY_DONE`, or `WRONG_PRIORITY`.
  `WRONG_PRIORITY` also requires `direction` of `too_high` or `too_low`.

- `GET /api/tasks/profile`
  Returns the current learned profile snapshot for debugging.
