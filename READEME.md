# 📘 README.md

## SonarQube KPI Runner & Power BI Dashboard

This project provides an automated workflow for collecting **code quality metrics** from SonarQube and visualizing them in  **Power BI dashboards** . It is designed to integrate seamlessly into existing development pipelines across multiple teams.

---

## 🔄 Development Pipeline Overview

1. **Code Commit (Developer → Repo)**
   * A developer pushes changes to the repository (main branch or feature branch).
2. **Unit Tests Execution**
   * The CI pipeline runs unit tests to validate functionality.
   * If unit tests fail, the pipeline stops and the commit does not proceed.
3. **SonarQube Scanner**
   * If tests pass, the pipeline triggers a **SonarQube scan** on the new code.
   * The scan checks for:
     * Bugs, vulnerabilities, code smells
     * Coverage, duplications
     * Maintainability, reliability, and security ratings
4. **Quality Gate Evaluation**
   * SonarQube compares metrics against the **Quality Gate KPIs** (e.g. coverage ≥ 80%, duplication ≤ 3%, no critical blockers).
   * **Pass** → pipeline continues.
   * **Fail** → pipeline may require rollback, fix, or re-commit.
5. **KPI Data Extraction**
   * The pipeline calls SonarQube’s REST APIs (`/api/qualitygates/project_status`, `/api/measures/component`, etc.).
   * KPI data (JSON) is normalized and stored for further use.
6. **Power BI Visualization**
   * Processed KPIs are published to  **Power BI** .
   * Dashboards provide:
     * Project-level Quality Gate status
     * Historical trends (coverage, bugs, duplication)
     * Team comparisons and KPI compliance rates

---

## ⚙️ Key Features

* **Automated** : Fully integrated into CI/CD pipelines.
* **Consistent** : All projects use the same Quality Gate criteria.
* **Visualized** : Clear, interactive dashboards in Power BI.
* **Actionable** : Immediate feedback if KPIs are not met.
* **Extensible** : Additional metrics and custom rules can be added.

---

## 📊 Example Dashboards

* **Quality Gate Status** : pass/fail overview per project.
* **Coverage Trends** : line chart of test coverage over time.
* **Issue Breakdown** : bugs vs vulnerabilities vs code smells.
* **Duplication Heatmap** : highlight areas with high code duplication.

---

## 🚀 Getting Started

### Prerequisites

* Python 3.10+
* Access to a SonarQube server
* Power BI Desktop or Power BI Service
* Personal Access Token (SonarQube API)

### Setup

<pre class="overflow-visible!" data-start="2755" data-end="3055"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-bash"><span><span># clone repository</span><span>
git </span><span>clone</span><span> https://github.com/<your-org>/SonarQubeKPIRunner.git
</span><span>cd</span><span> SonarQubeKPIRunner

</span><span># create virtual environment</span><span>
python -m venv .venv
</span><span>source</span><span> .venv/bin/activate   </span><span># Linux/Mac</span><span>
.venv\Scripts\activate      </span><span># Windows</span><span>

</span><span># install dependencies</span><span>
pip install -r requirements.txt
</span></span></code></div></div></pre>

### Run

<pre class="overflow-visible!" data-start="3065" data-end="3113"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-bash"><span><span>python backend/src/sonarqube/main.py
</span></span></code></div></div></pre>

---

## 🏗️ Future Enhancements

* Integration with GitHub Actions, GitLab CI, Azure DevOps.
* Extended KPI coverage (performance, security scans).
* Automated alerts (Slack/Teams) when Quality Gate fails.
* Historical trend storage (SQL/NoSQL database).

---

## 📜 License

MIT License (update if company policy requires otherwise).
