# EMP Monitor

A custom-built, locally-hostable employee monitoring system designed for Windows environments. It consists of a lightweight Windows agent for data capture and a centralized Django web dashboard for administration and visualization.

## Architecture

The system uses a two-component architecture:
1. **Windows Agent** (`/agent`): A Python script capable of running as a Windows Service. It captures screenshots, tracks active/idle time, and monitors foreground applications. Data is transmitted to the server via HTTPS.
2. **Django Server** (`/server`): A web application that receives agent data, stores it, and provides an administrative dashboard to monitor employee productivity.

## Features (Phase 1)

* **Multi-Monitor Screenshots**: Automatically captures all connected displays at configurable intervals.
* **Activity & Idle Tracking**: Uses the Windows API to accurately detect idle time based on keyboard/mouse input thresholds.
* **Application Tracking**: Logs the active foreground application and window title to determine app usage time.
* **Productivity Rules**: Categorize applications or websites (e.g., `github.com`, `code.exe`) as Productive, Unproductive, or Neutral.
* **Offline Resilience**: If the server is unreachable, the agent queues screenshots and activity logs locally and flushes them up to the server once the connection is restored.
* **Centralized Configuration**: Agent settings (screenshot intervals, tracking toggles) are managed from the server and pulled periodically by the agents.

## Tech Stack

* **Server**: Python 3.10+, Django 6.0, Django REST Framework, SQLite (Development) / PostgreSQL (Production)
* **Agent**: Python 3.10+, `mss` (screenshots), `pywin32` (Windows API & Service wrapper), `requests`
* **Frontend**: Vanilla CSS with modern variables, flexbox, and grid (no external CSS framework overhead).

## Setup & Installation

### 1. Server Setup
```bash
# Clone the repository
git clone https://github.com/HannesBlulite/emp-monitor.git
cd emp-monitor

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run migrations & create an admin user
cd server
python manage.py migrate
python manage.py createsuperuser

# Start the development server
# To allow agents on the local LAN network to connect, run on '0.0.0.0:8000'
python manage.py runserver 0.0.0.0:8000
```
*(Note: To run on your local network, ensure `ALLOWED_HOSTS` in `server/empmonitor_server/settings.py` includes your server's local IP address or `*` for development).*

### 2. Agent Setup (Employee PC)
1. Open the Django Dashboard, go to **Settings**, and add an new Employee. This will generate a unique **Agent Token**.
2. Copy the `/agent` directory to the employee's machine.
3. Edit `agent/config.json` and insert the generated token and the server's network URL:
```json
{
    "server_url": "http://<YOUR_SERVER_IP>:8000",
    "agent_token": "PASTE_THE_TOKEN_HERE",
    "screenshot_interval_seconds": 300,
    "activity_report_interval_seconds": 60,
    "idle_threshold_seconds": 120
}
```
4. Run the Agent:
   * **Console Mode** (Testing): `python main.py`
   * **Windows Service Mode**: `python service.py install` followed by `python service.py start`

## Development Guidelines

Please refer to the root `DEVELOPMENT_WORKFLOW.md` for strict coding guidelines, git workflow, and protocols for modifying the codebase.

**Agent-Server Contract**: Any changes to the communication protocol (API endpoints, JSON payload structures, header formats) **must** be updated simultaneously on both the Server API views and the Agent's `server_comm.py`.

## Versioning
* Current Version: **Phase 1 Codebase**
