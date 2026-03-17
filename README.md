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

To deploy the agent to an employee's computer, you need to set up Python, install the required packages, configure the agent, and set it to run silently in the background.

**Prerequisites on the Employee PC:**
1. Install [Python 3.10+](https://www.python.org/downloads/windows/). **CRITICAL**: During the Python installation, you MUST check the box that says **"Add Python to PATH"**.
2. Copy the entire `/agent` directory from this repository to `C:\DDC\tools\agent` on the employee's PC.

**Installation & Configuration:**
1. Open the Django Dashboard on your server, go to **Settings**, and add the new Employee. This will generate a unique **Agent Token**.
2. On the employee PC, open a command prompt (as Administrator) and navigate to the agent folder:
   ```cmd
   cd C:\DDC\tools\agent
   ```
3. Install the required Python packages for the agent:
   ```cmd
   pip install mss requests pywin32
   ```
4. Configure `pywin32` for the system:
   ```cmd
   python Scripts\pywin32_postinstall.py -install
   ```
5. Edit the `config.json` file in the agent folder. Insert the generated token and your server's local network IP address:
   ```json
   {
       "server_url": "http://<YOUR_SERVER_IP>:8000",
       "agent_token": "PASTE_THE_TOKEN_HERE",
       "screenshot_interval_seconds": 300,
       "activity_report_interval_seconds": 60,
       "idle_threshold_seconds": 120
   }
   ```

**Running the Agent:**

* **Option A: Testing Mode (Visible)**
  Run this from the command prompt to see the agent's live logs and verify it's capturing/uploading data correctly:
  ```cmd
  python main.py
  ```

* **Option B: Production Mode (Silent Windows Service)**
  Run these commands as Administrator to install the agent as a background Windows Service that will start automatically every time the PC boots:
  ```cmd
  python service.py install
  python service.py start
  ```
  *(To stop or remove the service later, you can run `python service.py stop` or `python service.py remove`)*.

## Development Guidelines

Please refer to the root `DEVELOPMENT_WORKFLOW.md` for strict coding guidelines, git workflow, and protocols for modifying the codebase.

**Agent-Server Contract**: Any changes to the communication protocol (API endpoints, JSON payload structures, header formats) **must** be updated simultaneously on both the Server API views and the Agent's `server_comm.py`.

## Versioning
* Current Version: **Phase 1 Codebase**
