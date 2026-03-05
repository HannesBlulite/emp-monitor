# DEVELOPMENT WORKFLOW RULES — EMP MONITOR

> **Local environment:** Windows 10 + PowerShell (uses `;` to chain commands, NOT `&&`)
> **Project:** Custom Employee Monitoring System (Windows Agent + Web Dashboard)
> **Stack:** Python (Windows Service Agent) + Django + PostgreSQL + HTML/CSS/JS (Dashboard)
> **Repository:** Single `main` branch for routine work; feature branches for larger changes

---

## 1. Golden Rules

These are non-negotiable. Every rule applies to every change, every session.

### 1.1 DO NOT REMOVE WORKING CODE BY DEFAULT

Only add or modify existing logic unless explicitly instructed otherwise.

### 1.2 CONTROLLED REMOVAL RULE

Code may only be removed if:

* The user explicitly instructs removal, **OR**
* The code is provably dead/unreachable/unused, and the agent documents:
  * what was removed
  * why it was safe to remove

### 1.3 VERIFY BEFORE AND AFTER EDITS

Always confirm file integrity around changes (line counts + function existence). See Section 4 for the exact commands.

### 1.4 TARGETED CHANGES FIRST

Prefer surgical edits. Avoid large rewrites unless justified.

### 1.5 FULL-FILE REWRITES (EXCEPTION RULE)

Full rewrites are allowed ONLY when:

* explicitly requested by the user, OR
* the change is purely mechanical (formatting/structure) with **no logic changes**, AND
* public interfaces and behavior remain identical.

### 1.6 FORWARD PROGRESS RULE

Prefer forward progress. If a change destabilizes working behavior, revert quickly and continue using a safer approach.

### 1.7 SCOPE CONTAINMENT RULE

Only change what was requested. If the fix requires touching 2 files, touch 2 files.

* Do NOT upgrade libraries, swap technologies, or refactor adjacent code unless the user explicitly asks.
* Do NOT introduce new dependencies when the existing approach works -- fix the existing code first.
* If the agent believes a broader change is warranted, it MUST **propose it first and wait for approval** before writing any code.

### 1.8 ROLLBACK CRITERIA

If a deployed change causes an error:

1. Revert the commit immediately: `git revert HEAD`
2. Push the revert.
3. THEN debug locally and fix forward with a new commit.

Do not fix-forward while users are hitting errors.

### 1.9 UNDERSTAND BEFORE MODIFYING

Before editing any file, the agent MUST read the relevant sections of that file to understand the existing logic. Never edit based on assumptions about what the code "probably" does.

* Read the function/block being changed.
* Read any callers or modules that depend on it.
* If the file is large (500+ lines), read at least the surrounding context (50 lines above and below the target).

**Project-specific read chain:**

| Editing...                     | Also read...                                                                              |
| ------------------------------ | ----------------------------------------------------------------------------------------- |
| Agent code (screenshot/tracking) | The server API endpoint that receives the data                                          |
| A Django view                  | The URL conf + the template(s) to verify context variables and URL names                  |
| A template                     | The view to confirm which context variables are available                                  |
| A model                        | Views, serializers, forms, or admin classes that reference its fields                      |
| Agent-server communication     | Both the agent-side sender AND the server-side receiver                                   |
| JS on a page                   | The template to confirm element IDs, `data-` attributes, inline scripts                  |
| CSS                            | The template(s) that use the affected classes                                             |
| Windows Service code           | The service installer/registration and any scheduled tasks                                |

### 1.10 WHEN IN DOUBT, ASK

If the agent is unsure about the intended behavior, existing architecture, or impact of a change, it MUST ask the user for clarification rather than guessing.

* "I'm not sure if this function is called elsewhere -- should I check?" is always better than a silent assumption.
* This applies to business logic, agent behavior, API design, and deployment steps.

### 1.11 NO SECRETS IN VERSION CONTROL

Never commit files that contain secrets or credentials:

* `.env`, `credentials.json`, API keys, database passwords, SSH keys, agent auth tokens.
* If the user asks to commit such a file, warn them explicitly before proceeding.
* The repository SHOULD have a `.env.example` with placeholder values documented.

### 1.12 CSS AND TEMPLATE CONVENTIONS

* All CSS must live in dedicated stylesheet files (e.g. `static/css/style.css`). No inline `<style>` blocks in templates. No `style="..."` attributes.
* If component-level scoping is unavoidable, use BEM-style class names -- never wildcard overrides.
* Templates must always use `{% load static %}` and `{% url %}` -- no hard-coded paths.
* Any override must justify itself in the commit message.

### 1.13 HARD STOP GATE -- DO NOT GUESS

If any of the following facts are unknown or ambiguous, the agent MUST stop and ask before writing code:

* **Model field names** -- never assume a column is called `name` vs `employee_name` vs `display_name`.
* **File paths** -- never assume a template lives at a path; confirm by searching.
* **URL names** -- never assume a URL is named `dashboard:home`; read the URL conf.
* **Element IDs** -- never assume a button is `id="saveBtn"`; read the template.
* **Agent protocol** -- never assume the data format the agent sends; read the agent code.
* **Business logic** -- never assume how productivity is calculated, what categories exist, or what thresholds apply.

**The rule:** If you would need to type a name, path, field, or ID that you have not read from the actual codebase in this session, STOP. Search or read first. If you still cannot confirm it, ask the user.

Guessing is how bugs get deployed.

### 1.14 AGENT-SERVER CONTRACT RULE

The Windows agent and the Django server communicate over HTTPS. Any change to the data format, endpoints, or authentication protocol on one side MUST be reflected on the other side in the same commit/PR.

* Never change the agent's upload format without updating the server's receiver.
* Never change the server's API contract without updating the agent code.
* Document all API endpoints and their expected payloads in the project README or a dedicated `API.md`.

### 1.15 SECURITY-FIRST RULE

This project involves monitoring software that runs on company-owned hardware. Security is paramount:

* All agent-to-server communication MUST use HTTPS with proper certificate validation.
* Agent authentication tokens must be stored securely (Windows Credential Manager or encrypted config).
* Screenshots must be transmitted encrypted and stored with access controls.
* Never log, print, or expose sensitive data (passwords, tokens, screenshot contents) in plain text.
* The agent must ONLY run on company-owned equipment as authorized by the employer.

---

## 2. Session Startup Protocol

When the user says "Follow the workflow" or references this file, the agent MUST:

1. **Read this document** in full before writing any code.
2. **Run `git status`** to understand the current state of the repo (uncommitted changes, branch, etc.).
3. **Confirm the task** -- restate what the user is asking in one sentence and wait for confirmation if it is ambiguous.
4. **Plan the steps** -- for anything beyond a trivial 1-2 step change, create a task checklist before writing code.

### Re-anchoring During Long Sessions

If the conversation exceeds ~20 exchanges, the agent should re-read this file and explicitly state: "Re-read workflow rules to stay anchored." This prevents context drift.

---

## 3. Required Change Reporting

After any modification, the agent MUST output:

* What was added
* What was modified
* What was removed (if anything)
* Why the change was safe
* **Which component was affected** (Agent, Server, Dashboard, or Shared)

No silent edits. Ever.

---

## 4. Development Workflow

### 4.1 Pre-Edit Integrity Check (Local -- PowerShell)

```powershell
$beforeCount = (Get-Content ".\path\to\file.py").Count
Write-Host "Before: $beforeCount lines"
```

### 4.2 Post-Edit Verification (Local -- PowerShell)

```powershell
$afterCount = (Get-Content ".\path\to\file.py").Count
Write-Host "After: $afterCount lines (diff: $($afterCount - $beforeCount))"

# Verify the target function still exists
Select-String -Path ".\path\to\file.py" -Pattern "def function_name"
```

### 4.3 Backend Sanity Check (Local -- PowerShell)

After any Django change, run before committing:

```powershell
python manage.py check
```

This catches import errors, model misconfigurations, and URL resolution failures in under 2 seconds.

### 4.4 Agent Sanity Check (Local -- PowerShell)

After any Windows agent change, run before committing:

```powershell
# Syntax check the agent code
python -m py_compile agent\main.py

# Run agent tests if they exist
python -m pytest agent\tests\ -v
```

### 4.5 Task Management

For any task involving more than two files or three steps, the agent MUST create and maintain a structured task checklist before starting work.

1. **Plan first** -- list all steps before writing any code.
2. **One at a time** -- work on only ONE step at a time.
3. **Immediate completion** -- mark each step done as soon as the edit/verification for that step is complete.
4. **No scope additions** -- do not add new steps mid-task without proposing them to the user first.

### 4.6 Minimal Test Requirement

Every change must have at least ONE verifiable check before it is committed. The minimum acceptable levels, in order of preference:

| Level                    | What                                                              | When to use                                                        |
| ------------------------ | ----------------------------------------------------------------- | ------------------------------------------------------------------ |
| 1. Automated test        | A failing test that now passes                                    | New features, bug fixes with clear input/output                    |
| 2. `manage.py check`    | Catches import/config/URL errors                                  | Any Django change                                                  |
| 3. `py_compile` check   | Catches syntax errors in agent code                               | Any agent-side Python change                                       |
| 4. Manual trace          | Agent reads the full code path and states the expected behavior   | JS/template-only changes where other checks add nothing            |

**Rule:** If the agent cannot perform at least Level 4, the change is not ready to commit. State which level was used in the change report.

---

## 5. Local Verification Before Deploy -- CRITICAL

**Everything must work locally first, before any commit or deployment.**

Before any `git push`, the agent MUST:

1. **Run Django checks** -- `python manage.py check` and apply any pending migrations locally.
2. **Compile-check agent code** -- `python -m py_compile` on all modified agent files.
3. **Trace the code path** -- read through the affected logic end-to-end and confirm it is correct.
4. **State what to test** -- list the specific actions that exercise the change (e.g. "install agent on test PC, wait for screenshot interval, verify screenshot appears in dashboard").
5. **Check for side effects** -- verify that no other functionality was broken.
6. **If agent-server changes** -- confirm both ends of the API contract match (request format, response format, error handling).
7. **If JS/frontend changes** -- confirm no syntax errors, all referenced DOM element IDs exist in the template.
8. **If CSS changes** -- confirm the styles are in the stylesheet, not inline.

Never deploy a change you haven't verified at least on paper. If in doubt, ask the user to test locally first.

### 5.1 Definition of Done

A change is NOT done until ALL of the following are true:

- [ ] All pending migrations have been applied locally (if Django changes) without errors.
- [ ] Agent code compiles without syntax errors (if agent changes).
- [ ] The code has been read back after editing (not just written and assumed correct).
- [ ] Pre/post line counts have been checked (Section 4.1 / 4.2).
- [ ] `python manage.py check` passes (or Level 4 trace completed for non-Django changes).
- [ ] The change report has been output (Section 3).
- [ ] The code path has been traced end-to-end (Section 5, item 3).
- [ ] Specific test actions have been stated to the user (Section 5, item 4).
- [ ] Agent-server API contract is consistent on both sides (if communication changes).
- [ ] No new inline `<style>` or `style="..."` attributes exist in templates.
- [ ] No secrets, debug prints, or `console.log()` statements were left in.
- [ ] No hardcoded server URLs, tokens, or credentials in agent code.
- [ ] The commit message follows the `[Feature/Fix/Agent/Server] description` format.

If any box cannot be checked, the change is not ready to push.

---

## 6. Git Workflow

### DO NOT USE `git add .`

Always stage only relevant files.

### PRE-COMMIT GATE (MANDATORY)

Before EVERY commit, the agent MUST:

1. Run `git diff --stat` and `git diff --name-only` to show exactly which files are staged/modified.
2. **Present the file list to the user** and state which files are relevant to the task and why.
3. **Wait for the user to approve** before running `git commit`.
4. If ANY file in the diff was NOT part of the original task scope, the agent MUST:
   - Explain why it was changed.
   - Ask the user whether to include it or revert it (`git checkout -- path/to/file`).
5. Only stage files that belong to the task: `git add path/to/file1 path/to/file2` (never `git add .`).

**This gate cannot be skipped.** If the agent commits without showing the diff to the user first, it is a workflow violation.

```bash
git status
git diff --stat
# Wait for user approval, then stage ONLY relevant files:
git add path/to/file1.py path/to/file2.html
git commit -m "[Feature/Fix/Agent/Server] description of what is working correctly now"
git push origin main
```

### Branch Strategy

| Scope                                  | Strategy                                                          |
| -------------------------------------- | ----------------------------------------------------------------- |
| 1-2 files, low risk                    | Commit directly to `main`                                       |
| 3+ files, or architectural             | Create a feature branch, push, ask the user before merging        |
| Agent-server protocol changes          | Always feature branch -- both sides must be verified together     |
| Database migrations on existing tables | Always feature branch -- never push migration risks to main blind |

```powershell
git checkout -b feature/short-description
# ... make changes ...
git push -u origin feature/short-description
# Ask the user to review before merging
```

### Safe Migration Branch Workflow (Step-by-Step)

**Step 1: Create the branch from the latest main**

```powershell
git checkout main
git pull origin main
git checkout -b feature/add-new-model
```

**Step 2: Make model changes and generate migrations**

```powershell
# Edit the model, then:
python manage.py makemigrations app_name
python manage.py migrate
# Test locally, verify the migration works
```

**Step 3: Before merging back, sync with main**

```powershell
git checkout feature/add-new-model
git pull origin main
```

* **If no migration conflicts** -- you are good to go, skip to Step 5.
* **If migration conflicts** -- follow Step 4.

**Step 4: Fix migration conflicts (if they occur)**

```powershell
# Delete YOUR conflicting migration file (not the one from main)
Remove-Item ".\server\apps\app_name\migrations\00XX_your_migration.py"

# Re-generate your migration on top of main's latest
python manage.py makemigrations app_name

# Verify the new migration looks correct
python manage.py migrate

# Commit the fixed migration
git add server/apps/app_name/migrations/
git commit -m "[Fix] Regenerated migration on top of latest main"
```

**Step 5: Merge to main**

```powershell
git checkout main
git pull origin main
git merge feature/add-new-model
git push origin main
```

**Step 6: Clean up**

```powershell
git branch -d feature/add-new-model
git push origin --delete feature/add-new-model
```

---

## 7. Migration Safety Check -- CRITICAL

Before committing model changes (Local -- PowerShell):

```powershell
python manage.py makemigrations --check --dry-run
```

If this produces migrations, review them carefully before committing. This prevents migration drift.

---

## 8. Project Architecture Rules

### 8.1 Component Separation

This project has two distinct components that MUST remain cleanly separated:

| Component        | Location          | Purpose                                      |
| ---------------- | ----------------- | -------------------------------------------- |
| **Windows Agent** | `agent/`         | Runs on employee PCs; captures data          |
| **Web Dashboard** | `server/`        | Django app; receives data, provides admin UI |

* Agent code must NEVER import Django modules.
* Server code must NEVER import agent modules.
* Shared constants (API versions, status codes) go in a `shared/` directory if needed.

### 8.2 Agent Design Rules

* The agent runs as a **Windows Service** under the SYSTEM account.
* It must handle network failures gracefully (queue locally, retry later).
* It must not crash or hang if the server is unreachable.
* Screenshot capture must support 1, 2, or 3+ monitors.
* All intervals and settings should be pulled from the server, not hardcoded.
* The agent must have an auto-update mechanism or be deployable via GPO.

### 8.3 Dashboard Design Rules

* Follow Django best practices (apps, models, views, templates).
* The dashboard must be responsive and work on desktop browsers.
* Employee data must be access-controlled (admin sees all, manager sees their team).
* Screenshots must be viewable in a gallery with timestamp and employee filters.
* Productivity data must be visualized with charts (daily/weekly summaries).

### 8.4 Data Flow

```
Employee PC (Agent) --HTTPS--> Django Server ---> PostgreSQL Database
                                            ---> File Storage (Screenshots)
                                            ---> Admin Dashboard (Web UI)
```

All data flows one direction: from agent to server. The only server-to-agent communication is:
* Settings/configuration (screenshot interval, productivity rules)
* Agent update checks

---

## 9. Deployment

### 9.1 Agent Deployment

The Windows agent is packaged as a standalone `.exe` using PyInstaller and installed as a Windows Service.

**Build the agent:**
```powershell
cd agent
pyinstaller --onefile --name EmpMonitorAgent main.py
```

**Install on target PC (run as Administrator):**
```powershell
.\EmpMonitorAgent.exe install
.\EmpMonitorAgent.exe start
```

**Agent deployment checklist:**
- [ ] Agent `.exe` is code-signed (to avoid antivirus flags).
- [ ] Server URL and auth token are configured (via config file or registry).
- [ ] Windows Firewall allows outbound HTTPS from the agent.
- [ ] Agent starts automatically on boot (Windows Service set to Automatic).

### 9.2 Server Deployment

Follow standard Django deployment practices (Gunicorn + Nginx or equivalent).

**Server deployment checklist:**
- [ ] All migrations applied.
- [ ] Static files collected.
- [ ] HTTPS configured with valid certificate.
- [ ] API endpoints accessible from agent machines.
- [ ] File storage configured for screenshots (local disk or S3-compatible).

---

## 10. Emergency Recovery

These commands work identically on Windows (Git Bash / PowerShell with Git) and Linux.

```bash
# View recent history
git log --oneline -10

# Revert an entire commit (creates a new undo commit)
git revert <commit-hash>

# Restore a single file from a specific commit
git checkout <commit-hash> -- path/to/file.py
```

---

## 11. Known Limitations (Honest Disclosure)

These rules significantly reduce agent errors but cannot fully prevent:

* **Hallucinated logic** -- The agent can follow every rule perfectly and still write code that is logically wrong because it misunderstood the business domain. Mitigation: Rule 1.10 (ask when uncertain).
* **Subtle regressions** -- Without automated tests, no rule catches "the edit was syntactically correct but broke an edge case." Mitigation: the verification steps help, but a test suite is the real safety net.
* **Context window drift** -- In very long conversations, the agent may lose track of earlier rules. Mitigation: Session startup protocol (Section 2) and re-anchoring rule.
* **Agent-server desync** -- Changes to one side without updating the other. Mitigation: Rule 1.14 (agent-server contract rule).

---

## Agent Invocation Reminder

Reference this file at the start of every session:

```
Follow the workflow in `DEVELOPMENT_WORKFLOW.md`.
```
