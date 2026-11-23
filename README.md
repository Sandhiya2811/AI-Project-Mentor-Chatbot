# AI Project Mentor

A desktop AI mentor (Python + CustomTkinter) that guides a student from a project idea to a validated, finished
project, **one task at a time**, without handing over finished code. The student writes in English, Tamil, Tanglish,
Hindi, Telugu, Malayalam, Kannada or any language the configured model supports; the mentor answers in that language.

**AI runs in the cloud** (OpenAI, Anthropic Claude, Google Gemini, Perplexity, Z.ai GLM). Nothing is downloaded to your
computer and Ollama is **not** needed - it remains available as an optional local provider if you choose it.

> Documentation: [docs/PROJECT_DOCUMENTATION.md](docs/PROJECT_DOCUMENTATION.md) (technical, for maintainers) and
> [docs/USER_GUIDE.md](docs/USER_GUIDE.md) (for students).

---

## Windows installation and first run (start to finish)

All commands are **PowerShell** commands. Supported Python: **3.9 or newer**. Developed and tested on Python 3.12;
on Windows use **3.11 or 3.12** (the `faiss-cpu` and `numpy` packages publish ready-made Windows packages for them).

### Step 1 - Install Python
1. Open <https://www.python.org/downloads/windows/> and download the latest **Windows installer (64-bit)** for Python 3.12 (or 3.11).
2. Run the installer. On the first screen **tick "Add python.exe to PATH"**, keep **"Install launcher for all users"**, click
   **Install Now**. (Under *Customize installation* keep **"tcl/tk and IDLE"** ticked - the application window needs it.)
3. Open a **new** PowerShell window and verify:
   ```powershell
   py --version
   py -c "import tkinter; print('Tk', tkinter.TkVersion)"
   ```
   Expected: `Python 3.12.x` and `Tk 8.6`. If the second command fails, re-run the installer and choose *Modify > tcl/tk and IDLE*.

### Step 2 - Open the project folder
Unzip the project (e.g. to `C:\Projects\ai_project_mentor`), then either **VS Code:** *File > Open Folder...* and
*Terminal > New Terminal*, or **PowerShell:**
```powershell
cd C:\Projects\ai_project_mentor
dir
```
`dir` must list `main.py`, `requirements.txt` and `.env.example`.

### Step 3 - Create a virtual environment
```powershell
py -m venv .venv
```

### Step 4 - Activate it
```powershell
.venv\Scripts\Activate.ps1
```
The prompt now starts with `(.venv)`. *If PowerShell says "running scripts is disabled on this system"*:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```
(Permanent alternative: `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`. Or use Command Prompt and `.venv\Scripts\activate.bat`.)

### Step 5 - Install the dependencies
```powershell
py -m pip install --upgrade pip
pip install -r requirements.txt
```
Required: `customtkinter`, `requests`, `numpy`, `faiss-cpu`. Recommended: `keyring` (stores API keys in **Windows Credential
Manager**), `ruff`, `pytest`. Optional: `pypdf`, `python-docx`. If `faiss-cpu` cannot be installed on your Python
version, delete that line and install again - the app then uses a slower NumPy search (it works the same).

### Step 6 - Choose the AI provider and enter your API key
You need an API key from **one** provider (see the [API key guide](#api-key-setup-guide) below).

**Recommended - inside the app (no files to edit):**
1. Start the app (Step 7), open **Settings > AI model**.
2. Choose the **Provider**, pick a **Model** from the list (or type any model name your account has; **Refresh models** lists what
   your account can use), paste the **API key**, press **Save**.
3. The **Connection** line shows the result of a real check of your key and model (no tokens are spent). **Test connection**
   checks what you typed *without saving it*.

The key is stored in Windows Credential Manager (when `keyring` is installed - Settings tells you where it is stored), never
in the database, logs or `.env.example`. If you prefer files/environment variables:
```powershell
Copy-Item .env.example .env
notepad .env
```
and set `LLM_PROVIDER=...` plus the key variable of your provider (table below). `.env` is private - never commit or share it
(`.gitignore` already excludes it). Variables you can set (all optional):

| Variable | Meaning |
|---|---|
| `LLM_PROVIDER` | `openai` (default), `anthropic`, `google`, `perplexity`, `zai`, `ollama` (optional, local), `openai_compatible` |
| `LLM_MODEL` | Model of the selected provider. Empty = provider default. |
| `LLM_BASE_URL` | Server address. Empty = provider default (only for proxies / custom servers). |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` (or `GOOGLE_API_KEY`), `PERPLEXITY_API_KEY`, `ZAI_API_KEY` | API keys (alternative to the Settings screen) |
| `LLM_TEMPERATURE`, `LLM_TIMEOUT` | Creativity (0-1); seconds to wait for a reply (empty = cloud 60 s, Ollama 180 s) |
| `CHAT_MAX_TOKENS` | Longest normal answer (default 900). Lower = faster. |
| `AUTO_AI_NOTES` | `idle` writes AI learning notes only while you are not chatting; `off` disables it. |
| `LLM_NUM_CTX`, `LLM_KEEP_ALIVE` | Ollama only |
| `EMBEDDING_BACKEND` | `hash` (default, offline), `sentence-transformers` or `ollama` |
| `THEME`, `CODE_EXECUTION` | `dark`/`light`/`system`; `auto`/`off` (on Windows student code is **never executed**) |

PowerShell environment variables also work, e.g. for the current window: `$env:OPENAI_API_KEY = "paste-key-here"`.

**Check everything from the terminal (uses your real keys, prints no key):**
```powershell
py main.py --check-providers
```
For each provider with a key it validates key + model and times a short streamed answer (time to first text).

### Step 7 - Start the application
```powershell
py main.py
```
What happens: the terminal prints the database path, the AI provider status (e.g. `openai -> NOT READY (OpenAI API key is
missing ...)` until you add a key), the RAG backend and the sandbox status; the SQLite database `storage\mentor.db` is created on
first run; the knowledge index is built in the background; your provider's connection is checked in the background; then the
desktop window opens on **Create Your Project**. The status line at the bottom of the home screen shows
**AI connected: provider - model** in green, or what is wrong in amber. Keep the terminal open: errors and per-answer timings
(`chat timings: ...`) are printed there and written to `storage\app.log` (API keys are masked in all logs).

> With the virtual environment active, `py main.py` uses it. If you ever see `ModuleNotFoundError`, run
> `.venv\Scripts\python.exe main.py` instead.

### Step 8 - Troubleshooting (Windows)
| Problem | Solution |
|---|---|
| `py` / `python` is not recognized | Python is not installed or not on PATH. Re-run the installer, tick **Add python.exe to PATH**, open a *new* PowerShell. |
| `.venv\Scripts\Activate.ps1 cannot be loaded because running scripts is disabled` | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again (Step 4). |
| `Missing packages: customtkinter...` or `ModuleNotFoundError: No module named 'customtkinter'` (`numpy`, `requests`) | The environment is not active or dependencies are missing: activate `.venv`, then `pip install -r requirements.txt`. |
| `No module named '_tkinter'` / `'tkinter'` | Re-run the Python installer > Modify > tick **tcl/tk and IDLE**. |
| `Could not find a version that satisfies the requirement faiss-cpu` | Use Python 3.11/3.12, or remove the `faiss-cpu` line (NumPy fallback). |
| `<Provider> API key is missing` | Settings > AI model: paste the key and Save (or set the environment variable). The message includes the page where you get a key. |
| `... rejected the API key (HTTP 401)` | The key is wrong, revoked, or belongs to another provider. Paste it again. (Gemini reports a bad key as HTTP 400 "API key not valid".) |
| `... returned 404 - check the model name` | The model id does not exist for your account. Use **Refresh models** or choose another model. |
| `quota / billing limit reached (HTTP 429)` | Your account has no credit/quota. Check the provider's billing page. A plain rate limit (also 429) is retried automatically; wait and try again. |
| `Cannot reach <Provider> ... check your internet connection, proxy or firewall` | No internet, or a firewall/proxy blocks the API host. Allow HTTPS to the provider's API address (shown in Settings > Base URL hint). |
| `did not answer within 60s (timeout)` | Slow network or an overloaded model. Retry, choose a faster model, or raise `LLM_TIMEOUT`. |
| Settings says keys are stored in `storage/settings.json (plain text)` | The optional `keyring` package is not installed: `pip install keyring`, restart, and save the key again - it moves to Windows Credential Manager. |
| Database error / `database is locked` | Close all copies of the app. To start clean, close the app and rename `storage\mentor.db` (your old data stays in the renamed file). |
| App window does not open / no output | Run it from PowerShell (not by double-click) to see the error. Check `storage\app.log`. |
| "Port" problems | Not applicable: this is a desktop program and opens no web server. (Only the optional local Ollama uses port 11434.) |
| A learning link does not open | The link is opened in your default browser; if none can be started the address is copied to the clipboard and shown. Run `py main.py --check-links` to find dead links. |

---

## API key setup guide

Each provider has its **own** key and its **own** API format; the app speaks each provider's official API. Keys are separate per
provider - you can store several and switch in Settings. Pricing, free tiers and available models change; check the provider's
page. The links below are the key-management pages as known at development time and are not verified from the build environment.

| Provider (Settings name) | Get a key | Default model | Models listed in Settings |
|---|---|---|---|
| OpenAI (ChatGPT) | <https://platform.openai.com/api-keys> (create a secret key; the API needs billing credit) | `gpt-4o-mini` | gpt-4o-mini, gpt-4.1-mini, gpt-4.1, gpt-4o, gpt-5-mini, gpt-5 |
| Anthropic (Claude) | <https://console.anthropic.com/settings/keys> | `claude-sonnet-5-5` | claude-haiku-5-5, claude-sonnet-5-5, claude-opus-5-5 |
| Google (Gemini) | <https://aistudio.google.com/app/apikey> (Google AI Studio; a free tier may be available) | `gemini-2.5-flash` | gemini-2.5-flash, -flash-lite, -pro, gemini-2.0-flash |
| Perplexity AI | <https://www.perplexity.ai/settings/api> (API tab; needs credit) | `sonar` | sonar, sonar-pro, sonar-reasoning-pro |
| Z.ai (GLM) | <https://z.ai/manage-apikey/apikey-list> | `glm-4.5-air` | glm-4.5-air, glm-4.5, glm-4.5-flash, glm-4.6 |

Steps for any provider: create an account > create an API key > copy it (it is shown once) > in the app **Settings > AI model**:
select the provider > paste the key > **Save** > check that **Connection: OK** appears. The model list is a starting point: use
**Refresh models** (OpenAI, Anthropic, Gemini, Ollama list your account's real models) or type any model id.

Speed tips for the ~5 s target: choose a fast model (`gpt-4o-mini`, `claude-haiku-5-5`, `gemini-2.5-flash`, `glm-4.5-air`); answers
stream, so the first words appear as soon as the provider sends them. Perplexity's Sonar models are search-oriented; the app
asks them not to search, but they are not the fastest choice for a mentor.

### Optional: local Ollama (only if you select it)
Not needed and never used automatically - if a cloud API fails you see the error, the app does **not** switch to Ollama. To use it:
install from <https://ollama.com/download/windows>, run `ollama pull llama3.2:3b`, then in Settings choose **Ollama (local,
optional)** and the model, and press **Save**. (`py main.py --benchmark` measures its speed.)

---

## Other commands
```powershell
py -m pytest -q                 # automated tests (GUI tests need a display and are skipped without one)
py main.py --check-providers    # validate every provider that has a key + time a streamed answer
py main.py --benchmark          # time-to-first-token / tokens per second of the selected provider
py main.py --check-links        # check that every curated learning link still opens (needs internet)
```

## What the application does (short)
* Create a project from an idea -> personalised roadmap -> guided **one task at a time**.
* Understands what the student means (task questions, "next", "I understand", libraries, errors, any task or the whole roadmap)
  using the real project state; progress changes **only** after a successful validation.
* **Language is automatic:** every message is analysed; the reply mirrors its language, script and style (English, Tamil,
  Tanglish, Hindi, Telugu, Malayalam, Kannada, romanised forms, mixed text).
* Students submit files/ZIPs or written answers -> hybrid validation (rule checks + static analysis + AI review).
* **Learning Resources:** official documentation plus "Start with" tutorials for the technologies the project needs
  (109 catalogued), tied to task numbers, with **clickable** titles.
* Answers stream in progressively; strict no-code policy (prompt + independent response guard) and project-only scope.

See [docs/PROJECT_DOCUMENTATION.md](docs/PROJECT_DOCUMENTATION.md) for details and
[Known limitations](docs/PROJECT_DOCUMENTATION.md#21-limitations).
