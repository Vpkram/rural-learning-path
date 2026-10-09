# Personalized Learning Path

A local-first adaptive learning application for students. The project currently
includes its SQLite foundation, adaptive diagnostic backend, local textbook
retrieval, and an Ollama-based grounded tutor.

## Stage 1 setup

Use Python 3.14.4. From the project root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m db.seed
```

The seed command creates `data/learning_path.db` and discovers every subject
pack in `data/subjects/<class>/<subject>/`. It is safe to rerun: seeded
subjects, topics, prerequisite links, and questions are updated without
deleting student records or attempts. The original root-level DBMS JSON files
remain as compatibility inputs for earlier modules and tests.

Run the Stage 1 database checks with:

```powershell
python -m pytest
```

The seeder also supports direct script execution with `python db/seed.py`.
Both seed commands use the same database and are safe to repeat.

## Stage 3: local textbook retrieval

Add a PDF or DOCX textbook, then search it from the project root:

```powershell
python -m rag.indexer "data\textbooks\your-book.pdf" --query "What is normalization?"
```

DOCX files do not have reliable stored page boundaries, so their retrieved
chunks show that the page is unavailable. PDF chunk results retain one-based
page numbers. Chunk size and overlap are measured in characters. Embeddings
run locally on CPU and are cached under `data/embeddings/`. The embedding model
must already be available locally; the app will not download it automatically.
Retrieval returns only chunks above the threshold; it does not call or generate
a tutor answer.

Run the focused tests with Python 3.14.4:

```powershell
python -m pytest tests/test_rag_loader.py tests/test_rag_cleaner_chunker.py tests/test_rag_embeddings.py tests/test_rag_indexer.py tests/test_rag_retriever.py tests/test_database.py -q
```

When nothing meets the similarity threshold, the search reports
`This topic was not found in the textbook.` Tutor generation is separate from
the retriever: it accepts retrieval results and will not contact Ollama when
there are no qualifying chunks.

## Stage 4: Ollama tutor

Start Ollama on this computer and inspect the models already installed:

```powershell
ollama list
```

If there is no suitable local model, choose to install one explicitly. The
application never downloads a model:

```powershell
ollama pull llama3
```

The tutor defaults to `llama3:latest`, then tries installed fallback models in
this order: `llama3.2:3b`, `qwen2.5:7b`, `qwen2.5:3b`. It sends one generation
request at a time, asks Ollama to keep the active model loaded for five minutes,
and reports connection, timeout, or model errors rather than returning a
fabricated response. Curated Telugu topic notes and question explanations are
used before Telugu generation; generated Telugu is labeled for teacher review.
Successful tutor responses are cached in SQLite.

The tutor service is called with a `RetrievalResult` created by the Stage 3
retriever. For example, the service
interface is `core.llm_tutor.tutor_response(connection, retrieval, topic_id=...,
topic_key=..., question=...)`; callers should provide a successful retrieval
result from the actual textbook query rather than construct one themselves.

Run the focused tutor and related tests with Python 3.14.4:

```powershell
python -m pytest tests/test_ollama_tutor.py tests/test_rag_retriever.py tests/test_database.py -q
```

## Stage 5: study plans and topic videos

Diagnostic tests show checked-answer feedback before advancing, then retain a
score, a result for every topic, and a review of every answer. A test includes
at least two questions per topic in the selected subject; a smaller requested
count is increased automatically. Study plans use the latest diagnostic for
that same subject: weak topics get a lesson, example, practice, and spaced
revisions; medium topics get practice and one revision; strong topics are
skipped. Weak prerequisites are scheduled before dependent weak topics. If no
diagnostic exists, the Study Plan page offers the test first or an explicit
full-syllabus plan. Completing a diagnostic archives the previous active plan
and creates a plan generation from its saved results. Plan snapshots, answers,
topic results, and tasks are stored in SQLite and remain scoped to the learner
and selected subject.

The legacy Stage 5 recommender tests still exercise `data/videos.csv`.
The student app now reads each selected pack's `videos.json`; old CSV links
are retained only as unverified review data and are never embedded.

Check the sample data from the project root:

```powershell
python -m scripts.validate_videos
```

Run the diagnostic, planner, and video recommender tests with the project's
Python 3.14.4 environment:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_diagnostic_study_plan_results.py tests\test_planner.py tests\test_video_recommender.py tests\test_adaptive_engine.py -q
```

## Stage 6A: student application

Start the local Streamlit student app from the project root:

```powershell
streamlit run app.py
```

The app initializes/seeds the local SQLite catalog, then offers student
registration/sign-in, class and subject selection, diagnostic sessions,
study-plan tasks and videos, and the grounded tutor. Passwords are bcrypt
hashes; the app stores only the local learner profile in Streamlit session
state. Settings are session-local in this foundation stage. Add a PDF/DOCX
through the Tutor page or place one in `data/textbooks/` to enable retrieval.
Textbook indexing runs in the background in embedding batches, reports page
and chunk progress, supports cancellation, and can be limited to a page range.
Unexpected UI errors show a friendly message while the traceback is written
to the terminal and `logs/app.log`.
Teacher dashboard features are not part of Stage 6A.

Run the auth and full application logic tests with Python 3.14.4:

```powershell
python -m pytest
```

## Data-driven class and subject packs

Each subject is discovered from a folder containing `topics.json`,
`questions.json`, `meta.json`, and `videos.json`:

```text
data/subjects/
  Class 1/ ... Class 10/
    <subject>/
  Class 11/ and Class 12/
    <stream>/<subject>/
  College/
    <subject>/
```

Each topic lists prerequisite topic keys. Questions have difficulty,
options, a correct answer, and an English explanation. The student UI falls
back to English when Telugu is selected and a pack has no Telugu copy. The
metadata records class, subject, board, language, review status, and version.
Draft packs show an under-review badge.

The generated folder matrix contains 95 packs across Classes 1-12 and College.
Classes 1-5 include English, Mathematics, Environmental Studies, Hindi, and
Telugu; Classes 6-10 include English, Mathematics, Science, Social Science,
Hindi, and Telugu. Classes 11-12 are nested under Science, Commerce, and Arts.
College contains the ten requested CSE/AI and Data Science subjects.

The current catalog contains 95 packs, 857 topics, and 3,184 question records:
2 packs are marked complete and 93 remain draft. Pack validation confirms the
configured folder coverage, topic/prerequisite alignment, and minimum record
counts; it does not certify question quality.

Only the existing DBMS and Data Mining question banks are currently marked
complete. Generated question banks remain draft until their original,
topic-specific questions are fact-checked; question count alone does not
establish educational correctness. Some target Math, Science, and College
packs already have six records per topic, but their broad review questions
must be replaced before those packs should be used as complete diagnostics.

Seed all discovered packs into SQLite (safe to rerun):

```powershell
python -m db.seed
```

Validate expected pack coverage, topic links, prerequisites/cycles, duplicate
questions, answers, explanations, video metadata, and status-based minimum
question counts with:

```powershell
python -m scripts.validate_packs
```

The app embeds a link only when it is explicitly verified and is a recognized
YouTube watch/embed/shorts/live link or direct video file. Otherwise it shows
a contextual YouTube search button. No guessed playable URLs are included.
Migrate CSV rows to unverified per-subject records with
`python -m scripts.migrate_videos`; audit missing verified topic videos and
unreachable supplied links with `python -m scripts.check_videos`.

`python -m scripts.build_curriculum_packs` regenerates the generated pack
scaffold and starter question records. It does not promote generated content
to complete status.
