PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    class_level TEXT NOT NULL,
    preferred_language TEXT NOT NULL DEFAULT 'en'
        CHECK (preferred_language IN ('en', 'te')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS teachers (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY,
    subject_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    class_level TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    stream TEXT NOT NULL DEFAULT '',
    content_status TEXT NOT NULL DEFAULT 'complete'
        CHECK (content_status IN ('complete', 'draft'))
);

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    topic_key TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    sequence_number INTEGER NOT NULL DEFAULT 0 CHECK (sequence_number >= 0),
    UNIQUE (subject_id, topic_key),
    UNIQUE (subject_id, name)
);

CREATE TABLE IF NOT EXISTS topic_prerequisites (
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    prerequisite_topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    PRIMARY KEY (topic_id, prerequisite_topic_id),
    CHECK (topic_id <> prerequisite_topic_id)
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    question_key TEXT NOT NULL UNIQUE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    difficulty INTEGER NOT NULL CHECK (difficulty BETWEEN 1 AND 5),
    prompt TEXT NOT NULL,
    options_json TEXT NOT NULL CHECK (json_valid(options_json)),
    correct_answer TEXT NOT NULL,
    explanation_en TEXT NOT NULL,
    explanation_te TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS diagnostic_sessions (
    session_key TEXT PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    requested_question_limit INTEGER NOT NULL DEFAULT 15 CHECK (requested_question_limit > 0),
    question_limit INTEGER NOT NULL CHECK (question_limit > 0),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'completed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS diagnostic_topic_results (
    session_id TEXT NOT NULL REFERENCES diagnostic_sessions(session_key) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    questions_asked INTEGER NOT NULL CHECK (questions_asked >= 0),
    correct_count INTEGER NOT NULL CHECK (correct_count >= 0),
    percentage REAL NOT NULL CHECK (percentage BETWEEN 0 AND 100),
    label TEXT NOT NULL CHECK (label IN ('Weak', 'Medium', 'Strong')),
    PRIMARY KEY (session_id, topic_id)
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES questions(id),
    session_id TEXT NOT NULL,
    attempt_type TEXT NOT NULL DEFAULT 'diagnostic'
        CHECK (attempt_type IN ('diagnostic', 'practice')),
    answer TEXT NOT NULL,
    is_correct INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
    response_time_seconds REAL NOT NULL CHECK (response_time_seconds >= 0),
    presented_difficulty INTEGER NOT NULL CHECK (presented_difficulty BETWEEN 1 AND 5),
    answered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS mastery (
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    score REAL NOT NULL DEFAULT 0.0 CHECK (score BETWEEN 0.0 AND 1.0),
    status TEXT NOT NULL DEFAULT 'Developing'
        CHECK (status IN ('Weak', 'Developing', 'Strong')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (student_id, topic_id)
);

CREATE TABLE IF NOT EXISTS study_plans (
    id INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    generation INTEGER NOT NULL DEFAULT 1 CHECK (generation > 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'archived')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS study_plan_topics (
    plan_id INTEGER NOT NULL REFERENCES study_plans(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    label TEXT NOT NULL CHECK (
        label IN ('Weak', 'Medium', 'Strong', 'Developing', 'Full syllabus')
    ),
    questions_asked INTEGER,
    correct_count INTEGER,
    percentage REAL,
    PRIMARY KEY (plan_id, topic_id)
);

CREATE TABLE IF NOT EXISTS plan_tasks (
    id INTEGER PRIMARY KEY,
    plan_id INTEGER NOT NULL REFERENCES study_plans(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    task_type TEXT NOT NULL CHECK (task_type IN ('lesson', 'example', 'practice', 'revision')),
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes BETWEEN 5 AND 15),
    scheduled_for TEXT NOT NULL,
    sequence_number INTEGER NOT NULL CHECK (sequence_number >= 0),
    is_completed INTEGER NOT NULL DEFAULT 0 CHECK (is_completed IN (0, 1)),
    completed_at TEXT,
    UNIQUE (plan_id, sequence_number)
);

CREATE TABLE IF NOT EXISTS explanation_cache (
    id INTEGER PRIMARY KEY,
    cache_key TEXT NOT NULL UNIQUE,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    language TEXT NOT NULL CHECK (language IN ('en', 'te')),
    mode TEXT NOT NULL CHECK (mode IN ('explain', 'hint', 'practice')),
    model_name TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    explanation TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_topics_subject ON topics(subject_id);
CREATE INDEX IF NOT EXISTS idx_questions_subject_topic ON questions(subject_id, topic_id, active);
CREATE INDEX IF NOT EXISTS idx_diagnostic_sessions_student_status
    ON diagnostic_sessions(student_id, status);
CREATE INDEX IF NOT EXISTS idx_diagnostic_results_student_subject
    ON diagnostic_topic_results(student_id, subject_id, session_id);
CREATE INDEX IF NOT EXISTS idx_attempts_student_session ON attempts(student_id, session_id, answered_at);
CREATE INDEX IF NOT EXISTS idx_mastery_student ON mastery(student_id);
CREATE INDEX IF NOT EXISTS idx_study_plans_student_status ON study_plans(student_id, status);
CREATE INDEX IF NOT EXISTS idx_plan_tasks_plan_schedule ON plan_tasks(plan_id, scheduled_for);
