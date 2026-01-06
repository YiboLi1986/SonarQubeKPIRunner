# SonarQube KPI Runner

### AI-Driven Code Quality Governance Pipeline

**SonarQube KPI Runner** is an end-to-end, automated **code quality analysis and visualization pipeline** designed for large-scale codebases, especially  **C/C++ multi-module systems** .

It extracts Bugs and Issues from  **SonarQube** , enriches them with source-code context (snippets / bug blocks / callsites), leverages **LLMs (e.g., GPT-4.1 / Copilot)** to generate structured explanations and remediation advice, and finally exports the results to  **CSV** , which can be automatically synchronized to **OneDrive → Power BI** for continuous quality governance, trend analysis, and KPI reporting.

---

## What Can You Do with It?

* ✅ Turn SonarQube issues into analyzable data assets (JSON / JSONL / CSV)
* ✅ Automatically generate **explanations and remediation suggestions** for each issue using LLMs
* ✅ Optionally enrich issues with stronger context (bug blocks / callsites) to improve suggestion quality
* ✅ Sync results to OneDrive as a stable data source for Power BI
* ✅ Archive outputs by project and timestamp for historical replay and auditing

---

## Pipeline Overview (From SonarQube to Power BI)

<pre class="overflow-visible! px-0!" data-start="1308" data-end="1528"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-text"><span><span>SonarQube
  ↓  (list issues)
Issues Snapshot (raw)
  ↓  (optional: snippets / bug blocks / callsites)
Context Enrichment
  ↓  (LLM review)
Advice JSON / JSONL
  ↓  (export)
CSV
  ↓  (sync)
OneDrive → Power BI
</span></span></code></div></div></pre>

---

## Highlights

* **End-to-End Automation**

  From SonarQube ingestion → LLM review → CSV export → OneDrive → Power BI
* **Context-Aware Analysis**

  Supports bug block and callsite–level context (function / call location granularity) to improve remediation quality
* **Robust Synchronization**

  Uses temporary files and atomic replacement to prevent partial OneDrive syncs
* **Modular Architecture**

  Clear separation between ingestion, context extraction, LLM review, export, and publishing
* **Replayable Outputs**

  Timestamped outputs enable historical trend analysis and governance reviews

---

## Project Structure (Aligned with Current Codebase)

> The structure below reflects the actual layout under `backend/src/`.

<pre class="overflow-visible! px-0!" data-start="2278" data-end="4737"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-text"><span><span>SONARQUBEKPIRUNNER/
├── backend/
│   └── src/
│       ├── config/
│       │   └── github_models.local.json          # LLM configuration (local/example)
│       │
│       ├── data_io/
│       │   ├── file_reader.py                    # Generic file reader
│       │   ├── file_writer.py                    # Generic file writer
│       │   └── jsonl_to_csv_exporter.py          # JSONL → CSV exporter
│       │
│       ├── dependency/
│       │   ├── bug_block_extractor.py            # Bug block (function/context) extraction
│       │   ├── bug_reference_scanner.py          # Reference / linkage scanning
│       │   └── cpp_dependency_extractor.py       # C++ dependency extraction (optional)
│       │
│       ├── doc/
│       │   └── issue_intelligence_keypoints.md   # Design notes and key ideas
│       │
│       ├── evaluations/
│       │   └── bugs/
│       │       ├── sq_bug_block_advisor.py       # ✅ Entry: Bug-block-level LLM advisor
│       │       └── sq_bug_callsite_advisor.py    # ✅ Entry: Callsite-level LLM advisor
│       │
│       ├── sonar/
│       │   └── sq_issue_advisor.py               # Issue-level advisor (legacy/optional)
│       │
│       ├── llm/
│       │   ├── config_loader.py                  # Model config loader
│       │   ├── copilot_client.py                 # Copilot / OpenAI client wrapper
│       │   └── llm_handler.py                    # Unified LLM invocation layer
│       │
│       ├── powerbi/
│       │   ├── one_drive_publisher.py            # OneDrive publisher
│       │   └── power_bi_refresher.py             # Power BI refresh (optional)
│       │
│       ├── prompts/
│       │   ├── system.bug_block.review.txt
│       │   ├── system.bug_callsite.review.txt
│       │   ├── system.sonar.review.txt
│       │   ├── user.bug_block.review.txt
│       │   ├── user.bug_callsite.review.txt
│       │   └── user.sonar.review.txt
│       │
│       ├── outputs/                              # All generated artifacts (archived)
│       │   ├── HysysEngine.Engine.issues/
│       │   ├── HysysEngine.Engine.bugs/
│       │   ├── HysysEngine.Engine.dependency/
│       │   └── evaluations/
│       │       └── <PROJECT_KEY>/
│       │           ├── bug_blocks/<timestamp>/
│       │           └── bug_callsites/<timestamp>/
│       │
│       └── main.py                               # Future unified pipeline entry
│
├── Flowchart_cn.md
├── Flowchart_en.md
├── README.md
└── requirements.txt
</span></span></code></div></div></pre>

---

## Output Files

Typical output paths (archived by project and timestamp):

### Issue-Level Data

* `backend/src/outputs/HysysEngine.Engine.issues/issues_raw.jsonl`
* `backend/src/outputs/HysysEngine.Engine.issues/issues_with_snippets.jsonl`

### Bug-Level Enriched Data

* `backend/src/outputs/HysysEngine.Engine.bugs/bugs_with_anchors_and_calls.json`

### LLM Review Results

* **Bug Block level**
  * `backend/src/outputs/evaluations/<PROJECT_KEY>/bug_blocks/<timestamp>/bugs_with_bug_block_advice.jsonl`
* **Callsite level**
  * `backend/src/outputs/evaluations/<PROJECT_KEY>/bug_callsites/<timestamp>/bugs_with_bug_callsite_advice.jsonl`

### Power BI–Ready CSV (examples)

* `issues_with_advice.csv`
* `bugs_with_*_advice.csv`

  (exact schema depends on the exporter)

---

## How to Run (Current Main Entry Points)

At the moment, the **most stable and direct way to run the pipeline** is via:

* `sq_bug_block_advisor.py`
* `sq_bug_callsite_advisor.py`

These scripts:

* Read input JSON / JSONL (e.g., `bugs_with_anchors_and_calls.json`)
* Load system and user prompts
* Invoke the LLM to generate advice
* Write results to `outputs/evaluations/.../<timestamp>/`

---

### 1) Environment Setup

<pre class="overflow-visible! px-0!" data-start="5945" data-end="5988"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-bash"><span><span>pip install -r requirements.txt
</span></span></code></div></div></pre>

Make sure you have:

* SonarQube access token / base URL (if required by your setup)
* LLM configuration (`backend/src/config/github_models.local.json`)
* A local OneDrive sync folder (if Power BI publishing is enabled)

---

### 2) Run: Bug Block–Level Advice (Recommended First)

<pre class="overflow-visible! px-0!" data-start="6271" data-end="6342"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-bash"><span><span>python backend/src/evaluations/bugs/sq_bug_block_advisor.py
</span></span></code></div></div></pre>

**Best for:**

* Minimal but sufficient context (function / class vicinity)
* Lower token usage
* Faster execution and lower failure rate

**Output example:**

* `backend/src/outputs/evaluations/<PROJECT_KEY>/bug_blocks/<timestamp>/bugs_with_bug_block_advice.jsonl`

---

### 3) Run: Callsite-Level Advice (Richer Context)

<pre class="overflow-visible! px-0!" data-start="6666" data-end="6740"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-bash"><span><span>python backend/src/evaluations/bugs/sq_bug_callsite_advisor.py
</span></span></code></div></div></pre>

**Best for:**

* Complex bugs spanning multiple modules
* Scenarios where callsite or reference context improves accuracy

**Output example:**

* `backend/src/outputs/evaluations/<PROJECT_KEY>/bug_callsites/<timestamp>/bugs_with_bug_callsite_advice.jsonl`

---

## LLM and Prompt Configuration

### Prompt Templates (Versioned & Auditable)

All prompts are stored under:

* `backend/src/prompts/system.*.txt`
* `backend/src/prompts/user.*.txt`

This ensures:

* Prompt versions are tracked in Git
* Output quality changes can be traced back to prompt updates

### LLM Configuration

Local / enterprise model settings are defined in:

* `backend/src/config/github_models.local.json`

> **Note:**
>
> Tokens and sensitive credentials should be stored locally or via environment variables and excluded via `.gitignore`.

---

## OneDrive → Power BI Integration (Optional)

After exporting JSONL to CSV:

* `one_drive_publisher.py` performs atomic sync to a local OneDrive folder
* `power_bi_refresher.py` (optional) triggers dataset refresh via Power BI REST API

**Typical use cases:**

* Near–real-time dashboard updates
* Turning code quality governance into measurable KPIs

---

## Roadmap

> This roadmap describes the evolution of the system  **beyond the current stable analysis and recommendation capabilities** ,
>
> toward a  **collaborative, verifiable, and governable AI-assisted code quality remediation loop** .

---

### I. Core Engineering Enhancements (Pipeline & Infrastructure)

* [ ] Introduce a unified **`PipelineRunner`** entry point

  *(orchestrating: SonarQube ingestion → context enrichment → LLM review → CSV export → publishing)*
* [ ] Support scheduled execution

  *(GitHub Actions / Windows Task Scheduler)*
* [ ] Strengthen **CSV / JSON schema validation**

  *(to ensure long-term stability of Power BI ingestion)*
* [ ] Add failure categorization and metrics

  *(token limits, LLM invocation failures, parsing errors, etc.)*

---

### II. Human-in-the-loop Remediation Workflow

* [ ] Generate **temporary patch / diff artifacts** based on LLM review results
  * Containing proposed code changes
  * Bundled with original code snippets and contextual explanations
  * Patches are treated as  **candidate drafts** , not direct modifications to the main branch
* [ ] Deliver patches back to developer repositories via **PRs or temporary branches**
  * Developers review patches directly in their IDEs
  * Perform necessary refinements (style, edge cases, business semantics)
* [ ] Introduce an explicit **Developer Feedback mechanism**
  * accept / partial accept / reject
  * Lightweight reason tags (insufficient context, logic mismatch, style concerns, etc.)

---

### III. Iterative Validation and Repair Loop

* [ ] Automatically trigger after PR merge or revision
  * CI builds
  * SonarQube re-analysis
* [ ] If issues are not fully resolved or new issues are introduced
  * Capture failure signals
  * Enter the next round of LLM-assisted remediation with failure-aware context

---

### IV. Long-term Governance and Trend Analysis

* [ ] Mark issues that fail across multiple iterations as **hard cases**
  * Persist failure types, contextual features, and module distribution
* [ ] Perform time-based aggregation and analysis
  * Identify rules or modules with low remediation success rates
  * Determine which issue categories are better handled manually
* [ ] Distill key metrics into governance-level KPIs
  * Fix success rate
  * Developer acceptance rate
  * Mean Time To Resolution (MTTR)
  * Number of remediation iterations

---

## License / Notes

This project is intended for internal engineering quality governance and automation.

If open-sourcing, consider removing or anonymizing internal project names, paths, tokens, and SharePoint / OneDrive references.
