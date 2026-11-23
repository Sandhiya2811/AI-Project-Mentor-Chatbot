# AI Project Mentor - Student Guide

Your mentor teaches you how to build your project; **you write the code**. It will explain, give hints, pseudocode and
documentation - never a finished solution.

## 1. Start a project
1. Open the app (`py main.py`). The home screen says **Create Your Project**.
2. Type your idea in your own words and language (for example "I want to build a Student Performance Predictor" or
   "Fake News Detection project pannanum") or click one of the examples.
3. Press **Start Your Project**. The mentor creates your roadmap, then its first message appears word by word:
   the objective, all stages, **Task 1**, and the **tools you need with official learning links**.

## 2. Talk naturally - in any language
Write the way you like: English, Tamil, Tanglish, Hindi, Telugu, Malayalam, Kannada... The mentor answers in the language
of **each message** and switches when you switch. You can also ask: "Explain this error in Tamil." There is no language
setting to change. Examples that work:

| You write | The mentor |
|---|---|
| `Libraries ennalam venum?` / `Which libraries should I install?` | Lists only the libraries your project needs, why, and where to learn them (official links). |
| `Task 2 explain pannunga` / `Task 3 la enna irukku?` | Explains that task: purpose, steps, tools, expected output. Works for **any** task, even future ones (shown as a preview). |
| `Ella tasks um explain pannu` / `Explain the full roadmap` | Explains every task and where you are now. |
| `Okay, I understand` | Short reply; it does not repeat the explanation and does not count the task as done. |
| `Next enna?` / `Next task polam` / `Task 2 ku move pannalam` | Checks your progress. If the current task is not validated yet it tells you what is missing and how to submit. If it is validated, it starts the next task. |
| `Why Pandas?` / `Feature scaling ethuku?` / `Which algorithm should I use?` | Answers for **your** project. |
| `Why am I getting ModuleNotFoundError?` | Explains the error and how to investigate - it does not give you the fixed code. |

Questions that have nothing to do with your project or programming (weather, cricket, movies...) get a polite reminder
to focus on the project.

## 3. Finish a task - Submit for review
Saying "I finished" or "next" **never** completes a task. Only a successful review does.
1. Do the task yourself.
2. Above the message box switch to **Submit for review**. (Attaching a file switches it automatically.)
3. Either type your written answer (for understanding/planning tasks) or press **Upload file** and choose your code file(s),
   notebook, documents or a **ZIP** of your project folder, then **Send**.
4. Read the **Review Report**: what is correct, what is missing, detected errors, quality notes, suggestions, the result and
   the next action. Result meanings:
   * **Passed** - the task is complete; the next task is unlocked and explained.
   * **Needs Improvement** - something required is missing; fix it and submit again.
   * **Failed Validation** - something basic failed (missing files, syntax error, failing tests); fix it and submit again.
5. Resubmit as often as needed. Each submission is saved.

## 4. Roadmap, progress and history
* **Roadmap** button (top right of the chat): all tasks with status (completed / current / locked). Locked tasks show only
  their title; ask the mentor if you want a preview.
* The progress bar shows completed tasks.
* **Chat History** (left): every project has its own conversation. Click to restore it (with project, task and
  submissions), use `...` to rename or delete, and the search box to find old chats. **New Chat** starts a new project
  without deleting anything. **Previous Projects** lets you resume or delete a project. **Clear Chat History** deletes
  conversations only (projects and submissions are kept).

## 5. Learning Resources
Open **Learning Resources** (left menu), choose your project, and read the notes: a **Learning path** (what to learn, in which order,
and which tasks need it) and one note per technology. The format is always:

```
1. Python  (needed for: Task 1, Task 6)
Official Documentation - Python documentation
Start with - The Python Tutorial
Start with - Virtual environments and packages
```
Every title is a **link**: click it and the page opens in your browser (if the browser cannot be opened the address is copied for
you). Only the technologies your project needs are shown, and "Start here" names the tools for your current task. Notes marked
*(offline)* are ready instantly; AI-written notes in your language appear when you are idle, or press **Regenerate with AI**.
If no link is known the note says so - the app never guesses a web address.

## 6. Settings and profile
* **Settings > AI model:** choose the AI **provider** (OpenAI ChatGPT, Anthropic Claude, Google Gemini, Perplexity, Z.ai GLM, or the
  optional local Ollama), pick a **model**, paste your **API key**, press **Save**. The **Connection** line tells you whether the key
  and model work. **Test connection** checks without saving; **Refresh models** lists the models your account can use. Each provider
  remembers its own model and key; the key is kept in a secure store and shown only as `******1234`. Ask your teacher/admin for a key
  or see the API key guide in `README.md`.
* Other settings: theme, knowledge-base mode, code-execution mode.
* **User Profile:** your name, skill level, and the language used for *learning notes* (chat language is automatic).

## 7. If something does not work
* "AI model not ready" on the home screen: the message says why - a missing or rejected API key, a wrong model, no credit/quota, no
  internet, or a timeout. Fix it in **Settings > AI model**, then **Test connection**. The app never switches to another provider on its own.
  Without the AI you can still read the roadmap, ask about tasks, next steps and libraries (answered from your saved roadmap),
  read the offline notes, and submit work for rule-based review.
* Slow answers: choose a faster model in Settings (for example `gpt-4o-mini`, `claude-haiku-5-5`, `gemini-2.5-flash`). Ask your teacher/admin to run `py main.py --check-providers`.
* Windows setup problems: see the Troubleshooting table in `README.md`.
