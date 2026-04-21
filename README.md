# task-priority-sorter

React + Flask setup for the hackathon project.

## Project structure

```text
task-priority-sorter/
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
