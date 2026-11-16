# AI Project Mentor - Technical Documentation

This document describes what is **actually implemented** (about 5,700 lines of Python in 42 modules, plus 40 automated
tests). Anything not implemented is listed in [21. Limitations](#21-limitations).

Contents: 1 Introduction - 2 Problem - 3 Objectives - 4 Features - 5 Architecture - 6 Folders - 7 Files - 8 Workflow -
9 AI/LLM - 10 Multilingual - 11 RAG - 12 Database - 13 Roadmap - 14 Tasks - 15 Upload and review - 16 Validation -
17 Learning resources - 18 Errors - 19 Configuration - 20 Dependencies - 21 Limitations - 22 Troubleshooting

---

## 1. Project introduction
AI Project Mentor is a local desktop application (Python 3.9+, CustomTkinter, SQLite) that acts as a personal technical
mentor for students. A student describes a project idea; the mentor analyses it, builds a roadmap, explains one task at a
time, reviews the student's own submissions, explains errors, and unlocks the next task only after validation. It is a
mentor, not an FAQ bot and not a code generator.

## 2. Problem statement
Students who build projects alone get stuck, copy code they do not understand, and have nobody to check their work
against the task. Generic chatbots hand over complete solutions and forget the project. The mentor must (a) keep the
whole project and progress in memory, (b) teach instead of solving, (c) verify work with evidence, and (d) speak the
student's language, including Tamil and Tanglish.

## 3. Project objectives
1. Guide a student from idea to a validated project, one task at a time.
2. Never give complete source code (prompt rule + independent guard).
3. Validate work with rules and tools, not only an LLM's opinion.
4. Understand free-form, multilingual conversation about any task or the whole roadmap.
5. Provide learning material with official, non-invented links.
6. Respond quickly (progressive streaming) and stay on project-related topics.

## 4. Features
* Create Your Project home screen, roadmap generation (AI, with a clearly labelled template fallback).
* Conversation per project, history, rename/delete/search, resume old projects with full state.
* Intent-aware mentor: explain any task / whole roadmap, "next task", acknowledgements, completion claims, libraries and
  tools, concepts, errors.
* Submission of files, ZIP projects or written answers; hybrid validation; review report; resubmission.
* Progress tracking (completed/total, current task), roadmap dialog.
* Learning Resources: per-technology notes (offline instantly, AI-written when idle) with curated official links.
* Per-message language detection and explicit language requests.
* Streaming answers, model warm-up, timing logs, benchmark command.
* Settings screen (theme, provider, model, URL, key, embeddings, sandbox), user profile, light/dark theme.

## 5. Complete system architecture

```
+-----------------------------------------------------------------------------------------+
|  interface/  (CustomTkinter)  app.py  sidebar  chat_view  project_view  resources_view   |
|              settings_view  history_view  markdown_text  theme                           |
+-----------------------------|-----------------------------------------------------------+
                              | calls (worker threads; results come back through a queue)
                              v
+-----------------------------------------------------------------------------------------+
|  ai_engine/assistant.py  (class Mentor)  <- the only entry point the UI uses             |
|     |-- intent_router  (what does the student want?)          no LLM                     |
|     |-- language_detector (language of THIS message)           no LLM                     |
|     |-- _plan()  (intent + real task state -> directive + facts + fallback)              |
|     |-- conversation_memory (recent messages from SQLite)                                 |
|     |-- rag/retriever (only for concept/error/follow-up questions)                        |
|     |-- llm_provider  (Ollama | OpenAI | Anthropic | OpenAI-compatible; streaming)        |
|     |-- response_guard (StreamGuard + check: no-code policy)  + URL filter                |
|     +-- code_review/review_engine  (submissions)                                          |
|            |-- file_reader, code_analyzer, report_generator                               |
|            +-- validation/ (static_analyzer, rule_validator, executor, validation_engine) |
|  project_manager/ (idea_analyzer, roadmap_generator, task_manager, progress_tracker)     |
|  learning/ (resource_manager = curated catalog, notes_generator)                          |
+-----------------------------|-----------------------------------------------------------+
                              v
+-----------------------------------------------------------------------------------------+
|  database/ (SQLite: db.py, models.py, repository.py)     storage/ (db, uploads, index)   |
+-----------------------------------------------------------------------------------------+
```

**How components communicate.** The UI never touches the LLM or the database logic directly: it calls `Mentor` methods in
a background thread (`App.run_bg`) and receives results on the UI thread through a `queue.Queue` polled every 80 ms
(`App._poll`). Streaming pieces travel the same way (`on_token` -> `post` -> `ChatView.stream_append`). Components share
state only through SQLite (`repository.py` opens a short-lived connection per call, so it is thread-safe). The task state
(`tasks.status`) is the single source of truth for progress; only `progress_tracker.mark_passed`, called by
`review_engine` after a **Passed** validation, can change a task to `passed`.

## 6. Folder structure
```
ai_project_mentor/
  main.py                    start-up; --benchmark; --check-links
  config.py  .env.example  requirements.txt  README.md
  docs/                      PROJECT_DOCUMENTATION.md, USER_GUIDE.md
  interface/                 app, sidebar, history_view, chat_view, project_view, resources_view, settings_view,
                             markdown_text, theme
  ai_engine/                 assistant, intent_router, language_detector, prompts, llm_provider, response_guard,
                             conversation_memory
  project_manager/           idea_analyzer, roadmap_generator, task_manager, progress_tracker
  code_review/               file_reader, language_detector, code_analyzer, report_generator, review_engine
  validation/                static_analyzer, rule_validator, executor, validation_engine
  rag/                       embeddings, knowledge_base, retriever
  learning/                  resource_manager, notes_generator
  database/                  db, models, repository
  utils/                     helpers, security, sandbox
  storage/                   knowledge/ (reference .md files), uploads/, index/, mentor.db, settings.json, app.log
  tests/                     test_core, test_conversation, test_streaming
```

## 7. Explanation of the important Python files
| File | Role |
|---|---|
| `main.py` | Checks Python and packages, initialises the DB, prints status, starts `App`. `--benchmark` measures the configured model; `--check-links` HTTP-checks every curated URL. |
| `config.py` | `.env` loader and `settings` object (precedence: `storage/settings.json` > environment/.env > defaults). |
| `interface/app.py` | Main window, navigation, background workers, streaming wiring, idle scheduling of AI notes, warm-up. |
| `interface/chat_view.py` | Message bubbles (selectable text), input area, attachments, Ask/Submit mode, **progressive display** (`stream_append`, `finish_stream`). |
| `ai_engine/assistant.py` | `Mentor`: `start_project`, `chat`, `resume_project`, `_question`, `_plan`, `_submission`, `_after_pass`, streaming and URL safety. |
| `ai_engine/intent_router.py` | `classify()` -> `Intent`. Understands task references, workflow phrases, acknowledgements, tools, concepts, errors, unrelated topics in English/Tamil/Tanglish. |
| `ai_engine/prompts.py` | Every prompt: system prompt, roadmap/idea/intro/review/notes prompts, fixed off-topic reply. |
| `ai_engine/llm_provider.py` | Provider classes with `chat`, `stream_chat`, `warm_up`, `health`; shared `requests.Session`; friendly errors; `last_stats` timings. |
| `ai_engine/response_guard.py` | `check()` (complete text) and `StreamGuard` (while streaming) enforce the no-code policy. |
| `ai_engine/language_detector.py` | Per-message language hint, Tanglish/Hinglish detection, explicit language requests. |
| `ai_engine/conversation_memory.py` | Last 8 messages / 3,500 characters; review reports reduced to a stub. |
| `project_manager/roadmap_generator.py` | Validates LLM stages, adds baseline checks, appends the fixed Final Validation task, template fallback. |
| `learning/resource_manager.py` | Curated catalog of 62 technologies with official sources and direct topic links; offline notes; learning path. |
| `learning/notes_generator.py` | Offline base notes instantly; AI notes (cancellable) per technology. |
| `code_review/review_engine.py` | Orchestrates ingest -> analysis -> validation -> AI review -> decision -> persistence. |
| `validation/validation_engine.py` | Decision policy (Passed / Needs Improvement / Failed Validation). |
| `database/repository.py` | All SQL. |
| `utils/security.py`, `utils/sandbox.py` | Safe ZIP extraction, upload rules; restricted subprocess runner. |

## 8. Application workflow
1. **Start:** `py main.py` -> `init_db()` -> window. In the background: knowledge index built, model warmed up (Ollama).
2. **Create project:** the idea goes to `idea_analyzer` (1 LLM call) and `roadmap_generator` (1 LLM call). The project, tasks,
   tools and progress are saved in one transaction; the chat opens immediately; the **opening message streams in**
   (greeting, objective, stage list, Task 1, then a deterministic "tools and where to learn them" block with official links).
   Offline learning notes are created instantly; AI notes follow only when the student is idle.
3. **Ask:** `Mentor.chat(mode="ask")` -> `_question` (see section 9 for the steps).
4. **Submit:** `mode="submit"` (or any attached file) -> `_submission` -> `review_engine.review` -> report message ->
   if **Passed**: task marked passed, next unlocked, next-task message (or completion message).
5. **Resume:** `resume_project` reopens the conversation (or writes a deterministic "welcome back" message with progress).

## 9. AI and LLM integration
**Providers** (`llm_provider.py`): `ollama` (`/api/chat`, NDJSON stream), `openai` and `openai_compatible`
(`/chat/completions`, SSE), `anthropic` (`/v1/messages`, SSE). The provider is created per call from the current settings
but all share one `requests.Session` (connection reuse). Errors are translated to `LLMUnavailable` (cannot reach, timeout,
429) or `LLMError` (bad key, 404 model); the UI shows a clear message and the non-AI features keep working.

**One normal question (`Mentor._question`):**
1. `intent_router.classify(text, project, tasks, tool_names)` - microseconds, no LLM.
2. If the intent is *unrelated* -> the fixed reply, **no LLM call**.
3. `_plan()` builds a *directive* (what the student wants and what the real state allows), the task details the model needs,
   a `max_tokens` limit, a verified-links block, and a deterministic fallback answer.
4. RAG retrieval **only** for concept / error / follow-up / ambiguous intents (3 chunks, 1,500 chars). Workflow, task,
   roadmap and tools questions are answered from the roadmap itself.
5. Prompt = system prompt (no-code rules, scope, behaviour, language rule, project, tools, roadmap with statuses, current
   task state, latest review summary) + the last messages + the directive appended to the student's message as a
   `[MENTOR NOTE - written by the application, not by the student]`.
6. `stream_chat` -> `StreamGuard` (held-back code blocks are judged before they are shown) -> `_UrlFilter` (removes URLs
   that are not in the curated catalog) -> UI, piece by piece.
7. A final complete `check()` pass produces the stored text; the verified-links block is appended; the message is stored with
   `metadata.timings`.

**Why project questions are no longer rejected (root cause).** Earlier, the only scope control was an instruction asking
the LLM to answer `[[OFF_TOPIC]]`; small models used it for good Tanglish questions ("Libraries ennalam venum?"). Now the
router decides scope with project context. The off-topic option is **removed from the prompt** for any message the router
classified as project-related, and offered to the model only for genuinely unsure messages (long messages with no technical
or project signal). Clearly unrelated topics (weather, cricket, movies, recipes, jokes, politics ...) get the fixed reply
without calling the model.

**Intent kinds** (`intent_router.py`): `explain_task`, `explain_roadmap`, `advance`, `whats_next`, `acknowledge`,
`completion`, `tools`, `resources`, `concept`, `error`, `followup`, `ambiguous`, `unrelated`. It is a layered heuristic
(task numbers -> workflow phrases -> technical and project vocabulary -> unrelated list -> "when in doubt, answer"), not a
trained classifier. Unusual phrasings can be misclassified; in doubt a message is treated as project-related.

**Task-progression rules implemented in `_plan`** (never marks anything complete):
| Student says | Behaviour |
|---|---|
| "Task N explain" / "Task N la enna irukku" / "explain all tasks" | Always allowed for any task, past, current or future (future = labelled preview). Roadmap overview uses all tasks. |
| "Task 2 ku move pannalam" with Task 1 **not validated** | Says what is pending, how to submit; no state change. |
| Same, and the target **is the open task** | "Great! Let's move to Task N ..." kick-off with subtasks and expected output. |
| Same, target later than the open task | Blocked until the current task is validated; a preview can be requested. |
| "Next task" / "Next enna?" | Uses state: if the open task was already introduced and is unvalidated -> finish and submit it; otherwise introduce it. |
| "Okay, I understand" | Short acknowledgement; no repeated explanation; not treated as completion. |
| "I completed Task 1" | Cannot be verified: asks for Submit for review; if already validated, confirms. |
Whether a task was already introduced is remembered in `chat_messages.metadata_json` (`intro_task`), so a task is not
re-explained in a long conversation.

**Response speed.**
* *Likely causes of multi-minute answers in the earlier version (from the code, not measured on the student's machine):*
  non-streaming calls (nothing visible until the last token), an output ceiling of 2,500 tokens (at 5 tokens/s that alone is
  about 500 s), a long prompt (RAG every time, long history, full review reports), a possible second full generation when
  the no-code guard triggered, model reloading without keep-alive, and AI notes generating in the background at the same
  time as the first question.
* *Changes:* streaming for chat and for the opening message; per-intent output limits (220-1,500 tokens, normal answers
  capped by `CHAT_MAX_TOKENS`); no regeneration on a guard hit (offending blocks are replaced inline); RAG only when needed;
  history 8 messages / 3,500 chars; context window 4,096; `keep_alive` 30 min; model **warm-up** at start; shared HTTP
  session; AI notes only when idle and cancelled when the student sends a message; deterministic answers for workflow
  questions when the model is down.
* *Measured here (not on a real model):* application overhead per message (routing, planning, DB, prompt assembly) is about
  6-10 ms; against a local fake server emitting a token every 150 ms, the first text reached the UI after about 0.15 s
  while the full answer took 0.75 s (`tests/test_streaming.py`).
* *Not measured:* time-to-first-token of the student's real model - it depends on model size, quantisation, CPU/GPU and
  prompt length (about 1.5k-2.5k tokens per request). Run `py main.py --benchmark` to get *your* numbers (time to first
  token, tokens/second, prompt tokens, model-load time). The 5-second target for the first visible text is realistic for
  small models (3B) or GPU use; on a CPU with 7-8B models it may not be reachable - use a smaller or more quantised model,
  keep `LLM_NUM_CTX` at 4096 or lower, lower `CHAT_MAX_TOKENS`, or use a cloud provider. Every answer's timings
  (`first_token_s`, `model_load_s`, `prompt_eval_s`, `tokens_per_s`, `prompt_chars`) are logged as `chat timings:` and saved
  in the message metadata, which shows where the time goes.

**No-code policy.** (1) `NO_CODE_RULES` in every prompt. (2) `response_guard.check` on every AI text (chat, review text,
task text, notes): definitions of functions/classes and code blocks over 3 lines are replaced by a notice; pseudocode is
allowed; unfenced runs of 5+ code-looking lines are removed. (3) `StreamGuard` does the same while streaming. It is a
heuristic and can miss cleverly disguised code.

## 10. Multilingual processing
* Language is **never a setting**: every student message is analysed (`language_detector.detect`) - Unicode script
  (Tamil, Hindi, Telugu, Kannada, Malayalam, Bengali, ...), romanised Tamil (Tanglish), Hindi, Telugu, Malayalam, Kannada
  vocabularies, and explicit requests ("explain this in Tamil", "tamil la sollu").
* The result becomes a rule in the system prompt: reply in the language/style of the latest message; an explicit request
  wins; for very short messages ("ok") the language of the previous turn is kept; technical terms stay in English.
* The LLM does the real understanding (informal spelling, mixed language); the detector only gives a reliable hint. Quality
  depends on the model (small models are noticeably weaker in Tamil/Tanglish).
* The router also understands Tanglish/Tamil workflow words (polam, pannalam, enna, ethuku, ella, venum ...).
* The profile has "Language for learning notes" only; chat replies ignore it.

## 11. RAG implementation
`storage/knowledge/*.md|txt|pdf` (12 bundled concise notes; add your own) -> `knowledge_base.chunk_text` (heading-aware chunks,
about 900 chars) -> `embeddings.Embedder` (`hash` offline lexical vectors by default; `sentence-transformers` or Ollama
optional) -> FAISS `IndexFlatIP` (NumPy fallback) with a manifest so the index is rebuilt only when files or the embedder
change. `retriever.retrieve` returns global chunks (and, for other callers, the project's own requirement chunks without
locked tasks). The default `hash` embedding matches English keywords; use a multilingual embedder for semantic or
non-English retrieval. RAG is skipped for workflow questions to save time.

## 12. Database structure (`database/models.py`, SQLite, foreign keys on)
`users` - `projects` (title, idea, objective, domain, programming_language, difficulty, roadmap_source llm|template, status)
- `project_requirements` (kind tool|requirement, name, detail) - `tasks` (position, title, description, expected_output,
deliverable_type, `hints_json` = `{"hints","subtasks","tools"}` (older projects: a plain list), `checks_json`, status
locked|active|passed, attempts) - `student_submissions` (attempt_no, status) - `uploaded_files` (path, size, sha256,
language, kind) - `validation_reports` (status, rule/static/LLM JSON, report markdown) - `conversations` (project_id, title,
language) - `chat_messages` (role, content, kind chat|review|notice, `metadata_json` e.g. intent, timings, intro_task,
attachments) - `learning_notes` (unique per project+tool, source llm|offline) - `project_progress` - `activity_logs`.
Deleting a project cascades to everything; deleting a conversation keeps the project.

## 13. Project roadmap generation
`idea_analyzer.analyze` (title, objective, domain, language, difficulty, tools in learning order, requirements) ->
`roadmap_generator.generate` (6-8 stages with purpose, subtasks, tools, expected output, hints and machine-checkable
checks) -> `normalize_stage` (guards text, drops invalid checks, adds baseline checks) -> a fixed **Final Validation and
Project Completion** task is appended (source, syntax, README, 80+ words, tests present, tests pass for Python). If the
LLM fails twice the **template roadmap** is used and the student is told. No schema change was needed for subtasks/tools.

## 14. Task management
`tasks.status`: `locked` -> `active` -> `passed`. Exactly one task is active. `progress_tracker.mark_passed` marks the task
passed, activates the next, refreshes `project_progress` and sets the project `completed` after the last task. Attempts are
counted per submission. Asking about tasks never changes status.

## 15. File upload and code review
`Upload file` accepts source files, notebooks, documents, data samples, images and ZIPs (allow-list in `utils/security.py`;
25 MB per file, 60 MB per submission, 400 files). ZIPs are extracted safely (no `..`, absolute paths, symlinks, nested
archives, executables, or oversize/zip-bomb content). `file_reader` produces a `Bundle` (text read with encoding fallback,
notebooks split into code/markdown, CSV only first rows, PDF/DOCX text if `pypdf`/`python-docx` are installed, images stored
but not analysed). `code_analyzer` extracts functions, classes, imports, tests, manifests, frameworks, long functions.
The student can also submit a typed answer (saved as `answer.md`). The **review report** lists files, what is correct,
what is missing, detected errors, quality notes, suggestions, validation result, checks that could not be performed and the
next action. Statuses: Pending Review, Under Review, Passed, Needs Improvement, Failed Validation.

## 16. Validation engine
* **Rule checks** (deterministic): `has_source_files`, `file_exists`, `syntax_valid`, `uses_any/all`, `defines_function`,
  `defines_class`, `text_mentions`, `text_min_words`, `min_lines`, `tests_present`, `tests_pass`, `runs_ok`. Hard checks
  (files, syntax, tests, run) give **Failed Validation**; content checks give **Needs Improvement**.
* **Static analysis (nothing executed):** Python `ast` + `ruff`; JavaScript `node --check`; PHP `php -l`; Ruby `ruby -c`; Go
  `gofmt -e`; C/C++ `gcc`/`g++ -fsyntax-only`; Java `javac -proc:none`; R `parse()`; SQL `sqlfluff`; HTML tag balance. Missing
  tools are reported as "could not be performed".
* **Execution:** Python tests/entry point only, in a throw-away copy, with timeout and CPU/file/memory limits, and only when the
  OS can isolate the network (`unshare`, Linux). **On Windows student code is never executed.**
* **AI review:** a JSON review of the files against the task; it may only make the decision **stricter**. Instructions
  inside submitted files are ignored. If the AI is unavailable, rule checks alone can pass work and the report says so.
* **Decision:** see `validation_engine.decide`. Only **Passed** unlocks the next task.

## 17. Learning resources
`resource_manager.CATALOG` holds 62 technologies (Python, Pandas, NumPy, Matplotlib, Seaborn, Scikit-learn, TF-IDF, Logistic
Regression, Random Forest, NLTK, spaCy, Streamlit, Flask, Git, GitHub, Java, JDBC, Maven, JUnit, JavaScript, React, SQL,
SQLite, Docker, Ollama, FAISS, ...). Each entry has a description, key concepts, the **official documentation** and **direct
topic links with the source name**. Rules: URLs only come from this catalog (the LLM is told not to write URLs and every URL it
writes that is not in the catalog is removed); an unknown technology gets no link, only a note to search its official site.
Where it appears: (1) the opening message ("Recommended tools and where to learn them", with the tasks that use each tool);
(2) answers about libraries, learning and concepts; (3) "Before you start, read:" under a task explanation; (4) the
Learning Resources screen: a *Learning path* note plus one note per technology (sections 1-9). Notes exist immediately
(offline); AI-written notes in the student's language replace them when generated (idle only, or via *Regenerate with AI*).
The links were curated manually; run `py main.py --check-links` (internet needed) to verify them - they were **not**
verified from the development environment.

## 18. Error handling
* LLM unreachable / key / model problems: friendly message; workflow answers (roadmap, any task, next step, libraries) are
  served from the database; submissions still get rule-based review.
* Invalid LLM JSON: one retry, then template roadmap / review without AI.
* Streaming interruption: the partial answer is dropped and a notice is shown.
* Uploads: rejected types/oversize/unsafe ZIP members are listed in the report, never silently ignored.
* Unexpected exceptions in background tasks are logged (`storage/app.log`) and shown in a dialog; the UI never freezes.
* Missing tools for static analysis are reported, never faked.

## 19. Configuration
Order: `storage/settings.json` (Settings screen) > environment/`.env` > defaults (`config.py`).
| Key | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` | ollama / llama3.1 (`llama3.2:3b` in `.env.example`) | model access |
| `LLM_TEMPERATURE`, `LLM_TIMEOUT` | 0.4, 180 | sampling, wait time (seconds) |
| `LLM_NUM_CTX`, `LLM_KEEP_ALIVE` | 4096, 30m | Ollama context and model residency |
| `CHAT_MAX_TOKENS` | 900 | cap of a normal answer |
| `AUTO_AI_NOTES` | idle | `off` disables background AI notes |
| `EMBEDDING_BACKEND`, `EMBEDDING_MODEL` | hash | RAG embeddings |
| `THEME` | dark | dark/light/system |
| `CODE_EXECUTION` | auto | `off` disables the sandbox entirely |
| `MENTOR_STORAGE_DIR` | `storage/` | relocate DB/uploads/index (used by tests) |
Limits in `config.py`: upload sizes, file counts, `MAX_SNIPPET_LINES` (3), sandbox timeout (25 s) and memory.

## 20. Dependencies
Required: `customtkinter`, `requests`, `numpy`, `faiss-cpu` (NumPy fallback exists). Recommended: `ruff`, `pytest`. Optional:
`pypdf`, `python-docx`, `sentence-transformers`. External: an LLM (Ollama or a cloud API); optional language toolchains
(node, php, ruby, go, gcc, javac, Rscript, sqlfluff) for static checks of those languages.

## 21. Limitations
* **Not tested on Windows or macOS** by the developer; tested on Linux (Python 3.12) including the GUI under a virtual display.
* **No real LLM was used in testing.** The 40 automated tests use fake/recorded providers and a fake Ollama server. They prove
  routing, state handling, guard, streaming and fallbacks - not the wording quality of a real model.
* The 5-second first-response target depends on the student's hardware and model and has **not** been demonstrated; see section 9.
* Intent routing and language detection are heuristics; unusual phrasing may be misread. Tanglish vocabulary is a fixed list.
* The no-code guard is heuristic. Students can still copy short snippets (max 3 lines) and pseudocode.
* Windows: student code is never executed (no network isolation available); tests/run checks are reported as "could not be
  performed". Static checks for non-Python languages need the language toolchain installed. ESLint, Checkstyle, PHPStan, Lintr,
  Semgrep, Tree-sitter and Pylint are **not** integrated.
* Curated links are not live-verified (use `--check-links`); only the 62 catalogued technologies have links.
* Small models may fail to produce valid roadmaps (template fallback) and answer weakly in Tamil/Tanglish.
* Conversation memory is a sliding window (8 messages) plus the full roadmap and state rebuilt from SQLite every turn.
* Images in submissions are stored but not analysed. No drag-and-drop. Emoji are stripped from display (Tk limitation).
* One local user; no login; API keys, if entered in Settings, are stored in plain text in `storage/settings.json`.

## 22. Troubleshooting
See the Windows table in [README.md](../README.md#step-8---troubleshooting-windows). Additional developer checks:
* Wrong answers / refusals: look at the `chat timings:` and `intent` in `storage/app.log` / message metadata; run
  `py -m pytest -q tests/test_conversation.py`.
* A link does not open: `py main.py --check-links`, fix the URL in `learning/resource_manager.py`.
* Slow answers: `py main.py --benchmark`; compare `first_token_s`, `model_load_s`, `prompt_eval_s`, `tokens_per_s` in the log.
* Reset everything: close the app, delete `storage\mentor.db*` and `storage\index\*`.
