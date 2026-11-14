# AI Project Mentor

A desktop (CustomTkinter) AI mentor that guides a student from a project idea to a validated, finished project -
**one task at a time**, without ever handing over finished code.

```bash
pip install -r requirements.txt
python main.py
```

Python 3.9+. On Linux you may also need Tk: `sudo apt install python3-tk`.

## First run
1. Install an LLM backend, e.g. [Ollama](https://ollama.com): `ollama pull llama3.1` (any model that follows JSON
   instructions works; bigger = better roadmaps and reviews). Or open **Settings** and choose OpenAI, Anthropic or any
   OpenAI-compatible server and paste the key. Use **Test AI connection**.
2. `python main.py` - the home screen shows **Create Your Project**. Describe an idea (or click an example) and press
   **Start Your Project**.
3. The mentor creates a roadmap, explains Task 1 and waits. Do the task yourself, then switch the input to
   **Submit for review** and either type your written answer or **Upload file** (files / ZIP of your project).
4. A review report appears. *Passed* unlocks the next task; otherwise fix and resubmit.

## How the main rules are enforced (not just prompted)
| Rule | Enforcement |
|---|---|
| No complete code | System prompt **and** `ai_engine/response_guard.py`, applied to chat replies, review text, task text and learning notes. Function/class definitions and blocks over 3 lines are replaced by a notice; one automatic retry asks the model to rewrite with pseudocode. It is a heuristic - it can miss cleverly disguised code or occasionally remove harmless text. |
| One task at a time | Tasks are `locked/active/passed` in SQLite. Only `progress_tracker.mark_passed` (called by the review engine) unlocks the next one. Locked tasks are never shown to the LLM. |
| Not LLM-opinion-only approval | `validation/validation_engine.py`: rule checks decide; the LLM reviewer can only make the verdict **stricter**. If the AI is offline, rule checks alone can pass work and the report says so. |
| Project-only scope | System prompt makes the model emit an off-topic token; the app replaces it with the fixed reply. |
| Multilingual | `language_detector.py` detects Tamil/Hindi/Telugu/Kannada/Malayalam... scripts plus Tanglish/Hinglish and tells the LLM to answer in kind (or in your preferred language from User Profile). Quality depends on the model you choose. |

## Validation engine
* **Rule checks** (generated per task by the roadmap, executed deterministically): source present, file exists,
  syntax valid, terms used, functions/classes defined, text mentions required topics, minimum words, tests present,
  tests pass, runs OK.
* **Static analysis** (nothing is executed): Python - `ast` + `ruff`; JavaScript - `node --check`; PHP - `php -l`;
  Ruby - `ruby -c`; Go - `gofmt -e`; C/C++ - `gcc`/`g++ -fsyntax-only`; Java - `javac -proc:none`; R - `parse()`;
  SQL - `sqlfluff`; HTML - tag balance. A tool that is not installed is listed under *Checks that could not be performed*.
  **Not integrated** (suggested in the brief): ESLint, Checkstyle, PHPStan, Lintr, Semgrep, Tree-sitter, Pylint -
  add them in `validation/static_analyzer.py`.
* **Test execution** is implemented for **Python only** (pytest/unittest) and runs only when the OS can isolate the network
  (Linux with `unshare`). Elsewhere student code is never executed. Limits: wall-clock timeout, CPU/file/memory rlimits,
  throw-away copy of the files. It does **not** limit process count. Missing third-party modules in the validation
  environment are reported as "could not be checked", not as student failure.
* Uploads: extension allow-list, size/file-count limits, zip-slip/symlink/zip-bomb protection (`utils/security.py`).
  Images are stored but their content is not analysed.

## RAG
`storage/knowledge/` holds concise bundled notes; drop your own `.md`, `.txt` or `.pdf` files there and press
**Settings > Rebuild knowledge index**. Retrieval uses FAISS. The default `hash` embeddings work offline but are lexical
(English keywords); for semantic/multilingual retrieval set `EMBEDDING_BACKEND=sentence-transformers` or `ollama`.

## Data
SQLite at `storage/mentor.db` (users, projects, project_requirements, tasks, student_submissions, uploaded_files,
validation_reports, conversations, chat_messages, learning_notes, project_progress, activity_logs). Uploaded files are
kept in `storage/uploads/<project>/<submission>/`. Settings (including an API key if you enter one) are saved in
`storage/settings.json` (owner-only permissions where the OS allows). Deleting a conversation keeps the project;
**Previous Projects > Resume** reopens it.

## When the LLM is down
Clear message in chat; browsing history/projects, Learning Resources (offline notes with official-doc links and local
knowledge excerpts), and rule-based review of submissions keep working. New projects get a clearly labelled generic
template roadmap.

## Project layout
Matches the brief: `interface/`, `ai_engine/`, `project_manager/`, `code_review/`, `validation/`, `rag/`, `learning/`,
`database/`, `storage/`, `utils/` (plus `interface/markdown_text.py`, `resources_view.py`, `settings_view.py`,
`validation/executor.py`, `utils/sandbox.py`).

## Tests
`python -m pytest -q` runs backend tests with a scripted fake LLM (guard, language detection, zip safety, full
task-progression flow, LLM-offline behaviour).

## Known limitations
* Developed and smoke-tested on Linux (headless Xvfb) with a **fake LLM**; it has not been run against a real model
  or on Windows/macOS here, so expect to tune prompts for your model. Small local models may return invalid roadmaps
  (the app retries once, then falls back to the template roadmap).
* Emoji are stripped from display (Tk 8.6 cannot render them reliably). No drag-and-drop upload (use the button).
* Conversation memory is the last ~14 messages plus project/task context rebuilt from the database each turn.
* Notes may be generated in a language the model handles poorly; use a stronger model for Indic languages.


# Git and GitHub – Push Code from VS Code (Windows)

## Step 1: Open VS Code Terminal

1. Open your project folder in VS Code.
2. Open the terminal using `Ctrl + ~`.
3. Make sure the terminal is in your project directory.
4. Select PowerShell as the terminal.

## Step 2: Initialize Git

Run the following commands one by one:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
```

## Step 3: Connect GitHub Repository

Create a new repository on GitHub.

Copy your repository URL and run:

```bash
git remote add origin https://github.com/USERNAME/REPOSITORY.git #git remote add origin https://github.com/Sandhiya2811/AI-Project-Mentor-Chatbot.git

git push -u origin main
```

Replace `USERNAME` with your GitHub username and `REPOSITORY` with your repository name.

## Step 4: Push Updated Code

Whenever you make changes to your project, use these commands:

```bash
git add .
git commit -m "Updated project"
git push
```

## Step 5: Check Git Status

To check modified and staged files:

```bash
git status
```

## Useful Git Commands

| Command | Description |
|---|---|
| `git init` | Initialize Git |
| `git add .` | Stage all changes |
| `git commit -m "message"` | Save changes |
| `git push` | Upload code to GitHub |
| `git pull` | Get latest code |
| `git status` | Check file status |
| `git remote -v` | View remote repository |
| `git log --oneline` | View commit history |

## Important: Create a .gitignore File

Before pushing your project, create a `.gitignore` file in the root directory.

Add:

```gitignore
.env
.venv/
venv/
__pycache__/
*.pyc
*.db
.DS_Store
.vscode/
```

**Note:** Never upload passwords, API keys, secret tokens, or sensitive environment variables to GitHub.

## Conclusion

You can use VS Code Terminal with Git commands to manage your project and push code to GitHub easily.
