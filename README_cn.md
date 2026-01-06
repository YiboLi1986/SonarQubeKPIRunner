# SonarQube KPI Runner（AI 代码质量治理流水线）

**SonarQube KPI Runner** 是一个面向大型代码库（尤其是 C/C++ 多模块工程）的 **端到端自动化代码质量分析与可视化流程** ：

它从 **SonarQube** 拉取 Bugs/Issues 数据，结合源码上下文（snippets / bug blocks / callsites），再通过  **LLM（如 GPT-4.1 / Copilot）生成结构化审查与修复建议** ，最终导出为 **CSV** 并自动同步到  **OneDrive → Power BI** ，用于持续的质量治理、趋势分析与 KPI 可视化。

---

## 你能用它做什么？

* ✅ 把 SonarQube Issues 变成可分析的数据资产（JSON/JSONL/CSV）
* ✅ 自动为每条 issue 生成 **解释 + 修复建议（LLM Review）**
* ✅ 可选：生成更强上下文（bug block / callsite）来提升修复建议质量
* ✅ 自动同步到 OneDrive 并为 Power BI 提供稳定数据源
* ✅ 输出目录按项目/时间戳归档，便于回放历史趋势与对账

---

## Pipeline 总览（从 SonarQube 到 Power BI）

<pre class="overflow-visible! px-0!" data-start="806" data-end="1022"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>SonarQube</span><span>
  ↓  (list issues)
</span><span>Issues</span><span></span><span>Snapshot</span><span> (raw)
  ↓  (</span><span>optional</span><span>: snippets / bug blocks / callsites)
</span><span>Context</span><span></span><span>Enrichment</span><span>
  ↓  (</span><span>LLM</span><span> review)
</span><span>Advice</span><span></span><span>JSON</span><span> / </span><span>JSON</span><span>L
  ↓  (</span><span>export</span><span>)
</span><span>CSV</span><span>
  ↓  (sync)
</span><span>OneDrive</span><span> → </span><span>Power</span><span></span><span>BI</span><span>
</span></span></code></div></div></pre>

---

## 项目亮点（Highlights）

* **端到端自动化** ：从 SonarQube 抓取 → LLM 审查 → CSV → OneDrive → Power BI
* **上下文增强** ：支持 bug block / callsite（函数/调用位置级上下文）以提升建议质量
* **稳健同步** ：使用“临时文件 + 原子替换”避免 OneDrive 同步半文件
* **模块化架构** ：采集、上下文、LLM、导出、同步分层清晰，便于扩展与接入调度
* **可回放** ：输出按时间戳归档，便于趋势分析与治理复盘

---

## 目录结构（基于你当前截图）

> 下面结构与你项目实际目录对齐（`backend/src/...`）

<pre class="overflow-visible! px-0!" data-start="1350" data-end="3568"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-text"><span><span>SONARQUBEKPIRUNNER/
├── backend/
│   └── src/
│       ├── config/
│       │   └── github_models.local.json          # LLM 配置（示例/本地配置）
│       │
│       ├── data_io/
│       │   ├── file_reader.py                    # 通用文件读取
│       │   ├── file_writer.py                    # 通用文件写入
│       │   └── jsonl_to_csv_exporter.py          # JSONL → CSV 导出
│       │
│       ├── dependency/
│       │   ├── bug_block_extractor.py            # 提取 bug block（函数/上下文块）
│       │   ├── bug_reference_scanner.py          # 扫描引用/关联线索
│       │   └── cpp_dependency_extractor.py       # C++ 依赖/调用关系抽取（可选）
│       │
│       ├── doc/
│       │   └── issue_intelligence_keypoints.md   # 思路/要点记录
│       │
│       ├── evaluations/
│       │   └── bugs/
│       │       ├── sq_bug_block_advisor.py       # ✅ 入口：Bug Block 级 LLM 建议
│       │       └── sq_bug_callsite_advisor.py    # ✅ 入口：Callsite 级 LLM 建议
│       │
│       ├── sonar/
│       │   └── sq_issue_advisor.py               # Issue 级别 advisor（可选入口/旧入口）
│       │
│       ├── llm/
│       │   ├── config_loader.py                  # 读取模型配置
│       │   ├── copilot_client.py                 # Copilot / OpenAI 客户端封装
│       │   └── llm_handler.py                    # LLM 调用封装
│       │
│       ├── powerbi/
│       │   ├── one_drive_publisher.py            # OneDrive 同步发布
│       │   └── power_bi_refresher.py             # Power BI 刷新（可选）
│       │
│       ├── prompts/
│       │   ├── system.bug_block.review.txt
│       │   ├── system.bug_callsite.review.txt
│       │   ├── system.sonar.review.txt
│       │   ├── user.bug_block.review.txt
│       │   ├── user.bug_callsite.review.txt
│       │   └── user.sonar.review.txt
│       │
│       ├── outputs/                              # 所有运行产物（归档/回放）
│       │   ├── HysysEngine.Engine.issues/
│       │   ├── HysysEngine.Engine.bugs/
│       │   ├── HysysEngine.Engine.dependency/
│       │   └── evaluations/
│       │       └── <PROJECT_KEY>/
│       │           ├── bug_blocks/<timestamp>/
│       │           └── bug_callsites/<timestamp>/
│       │
│       └── main.py                               # 总入口（若你后续做 PipelineRunner 可接这里）
│
├── Flowchart_cn.md
├── Flowchart_en.md
├── README.md
└── requirements.txt
</span></span></code></div></div></pre>

---

## 输出文件说明（你截图里已经有）

典型输出路径示例（按项目与时间戳归档）：

* Issue 级原始/增强数据：
  * `backend/src/outputs/HysysEngine.Engine.issues/issues_raw.jsonl`
  * `backend/src/outputs/HysysEngine.Engine.issues/issues_with_snippets.jsonl`
* Bugs（带 anchors/calls 等增强信息）：
  * `backend/src/outputs/HysysEngine.Engine.bugs/bugs_with_anchors_and_calls.json`
* LLM Review 输出（带建议）：
  * Bug Block 级：
    * `backend/src/outputs/evaluations/<PROJECT_KEY>/bug_blocks/<timestamp>/bugs_with_bug_block_advice.jsonl`
  * Callsite 级：
    * `backend/src/outputs/evaluations/<PROJECT_KEY>/bug_callsites/<timestamp>/bugs_with_bug_callsite_advice.jsonl`
* 面向 Power BI 的 CSV（示例）：
  * `issues_with_advice.csv` / `bugs_with_*_advice.csv`（具体由 exporter 决定）

---

## 运行方式（当前主入口脚本）

> 你现在“最稳定/最直接”的运行方式，就是用 `sq_bug_block_advisor.py` 和 `sq_bug_callsite_advisor.py` 作为入口。
>
> 这两个脚本会：
>
> * 读取输入 JSON/JSONL（例如 bugs_with_anchors_and_calls.json）
> * 读取 prompts（system/user）
> * 调用 LLM 生成建议
> * 输出到 `outputs/evaluations/.../<timestamp>/...`

### 1）环境准备

<pre class="overflow-visible! px-0!" data-start="4566" data-end="4609"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-bash"><span><span>pip install -r requirements.txt
</span></span></code></div></div></pre>

确保你已准备好：

* SonarQube 访问所需的 token / base url（若脚本使用）
* LLM 配置（见 `backend/src/config/github_models.local.json`）
* OneDrive 同步目录（若启用 powerbi 发布）

---

### 2）运行：Bug Block 级建议生成（推荐先跑这个）

<pre class="overflow-visible! px-0!" data-start="4792" data-end="4863"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-bash"><span><span>python backend/src/evaluations/bugs/sq_bug_block_advisor.py
</span></span></code></div></div></pre>

适用场景：

* 你希望 LLM 聚焦于**“最小可用上下文块”**（函数/类附近 N 行）
* 对 token 更友好、速度更快、失败率更低

输出位置（示例）：

* `backend/src/outputs/evaluations/<PROJECT_KEY>/bug_blocks/<timestamp>/bugs_with_bug_block_advice.jsonl`

---

### 3）运行：Callsite 级建议生成（更强上下文、更适合复杂问题）

<pre class="overflow-visible! px-0!" data-start="5099" data-end="5173"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-bash"><span><span>python backend/src/evaluations/bugs/sq_bug_callsite_advisor.py
</span></span></code></div></div></pre>

适用场景：

* 你希望 LLM 同时利用**调用点/相关引用**信息，增强修复建议准确性
* 适合跨模块、依赖复杂、需要更多上下文的 bug

输出位置（示例）：

* `backend/src/outputs/evaluations/<PROJECT_KEY>/bug_callsites/<timestamp>/bugs_with_bug_callsite_advice.jsonl`

---

## LLM / Prompt 配置说明

### Prompt 文件（版本可追溯）

你的 prompt 都在：

* `backend/src/prompts/system.*.txt`
* `backend/src/prompts/user.*.txt`

这保证了：

* prompt 版本可以随 repo 管理
* 输出质量变化可定位到 prompt 变更

### LLM 配置

本地模型/企业模型配置放在：

* `backend/src/config/github_models.local.json`

（建议把真实 token 放到本地配置或环境变量里，并保证 `.gitignore` 已忽略敏感配置）

---

## OneDrive → Power BI（可选功能）

当你把 JSONL 扁平化导出为 CSV 后：

* `one_drive_publisher.py` 负责将 CSV 原子同步到本机 OneDrive 同步目录
* 可选 `power_bi_refresher.py` 通过 REST API 触发数据集刷新

典型目的：

* 让 Power BI 仪表盘尽可能接近实时更新
* 将代码质量治理变成可持续运营的 KPI 系统

---

## Roadmap

> 本 Roadmap 描述的是在**当前稳定的分析与建议能力**之上，
>
> 逐步演进为一个  **可协作、可验证、可治理的 AI 辅助代码质量闭环系统** 。

---

### 一、基础工程能力增强（Pipeline & Infra）

* [ ] 增加统一入口 **`PipelineRunner`**

  （串起：SonarQube 抓取 → 上下文增强 → LLM 审查 → CSV 导出 → 发布）
* [ ] 支持定时调度

  （GitHub Actions / Windows Task Scheduler）
* [ ] 增强输出 **CSV / JSON schema 校验**

  （保证 Power BI ingestion 的长期稳定性）
* [ ] 增加失败分类统计

  （token 超限 / LLM 调用失败 / 解析失败等）

---

### 二、人机协作与修复闭环（Human-in-the-loop）

* [ ] 基于 LLM 审查结果生成 **临时 Patch / Diff 文件**
  * 包含建议修改的代码变更
  * 同步附带原始代码片段与上下文说明
  * Patch 仅作为候选修复草稿，不直接修改主干代码
* [ ] 通过 **PR 或临时分支** 将 Patch 回传至开发者仓库
  * 开发者在 IDE 中打开并审查 Patch
  * 进行必要的微调（风格 / 边界条件 / 业务语义）
* [ ] 引入 **Developer Feedback 机制**
  * accept / partial accept / reject
  * 简要原因标签（上下文不足 / 逻辑不适配 / 风格问题等）

---

### 三、多轮验证与迭代修复（Validation Loop）

* [ ] PR 合并或修订后自动触发
  * CI 构建
  * SonarQube re-analysis
* [ ] 若问题未完全解决或引入新问题
  * 记录失败信号
  * 进入下一轮 LLM 修复建议生成（带失败上下文）

---

### 四、长期治理与趋势分析（Governance & Insights）

* [ ] 对多轮仍未成功修复的 issues 标记为 **hard cases**
  * 记录失败类型、上下文特征与模块分布
* [ ] 在时间维度上进行聚合分析
  * 哪些规则 / 模块修复成功率低
  * 哪些问题更适合人工优先处理
* [ ] 将关键指标沉淀为治理 KPI
  * 修复成功率
  * Developer 接受率
  * 平均修复周期（MTTR）
  * 多轮迭代次数

---

## 许可 / 备注

> 本项目用于工程内部质量治理与自动化分析。若你将其开源，建议移除或替换内部项目名、路径、token、SharePoint 链接等敏感信息。
