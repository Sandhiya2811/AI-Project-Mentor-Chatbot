# AI Project Mentor - Technical Documentation

This document describes what is **actually implemented** (about 7,000 lines of Python in 50 modules, plus 109 automated
tests in 8 test files). Anything not implemented is listed in [21. Limitations](#21-limitations).

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
* **Cloud AI providers** (OpenAI, Anthropic, Google Gemini, Perplexity, Z.ai GLM; Ollama optional) with per-provider models,
  keys, live validation and connection status; no silent fallback to a local model.
* Settings screen (theme, provider, model list, URL, key, embeddings, sandbox), user profile, light/dark theme.
* **Clickable learning links** (opened in the default browser, validated, safe fallbacks).

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
|     |-- llm_provider  (OpenAI | Anthropic | Gemini | Perplexity | Z.ai | Ollama; streaming)  |
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
  ai_engine/                 assistant, intent_router, language_detector, prompts, llm_provider (6 providers), response_guard,
                             conversation_memory
  project_manager/           idea_analyzer, roadmap_generator, task_manager, progress_tracker
  code_review/               file_reader, language_detector, code_analyzer, report_generator, review_engine
  validation/                static_analyzer, rule_validator, executor, validation_engine
  rag/                       embeddings, knowledge_base, retriever
  learning/                  resource_manager, catalog_extra (data), notes_generator
  database/                  db, models, repository
  utils/                     helpers, security, sandbox, secrets (API-key storage + redaction)
  storage/                   knowledge/ (reference .md files), uploads/, index/, mentor.db, settings.json, app.log
  tests/                     test_core, test_conversation, test_streaming, test_providers, test_language, test_resources,
                             test_settings_ui, test_compat, fixtures/ (legacy database + settings)
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
| `ai_engine/llm_provider.py` | `OpenAIProvider`, `AnthropicProvider`, `GeminiProvider`, `PerplexityProvider`, `ZaiProvider`, `OllamaProvider`, `OpenAICompatibleProvider`: `chat`, `stream_chat`, `validate`, `list_models`, `health`; retries, error mapping, key redaction, `last_stats` timings; `build_provider`/`get_provider`/`connection_status`. |
| `utils/secrets.py` | Per-provider API-key storage (OS keyring when available), legacy-key migration, `redact()` and log redaction. |
| `learning/catalog_extra.py` | Data only: the technologies added to the learning catalog and extra "Start with" links. |
| `interface/settings_view.py` | Settings: provider selector, per-provider model list, key field, status, Test/Refresh; profile and roadmap dialogs. |
| `interface/markdown_text.py` | Markdown-lite renderer for read-only Text widgets, including **clickable links** (`open_url`). |
| `ai_engine/response_guard.py` | `check()` (complete text) and `StreamGuard` (while streaming) enforce the no-code policy. |
| `ai_engine/language_detector.py` | Per-message language hint, Tanglish/Hinglish detection, explicit language requests. |
| `ai_engine/conversation_memory.py` | Last 8 messages / 3,500 characters; review reports reduced to a stub. |
| `project_manager/roadmap_generator.py` | Validates LLM stages, adds baseline checks, appends the fixed Final Validation task, template fallback. |
| `learning/resource_manager.py` | Curated catalog (109 technologies, 271 links); link-line formatting; learning path; offline notes. |
| `learning/notes_generator.py` | Offline base notes instantly; AI notes (cancellable) per technology. |
| `code_review/review_engine.py` | Orchestrates ingest -> analysis -> validation -> AI review -> decision -> persistence. |
| `validation/validation_engine.py` | Decision policy (Passed / Needs Improvement / Failed Validation). |
| `database/repository.py` | All SQL. |
| `utils/security.py`, `utils/sandbox.py` | Safe ZIP extraction, upload rules; restricted subprocess runner. |

## 8. Application workflow
1. **Start:** `py main.py` -> `init_db()` -> window. In the background: knowledge index built, the AI provider's key/model checked (no tokens), and - only if Ollama is selected - the model loaded.
2. **Create project:** the idea goes to `idea_analyzer` (1 LLM call) and `roadmap_generator` (1 LLM call). The project, tasks,
   tools and progress are saved in one transaction; the chat opens immediately; the **opening message streams in**
   (greeting, objective, stage list, Task 1, then a deterministic "tools and where to learn them" block with official links).
   Offline learning notes are created instantly; AI notes follow only when the student is idle.
3. **Ask:** `Mentor.chat(mode="ask")` -> `_question` (see section 9 for the steps).
4. **Submit:** `mode="submit"` (or any attached file) -> `_submission` -> `review_engine.review` -> report message ->
   if **Passed**: task marked passed, next unlocked, next-task message (or completion message).
5. **Resume:** `resume_project` reopens the conversation (or writes a deterministic "welcome back" message with progress).

## 9. AI and LLM integration
**Providers** (`llm_provider.py`, registry in `config.PROVIDER_INFO`). Cloud APIs are the default (`LLM_PROVIDER=openai` on a fresh
install); nothing is downloaded to the computer. Each provider uses **its own official HTTP API** (via `requests`, no vendor SDK
is needed, so there are no extra dependencies):

| Provider | Endpoint / auth | Provider-specific handling |
|---|---|---|
| OpenAI | `POST {base}/chat/completions`, `Authorization: Bearer` | reasoning models (`gpt-5*`, `o*`) use `max_completion_tokens`, no `temperature`, `reasoning_effort=minimal` for speed; validation = `GET /models/{model}` (no tokens); live model list |
| Anthropic | `POST {base}/v1/messages`, `x-api-key` + `anthropic-version` | system prompt as a separate field; SSE `content_block_delta`; validation = `GET /v1/models/{model}`; live model list |
| Google Gemini | `POST {base}/models/{m}:generateContent` and `:streamGenerateContent?alt=sse`, `x-goog-api-key` (never in the URL) | `systemInstruction` + `contents` with roles `user`/`model`, turns merged to alternate, JSON via `responseMimeType`, `thinkingBudget=0` on 2.5 Flash for speed, safety-block errors; validation = `GET /models/{m}`; live model list |
| Perplexity | `POST {base}/chat/completions`, Bearer | strictly alternating roles (merged), JSON requested in the prompt (no JSON mode), `disable_search` so it answers like a mentor |
| Z.ai GLM | `POST https://api.z.ai/api/paas/v4/chat/completions`, Bearer | `thinking` disabled for fast first words; JSON mode |
| Ollama (optional) | `POST {base}/api/chat`, no key | `keep_alive`, `num_ctx`, warm-up; used **only** when selected |
| OpenAI-compatible | any `/chat/completions` server (LM Studio, proxies) | generic |

Shared behaviour: one `requests.Session`; streaming for all; **retries with back-off** (2 retries) for HTTP 429/5xx and dropped
connections on cloud providers (not for timeouts, quota errors or bad keys); optional speed-up parameters are **dropped
automatically** (and remembered) if a server answers HTTP 400; connect timeout 10 s and a per-provider read timeout (cloud 60 s);
errors are translated to clear messages (missing key + where to get one, rejected key, unknown model, quota/billing, rate limit,
provider outage, no internet, timeout) with every key masked; the interface shows them and the non-AI features keep working.
**There is no fallback between providers**: if the selected cloud API fails, the student sees the error; Ollama is never started
or contacted unless it is the selected provider. A provider instance is cached per configuration; `build_provider()` builds one
from explicit values (Settings "Test connection" uses the form values before anything is saved).

**Keys and status.** `utils/secrets.py` stores one key per provider: first in the OS credential store through the optional
`keyring` package (Windows Credential Manager), otherwise in `storage/settings.json` as `API_KEY_<PROVIDER>` (plain text -
Settings says so), otherwise from environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`/`GOOGLE_API_KEY`,
`PERPLEXITY_API_KEY`, `ZAI_API_KEY`). An old single `LLM_API_KEY` still works for the selected provider and is migrated to the
keyring when one exists. Keys are never written to the database, `.env.example`, UI text (masked) or logs (`redact()`,
`install_log_redaction()`). At start-up and after Save the app runs `quick_health()` (no network) and `connection_status()`
(key + model check through the API, no tokens for OpenAI/Anthropic/Gemini) and shows **AI connected: provider - model** or the
problem on the home screen and in Settings.

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

**Cloud speed notes.** With a cloud provider the startup warm-up is just the connection check (TLS reuse through the shared
session). In the test harness the application adds about 25 ms between the provider's first token and the first visible text.
Real latency depends on the provider, model, region and network and was **not measurable** without keys: use
`py main.py --check-providers` (key/model check + time to first text per provider) or `py main.py --benchmark`. The first-word
target of about 5 s is realistic for fast models (`gpt-4o-mini`, `claude-haiku-5-5`, `gemini-2.5-flash`, `glm-4.5-air`) on a normal
connection; project creation makes two sequential JSON calls (analysis, roadmap) before the streamed opening message, so it takes
longer than a normal answer.

**No-code policy.** (1) `NO_CODE_RULES` in every prompt. (2) `response_guard.check` on every AI text (chat, review text,
task text, notes): definitions of functions/classes and code blocks over 3 lines are replaced by a notice; pseudocode is
allowed; unfenced runs of 5+ code-looking lines are removed. (3) `StreamGuard` does the same while streaming. It is a
heuristic and can miss cleverly disguised code.

## 10. Multilingual processing
* Language is **never a setting**: every message is analysed on its own (`language_detector.detect`/`resolve`):
  Unicode script (Tamil, Hindi, Telugu, Kannada, Malayalam, Bengali, ...), romanised Tamil (**Tanglish**), Hindi (**Hinglish**),
  Malayalam (**Manglish**), Telugu (**Tenglish**), Kannada (**Kanglish**) from vocabulary lists, and explicit requests ("explain this
  in Tamil", "tamil la sollu"). Other Latin-script languages (Spanish, French, ...) are left to the model.
* The result becomes a rule in the system prompt: answer in exactly the language, script and register of the latest message like a
  native speaker (not a word-by-word translation); understand meaning first; follow switches immediately; for mixed text use the
  dominant language; keep programming terms in English. A **style example per language** is added (for example Tanglish must be
  Tamil in Latin letters, Tamil must be Tamil script) so the model mirrors the form, not only the language name.
* Tiny follow-ups ("ok", "next task", "why pandas?") keep the language of the conversation (`resolve`); a clear sentence in another
  language switches at once. The conversation's last language is stored (`conversations.language`).
* The fixed off-topic reply exists in 10 languages (`prompts.OFF_TOPIC_BY_LANGUAGE`); everything else is written by the model.
  Offline fallback answers (when the model is unreachable) are English.
* The profile has "Language for learning notes" only; chat replies ignore it.
* **Verified:** detection of the five required examples and eleven further sentences, the explicit-request override, the
  inheritance rule, the prompt content, and the localised refusal (`tests/test_language.py`). **Not verified:** the actual wording
  a live model produces - that needs a provider key and depends on the model (smaller models are weaker in Tamil/Tanglish).

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
`resource_manager.CATALOG` holds **109 technologies and 271 links**: programming languages (Python, Java, C, C++, JavaScript,
TypeScript, C#, PHP, Go, Rust, R, Ruby, Kotlin, Swift, Dart, Scala), data and analytics (NumPy, Pandas, Matplotlib, Seaborn, Plotly,
SQL, MySQL, PostgreSQL, MongoDB, Statistics, Excel, Power BI, Tableau), machine learning (Scikit-learn, XGBoost, LightGBM, CatBoost,
Feature Engineering, Model Evaluation, Hyperparameter Tuning), deep learning (TensorFlow, Keras, PyTorch, JAX, OpenCV, CNN, RNN,
LSTM, Transformers), AI/NLP/GenAI (NLP, Hugging Face, LangChain, LangGraph, RAG, LLMs, Prompt Engineering, Fine-Tuning, Vector
Databases, FAISS, ChromaDB, Pinecone, Ollama), web (HTML, CSS, React, Angular, Vue.js, Node.js, Express.js, FastAPI, Flask, Django, REST
APIs, GraphQL), cloud and deployment (AWS, Azure, GCP, Docker, Kubernetes, Git, GitHub, Streamlit, Render, Vercel, CI/CD) and big data
(Spark, PySpark, Hadoop, Kafka, Airflow, Databricks, ETL) - 88 requested names, all covered (`tests/test_resources.py`). Aliases
(`Vue.js`, `CI/CD`, `Google Cloud Platform`, `Feature Scaling`, ...) resolve to entries. The data lives in `resource_manager.py`
(original entries) and `catalog_extra.py` (additions and extra links); entries are merged and de-duplicated at import.

Each entry has a description, key concepts, the **official documentation** and beginner "Start with" pages with the source name.
Where a technology has no free official tutorial a clearly named reputable source is used (for example MDN, cppreference, Kaggle Learn,
Khan Academy) and the source is shown.

**Display format** (identical in chat, the Learning Resources screen and notes):
```
1. Python  (needed for: Task 1, Task 6)
Official Documentation - [Python documentation](https://docs.python.org/3/)
Start with - [The Python Tutorial](https://docs.python.org/3/tutorial/)
Start with - [Virtual environments and packages](https://docs.python.org/3/tutorial/venv.html)
```
Titles are clickable; no URL appears twice in a list; only the technologies **of the student's project** are shown, ordered in learning
order, each with the tasks that need it, plus a "Start here - Task N" line for the current task.

**Clickable links** (`interface/markdown_text.py`): `[title](https://...)` and bare URLs become underlined link-coloured tags with a hand
cursor. A click calls `open_url()`: the address must be `http(s)` with a real host (otherwise a warning is shown and nothing is opened),
it opens in a **new tab of the default browser**; if the browser cannot be started the address is copied to the clipboard and shown.
Links survive the repeated re-rendering used for streaming answers.

**No invented URLs.** URLs come only from the catalog; the LLM is told not to write URLs and every URL it writes that is not in the
catalog is removed. A technology without an entry gets no link, only a note to search its official site. The URLs were curated by
hand and are **not verified from the development environment**: run `py main.py --check-links` (internet needed). Notes exist
immediately (offline); AI-written notes in the student's language replace them when generated (idle only, or *Regenerate with AI*).

## 18. Error handling
* Cloud provider problems (missing/rejected key, unknown model, quota or billing, rate limit, outage, no internet, timeout): one
  clear message each, secrets masked, automatic retries only for transient errors, **no switch to another provider**; workflow answers (roadmap, any task, next step, libraries) are
  served from the database; submissions still get rule-based review.
* Invalid LLM JSON: one retry, then template roadmap / review without AI.
* Streaming interruption: the partial answer is dropped and a notice is shown.
* Uploads: rejected types/oversize/unsafe ZIP members are listed in the report, never silently ignored.
* Unexpected exceptions in background tasks are logged (`storage/app.log`) and shown in a dialog; the UI never freezes.
* Missing tools for static analysis are reported, never faked.

## 19. Configuration
Order: `storage/settings.json` (Settings screen) > environment/`.env` > defaults (`config.py`). API keys: see section 9.
| Key | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai`, `anthropic`, `google`, `perplexity`, `zai`, `ollama`, `openai_compatible` |
| `LLM_MODEL`, `MODEL_<PROVIDER>` | provider default | model of the active provider; the Settings screen remembers one model per provider |
| `LLM_BASE_URL`, `BASE_URL_<PROVIDER>` | provider default | server address (proxy / custom server) |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`/`GOOGLE_API_KEY`, `PERPLEXITY_API_KEY`/`PPLX_API_KEY`, `ZAI_API_KEY`/`ZHIPUAI_API_KEY` | - | keys (alternative to the Settings screen) |
| `LLM_TEMPERATURE`, `LLM_TIMEOUT` | 0.4, empty | sampling; seconds to wait (empty = cloud 60, openai_compatible 120, Ollama 180) |
| `CHAT_MAX_TOKENS` | 900 | cap of a normal answer (roadmap overview exempt) |
| `AUTO_AI_NOTES` | idle | `off` disables background AI notes |
| `LLM_NUM_CTX`, `LLM_KEEP_ALIVE` | 4096, 30m | Ollama only |
| `EMBEDDING_BACKEND`, `EMBEDDING_MODEL` | hash | RAG embeddings |
| `THEME` | dark | dark/light/system |
| `CODE_EXECUTION` | auto | `off` disables the sandbox entirely |
| `MENTOR_STORAGE_DIR` | `storage/` | relocate DB/uploads/index (used by tests) |
Provider labels, defaults, model lists, key URLs and timeouts: `config.PROVIDER_INFO`. To add a provider: add an entry there and a class in
`llm_provider.PROVIDERS`. Limits in `config.py`: upload sizes, file counts, `MAX_SNIPPET_LINES` (3), sandbox timeout (25 s) and memory.

## 20. Dependencies
Required: `customtkinter`, `requests`, `numpy`, `faiss-cpu` (NumPy fallback exists). Recommended: `keyring` (secure key storage),
`ruff`, `pytest`. Optional: `pypdf`, `python-docx`, `sentence-transformers`. **No vendor AI SDKs** are used (the providers' official
REST APIs are called directly). External: an AI provider account and key (or a local Ollama if selected); optional language
toolchains (node, php, ruby, go, gcc, javac, Rscript, sqlfluff) for static checks of those languages.

## 21. Limitations
* **No live provider API was called during development** (no keys, no internet access to the vendors). The six provider
  integrations were tested against a local server that imitates each vendor's documented wire format (URL, authentication
  header, request body, streaming, errors). That proves the application builds and parses requests the way each API
  documentation describes; it cannot prove that today's live APIs accept them unchanged. Use `py main.py --check-providers` with
  your keys - the first run on a new provider is the real test. Model names change: the lists in Settings are starting points
  (use **Refresh models** or type a model id).
* **Response time:** the first-word target of about 5 s was not demonstrated against a live provider; see section 9.
* Perplexity: `disable_search` and Z.ai: `thinking` are optional parameters; if a server rejects them the app drops them and continues.
  Gemini 2.5 Flash `thinkingBudget=0` likewise. Perplexity/Z.ai/Gemini keys are validated by a tiny request or a model lookup.
* Without the optional `keyring` package keys are stored in `storage/settings.json` in **plain text** (the Settings screen says so).
* **Not tested on Windows or macOS** by the developer; tested on Linux (Python 3.12) including the GUI under a virtual display.
* Language: detection and the instructions are tested; the model's actual wording is not. Latin-script languages other than the
  romanised Indian languages are left to the model. Tanglish/Manglish/... vocabularies are fixed lists. Offline fallback answers and
  UI texts are English.
* Intent routing is a heuristic; unusual phrasing may be misread. The no-code guard is heuristic.
* Learning links are curated by hand and not live-verified (`--check-links`); only catalogued technologies have links.
* Windows: student code is never executed (no network isolation); static checks for non-Python languages need their toolchain.
  ESLint, Checkstyle, PHPStan, Lintr, Semgrep, Tree-sitter and Pylint are not integrated.
* Small models may fail to produce valid roadmaps (template fallback). Conversation memory is a sliding window (8 messages) plus the
  roadmap and state rebuilt from SQLite every turn. Images in submissions are stored but not analysed. No drag-and-drop. Emoji are
  stripped from display (Tk limitation). One local user; no login.

## 22. Troubleshooting
See the Windows table in [README.md](../README.md#step-8---troubleshooting-windows). Additional developer checks:
* Wrong answers / refusals: look at the `chat timings:` and `intent` in `storage/app.log` / message metadata; run
  `py -m pytest -q tests/test_conversation.py`.
* A link does not open: `py main.py --check-links`, fix the URL in `learning/resource_manager.py`.
* Provider problems: Settings > Test connection (uses the form values); `py main.py --check-providers`; the message names the cause.
* Slow answers: `py main.py --benchmark`; compare `first_token_s`, `model_load_s`, `prompt_eval_s`, `tokens_per_s` in the log.
* Reset everything: close the app, delete `storage\mentor.db*` and `storage\index\*`.
