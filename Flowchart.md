# 📘 Project Overview

**SonarQube KPI Runner** is an end-to-end **automated code quality analysis and governance pipeline** designed for large-scale codebases, especially  **C/C++ multi-module systems** .

It ingests Bugs and Issues from  **SonarQube** , performs **context enrichment and modeling** (snippets / bug blocks / callsites), leverages **Large Language Models (LLMs, e.g., GPT-4.1 / Copilot)** to generate structured explanations and remediation advice, and finally exports the results to  **CSV** , which can be automatically synchronized to **OneDrive → Power BI** for continuous quality governance, trend analysis, and KPI visualization.

---

# ⚙️ Pipeline Overview (Aligned with Current Implementation)

> Notes:
>
> * **Main Path** : The pipeline actually exercised by
>
> `sq_bug_block_advisor.py` and `sq_bug_callsite_advisor.py`
>
> * **Optional Steps** : Enhance context and analysis quality, but are not hard prerequisites for every run

---

## 1️⃣ SonarQube Issues / Bugs Ingestion (Main Path)

* Pull issues / bugs snapshots from SonarQube
* Supports project-level and time-window–based slicing
* Example output:
  <pre class="overflow-visible! px-0!" data-start="1350" data-end="1424"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>backend/src/outputs/HysysEngine.Engine.issues/issues_raw.jsonl
  </span></span></code></div></div></pre>

---

## 2️⃣ (Optional) Component Indexing & Dependency Preprocessing

> This stage builds a **structural view of the codebase** to support richer context modeling downstream.

* Component and file path indexing
* Optional local source snapshot
* C/C++ dependency and reference scanning
* Typical outputs:
  <pre class="overflow-visible! px-0!" data-start="1733" data-end="1795"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>backend</span><span>/src/</span><span>outputs</span><span>/HysysEngine.Engine.dependency/</span><span>
  </span></span></code></div></div></pre>

> ⚠️
>
> The current LLM advisors can run directly on  **pre-enriched bugs / anchors data** .
>
> This step is **not a mandatory prerequisite** for execution.

---

## 3️⃣ Context Enrichment (Main Path)

Issues and bugs are progressively enriched with increasing levels of context:

* **Issue Snippets**
  * Line-level context (issue line ± N lines)
* **Bug Blocks**
  * Function / class–level *minimum viable context*
  * Optimized for token efficiency and stability
* **Callsites / Anchors**
  * Call locations and related references
  * Suitable for cross-module and dependency-heavy bugs

Example output:

<pre class="overflow-visible! px-0!" data-start="2412" data-end="2452"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>bugs_with_anchors_and_calls.json
</span></span></code></div></div></pre>

---

## 4️⃣ LLM Review & Advice Generation (Core Stage)

Different advisors are selected based on context granularity:

* **Bug Block Advisor**
  * Minimal but sufficient context
  * Token-efficient, fast, and low failure rate
  * Entry script:
    <pre class="overflow-visible! px-0!" data-start="2703" data-end="2742"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>sq_bug_block_advisor.py
    </span></span></code></div></div></pre>
* **Callsite Advisor**
  * Richer context (callsites / references)
  * Designed for complex, cross-module issues
  * Entry script:
    <pre class="overflow-visible! px-0!" data-start="2879" data-end="2921"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>sq_bug_callsite_advisor.py
    </span></span></code></div></div></pre>

Example outputs:

<pre class="overflow-visible! px-0!" data-start="2940" data-end="3122"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>backend</span><span>/src/</span><span>outputs</span><span>/evaluations/</span><span><</span><span>PROJECT_KEY</span><span>>/</span><span>
 </span><span>├──</span><span> bug_blocks</span><span>/<timestamp>/</span><span>bugs_with_bug_block_advice.jsonl
 </span><span>└──</span><span> bug_callsites</span><span>/<timestamp>/</span><span>bugs_with_bug_callsite_advice.jsonl
</span></span></code></div></div></pre>

---

## 5️⃣ Structured Export (Main Path)

* LLM review results are archived as **JSON / JSONL**
* Optional flattening to **CSV** for Power BI consumption
* Example outputs:
  <pre class="overflow-visible! px-0!" data-start="3300" data-end="3359"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>issues_with_advice.csv
  bugs_with_*_advice.csv
  </span></span></code></div></div></pre>

---

## 6️⃣ Publishing & Visualization (Main Path)

* **OneDrive Atomic Sync**
  * Temporary file + atomic replacement
  * Prevents partial or corrupted sync states
* **Power BI (Optional)**
  * Dataset refresh via REST API
  * Dashboards updated near real time

---

# 📊 Data Flow Diagram (Recommended Version)

<pre class="overflow-visible! px-0!" data-start="3676" data-end="4148"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-text"><span><span>SonarQube
  ↓  (list issues / bugs)
Issues Snapshot (raw)
  ↓
(Optional Preprocessing)
  ├─ Component Indexing / Source Snapshot
  └─ Dependency / Reference Extraction
  ↓
Context Enrichment
  ├─ Issue Snippets
  ├─ Bug Blocks (function-level context)
  └─ Callsites / Anchors (call-level context)
  ↓
LLM Review & Advice
  ├─ Bug Block Advisor
  └─ Callsite Advisor
  ↓
Structured Outputs (JSON / JSONL)
  ↓
CSV Export
  ↓
OneDrive Sync
  ↓
Power BI Dashboard
</span></span></code></div></div></pre>

---

# 🧠 Key Highlights (Aligned with Current Capabilities)

* **End-to-End Automation**

  From SonarQube ingestion → context modeling → LLM review → Power BI
* **Layered Context Design**

  Progressive enrichment: snippet → bug block → callsite
* **Controlled LLM Usage**

  Minimal-context-first strategy to manage token usage and failure rates
* **Production-Grade Publishing**

  Atomic sync ensures reliable downstream BI ingestion
* **Modular Architecture**

  Each stage can run independently or be orchestrated as a pipeline

---

# 🚀 Roadmap

* Introduce a unified **PipelineRunner** to orchestrate the full flow
* Add scheduled execution (GitHub Actions / Windows Task Scheduler)
* Strengthen CSV schema validation and sync monitoring
* Add failure classification (token overflow / API errors / parsing failures)

---

## ✅ One-Sentence Summary (Very Useful for Interviews)

> This flowchart describes  **what the system can reliably execute today** ,
>
> not a speculative future architecture.
