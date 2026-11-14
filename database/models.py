"""Schema + status vocabularies."""

REVIEW_STATUSES = ("Pending Review", "Under Review", "Passed", "Needs Improvement", "Failed Validation")
TASK_LOCKED, TASK_ACTIVE, TASK_PASSED = "locked", "active", "passed"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL DEFAULT 'Student',
  preferred_language TEXT NOT NULL DEFAULT 'Auto-detect',
  skill_level TEXT NOT NULL DEFAULT 'beginner',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL, idea TEXT NOT NULL, objective TEXT DEFAULT '',
  domain TEXT DEFAULT '', programming_language TEXT DEFAULT 'Python', difficulty TEXT DEFAULT 'beginner',
  roadmap_source TEXT DEFAULT 'llm', status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_requirements(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  name TEXT NOT NULL, detail TEXT DEFAULT '', position INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  position INTEGER NOT NULL, title TEXT NOT NULL, description TEXT DEFAULT '',
  expected_output TEXT DEFAULT '', deliverable_type TEXT DEFAULT 'code',
  hints_json TEXT DEFAULT '[]', checks_json TEXT DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'locked', attempts INTEGER NOT NULL DEFAULT 0, completed_at TEXT
);
CREATE TABLE IF NOT EXISTS student_submissions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  attempt_no INTEGER NOT NULL, notes TEXT DEFAULT '', status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS uploaded_files(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id INTEGER NOT NULL REFERENCES student_submissions(id) ON DELETE CASCADE,
  original_name TEXT NOT NULL, stored_path TEXT NOT NULL, size_bytes INTEGER, sha256 TEXT,
  detected_language TEXT, kind TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS validation_reports(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id INTEGER NOT NULL REFERENCES student_submissions(id) ON DELETE CASCADE,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  status TEXT NOT NULL, rule_results_json TEXT, static_results_json TEXT, llm_review_json TEXT,
  not_performed_json TEXT, report_md TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
  title TEXT NOT NULL, language TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL, content TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'chat',
  metadata_json TEXT DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_notes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  tool_name TEXT NOT NULL, language TEXT DEFAULT 'English', content_md TEXT NOT NULL,
  doc_url TEXT DEFAULT '', order_index INTEGER DEFAULT 0, source TEXT DEFAULT 'llm', created_at TEXT NOT NULL,
  UNIQUE(project_id, tool_name)
);
CREATE TABLE IF NOT EXISTS project_progress(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
  total_tasks INTEGER NOT NULL DEFAULT 0, completed_tasks INTEGER NOT NULL DEFAULT 0,
  percent REAL NOT NULL DEFAULT 0, current_task_id INTEGER, last_activity TEXT
);
CREATE TABLE IF NOT EXISTS activity_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, project_id INTEGER,
  action TEXT NOT NULL, detail TEXT DEFAULT '', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON chat_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_task_proj ON tasks(project_id, position);
"""
