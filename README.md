# AI Project Mentor

A desktop AI mentor (Python + CustomTkinter) that guides a student from a project idea to a validated, finished
project, **one task at a time**, without handing over finished code. The student writes in English, Tamil, Tanglish,
Hindi, Telugu, Malayalam, Kannada or any language the configured model supports; the mentor answers in that language.

> Documentation: [docs/PROJECT_DOCUMENTATION.md](docs/PROJECT_DOCUMENTATION.md) (technical, for maintainers) and
> [docs/USER_GUIDE.md](docs/USER_GUIDE.md) (for students).

---

## Windows installation and first run (start to finish)

All commands are **PowerShell** commands. Supported Python: **3.9 or newer**. Developed and tested on Python 3.12;
on Windows use **3.11 or 3.12** (the `faiss-cpu` and `numpy` packages publish ready-made Windows packages for them).

### Step 1 - Install Python
1. Open the official download page: <https://www.python.org/downloads/windows/> and download the latest
   **Windows installer (64-bit)** for Python 3.12 (or 3.11).
2. Run the installer. On the first screen **tick "Add python.exe to PATH"** and keep the default **"Install launcher for
   all users"**. Click **Install Now**. (Under *Customize installation* make sure **"tcl/tk and IDLE"** stays ticked -
   the application window needs it.)
3. Open a **new** PowerShell window and verify:
   ```powershell
   py --version
   py -c "import tkinter; print('Tk', tkinter.TkVersion)"
   ```
   The first command prints e.g. `Python 3.12.x`; the second prints `Tk 8.6`. If the second fails, re-run the installer
   and choose *Modify > tcl/tk and IDLE*.

### Step 2 - Open the project folder
Unzip the project (e.g. to `C:\Projects\ai_project_mentor`), then either
* **VS Code:** *File > Open Folder...* > select `ai_project_mentor`, then *Terminal > New Terminal* (PowerShell), or
* **PowerShell:**
  ```powershell
  cd C:\Projects\ai_project_mentor
  ```
Check you are in the right folder: `dir` must list `main.py`, `requirements.txt` and `.env.example`.

### Step 3 - Create a virtual environment
```powershell
py -m venv .venv
```

### Step 4 - Activate it
```powershell
.venv\Scripts\Activate.ps1
```
The prompt now starts with `(.venv)`.

*If PowerShell says "running scripts is disabled on this system"*, allow scripts **for this window only** and retry:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```
(Permanent alternative for your user: `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`. Or use
Command Prompt and `.venv\Scripts\activate.bat`.)

### Step 5 - Install the dependencies
```powershell
py -m pip install --upgrade pip
pip install -r requirements.txt
```
Required: `customtkinter`, `requests`, `numpy`, `faiss-cpu`. Recommended: `ruff` (Python lint), `pytest`. Optional: `pypdf`,
`python-docx`. If `faiss-cpu` cannot be installed on your Python version, delete that line from `requirements.txt` and
install again - the application then uses a slower NumPy search (works the same).

### Step 6 - Configure the environment (`.env`) and the AI model
1. Create your settings file and open it:
   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```
2. The variables (all optional except the model choice):

   | Variable | Meaning |
   |---|---|
   | `LLM_PROVIDER` | `ollama` (local), `openai`, `anthropic` or `openai_compatible` (LM Studio, Groq, OpenRouter...) |
   | `LLM_MODEL` | Model name, e.g. `llama3.2:3b`. For Ollama it must appear in `ollama list`. |
   | `LLM_BASE_URL` | Server URL. Empty = provider default (Ollama: `http://localhost:11434`). |
   | `LLM_API_KEY` | Key for cloud providers (or set `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`). Keep it private; never share `.env`. |
   | `LLM_TEMPERATURE`, `LLM_TIMEOUT` | Creativity (0-1) and seconds to wait for the model. |
   | `LLM_NUM_CTX`, `LLM_KEEP_ALIVE` | Ollama speed settings: context size (default 4096) and how long the model stays loaded (default 30m). |
   | `CHAT_MAX_TOKENS` | Longest normal answer (default 900). Lower = faster. |
   | `AUTO_AI_NOTES` | `idle` writes AI learning notes only while you are not chatting; `off` disables it. |
   | `EMBEDDING_BACKEND` | `hash` (default, offline), `sentence-transformers` or `ollama`. |
   | `THEME` | `dark`, `light` or `system`. |
   | `CODE_EXECUTION` | `auto` or `off`. On Windows student code is **never executed** (see Limitations). |

3. **Ollama (local model, free):**
   * Install from <https://ollama.com/download/windows> and start it (it runs in the system tray).
   * Download a model (new PowerShell window):
     ```powershell
     ollama pull llama3.2:3b
     ollama list
     ```
   * Put the same name in `.env`: `LLM_MODEL=llama3.2:3b`.
   * **Choosing a model:** small models (3B) answer fast but are weaker at Tamil/Tanglish and at planning roadmaps; 7-8B
     models (`llama3.1:8b`, `qwen2.5:7b`) are better but need a good CPU/GPU and 8+ GB RAM. Measure your machine (below).
4. **Cloud provider instead:** set `LLM_PROVIDER=openai` (or `anthropic`), the model name and `LLM_API_KEY`.
5. **Verify the connection** (either way works):
   * the start-up text printed by `py main.py` shows `LLM provider : ollama -> OK`, or
   * in the app: **Settings > Test AI connection**.
6. **Measure the speed of your model** (optional but recommended):
   ```powershell
   py main.py --benchmark
   ```
   It prints the time to the *first token* (what the student waits for), tokens per second and model-load time.

### Step 7 - Start the application
```powershell
py main.py
```
What happens: the terminal prints the database path, LLM status, RAG backend and sandbox status; the SQLite database
`storage\mentor.db` is created on first run; the knowledge index is built in the background; if Ollama is the provider the
model is loaded into memory in the background; then the desktop window opens on **Create Your Project**. Keep the
terminal open: errors and per-answer timings (`chat timings: ...`) are printed there and written to `storage\app.log`.

> With the virtual environment active, `py main.py` uses it. If you ever see `ModuleNotFoundError`, run
> `.venv\Scripts\python.exe main.py` instead.

### Step 8 - Troubleshooting (Windows)
| Problem | Solution |
|---|---|
| `py` / `python` is not recognized | Python is not installed or not on PATH. Re-run the installer, tick **Add python.exe to PATH**, open a *new* PowerShell. Try `py --version`. |
| `.venv\Scripts\Activate.ps1 cannot be loaded because running scripts is disabled` | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again (Step 4). |
| `Missing packages: customtkinter...` printed by `main.py` | The environment is not active or dependencies are missing: activate `.venv`, then `pip install -r requirements.txt`. |
| `ModuleNotFoundError: No module named 'customtkinter'` (or `numpy`, `requests`) | Same cause. Check `(.venv)` is in the prompt; run `.venv\Scripts\python.exe -m pip install -r requirements.txt`. |
| `ModuleNotFoundError: No module named '_tkinter'` / `No module named 'tkinter'` | Re-run the Python installer > Modify > tick **tcl/tk and IDLE**. |
| `Could not find a version that satisfies the requirement faiss-cpu` | Your Python version has no wheel. Use Python 3.11/3.12, or remove the `faiss-cpu` line (NumPy fallback). |
| Start-up shows `Ollama is not reachable at http://localhost:11434` | Ollama is not running: start the Ollama app (or `ollama serve`). Check `LLM_BASE_URL` if you changed the port. |
| `Ollama is running but model 'x' is not installed` / `HTTP 404 ... check the model name` | `ollama list` shows the real names; run `ollama pull <name>` and make `LLM_MODEL` identical (including `:3b`). |
| The first answer takes very long, later ones are faster | The model was loading into memory. The app warms it up at start; wait for the first answer once, or use a smaller model. Run `py main.py --benchmark`. |
| `rejected the API key (HTTP 401)` | Wrong or missing `LLM_API_KEY`. Fix it in Settings or `.env`. |
| Database error / `database is locked` / corrupted DB | Close all copies of the app. The database is `storage\mentor.db`; to start clean, close the app and rename that file (your old data stays in the renamed file). |
| App window does not open / no output | Run it from PowerShell (not by double-click) to see the error. Check `storage\app.log`. |
| "Port" problems | Not applicable: the application is a desktop program and opens no web server. Only Ollama uses a port (11434). |

---

## Other commands
```powershell
py -m pytest -q                 # run the automated tests (40 tests, fake LLM, no GPU needed)
py main.py --benchmark          # measure time-to-first-token / tokens per second of YOUR model
py main.py --check-links        # check that every curated learning link still opens (needs internet)
```

## What the application does (short)
* Create a project from an idea -> personalised roadmap -> guided **one task at a time**.
* Understands what the student means (task questions, "next", "I understand", libraries, errors, any task or the
  whole roadmap) using the real project state; progress changes **only** after a successful validation.
* Students submit files/ZIPs or written answers -> hybrid validation (rule checks + static analysis + AI review).
* Learning Resources with **official, curated links** for every recommended technology.
* Answers stream in progressively; language follows each message automatically.
* Strict no-code policy (prompt + independent response guard) and project-only scope.

See [docs/PROJECT_DOCUMENTATION.md](docs/PROJECT_DOCUMENTATION.md) for details and
[Known limitations](docs/PROJECT_DOCUMENTATION.md#21-limitations).
