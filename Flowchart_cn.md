# 📘 项目概述

**SonarQube KPI Runner** 是一个面向大型代码库（尤其是 C/C++ 多模块工程）的

 **端到端自动化代码质量分析与可视化治理流水线** 。

它从 **SonarQube** 拉取 Bugs / Issues 数据，在本地进行 **上下文增强建模** （snippets / bug blocks / callsites），再通过 **大语言模型（LLM，如 GPT-4.1 / Copilot）**生成结构化的审查解释与修复建议，最终导出为 **CSV** 并自动同步到  **OneDrive → Power BI** ，用于持续的代码质量治理、趋势分析与 KPI 可视化。

---

# ⚙️ 流程总览（对齐当前实现）

> 说明：
>
> * **主路径** ：你现在 `sq_bug_block_advisor.py` / `sq_bug_callsite_advisor.py` 实际依赖的流程
> * **可选步骤** ：用于增强上下文与分析能力，但不是每次运行的硬依赖

---

## 1️⃣ SonarQube Issues / Bugs 抓取（主路径）

* 从 SonarQube 拉取 issues / bugs 快照
* 支持按时间窗口、项目分片
* 输出示例：
  <pre class="overflow-visible! px-0!" data-start="856" data-end="930"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>backend/src/outputs/HysysEngine.Engine.issues/issues_raw.jsonl
  </span></span></code></div></div></pre>

---

## 2️⃣ （可选）组件索引与依赖预处理（增强路径）

> 该阶段用于 **构建更完整的代码结构视图** ，为后续上下文增强提供基础数据。

* 组件路径索引（Component / File Snapshot）
* 源码本地快照（可选）
* C/C++ 依赖与引用扫描
* 典型输出：
  <pre class="overflow-visible! px-0!" data-start="1082" data-end="1144"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>backend</span><span>/src/</span><span>outputs</span><span>/HysysEngine.Engine.dependency/</span><span>
  </span></span></code></div></div></pre>

> ⚠️
>
> 当前 LLM Advisor 可在**已有 bugs / anchors 数据**基础上直接运行，
>
> 该步骤不是强制前置。

---

## 3️⃣ 上下文增强（Context Enrichment，主路径）

在 issues / bugs 的基础上，逐步增强上下文信息：

* **Issue Snippets**
  * 行级上下文（issue 所在行 ± N 行）
* **Bug Blocks**
  * 函数 / 类级最小可用上下文块
  * 用于控制 token、提升稳定性
* **Callsites / Anchors**
  * 调用点与关联引用
  * 适合跨模块、依赖复杂的问题

输出示例：

<pre class="overflow-visible! px-0!" data-start="1479" data-end="1519"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>bugs_with_anchors_and_calls.json
</span></span></code></div></div></pre>

---

## 4️⃣ LLM 审查与建议生成（核心阶段）

基于不同上下文粒度，选择对应的 Advisor：

* **Bug Block Advisor**
  * 最小可用上下文
  * token 友好、速度快、失败率低
  * 入口脚本：
    <pre class="overflow-visible! px-0!" data-start="1650" data-end="1689"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>sq_bug_block_advisor.py
    </span></span></code></div></div></pre>
* **Callsite Advisor**
  * 更强上下文（调用点 / 引用）
  * 适合复杂、跨模块 bug
  * 入口脚本：
    <pre class="overflow-visible! px-0!" data-start="1765" data-end="1807"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>sq_bug_callsite_advisor.py
    </span></span></code></div></div></pre>

输出示例：

<pre class="overflow-visible! px-0!" data-start="1815" data-end="1997"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>backend</span><span>/src/</span><span>outputs</span><span>/evaluations/</span><span><</span><span>PROJECT_KEY</span><span>>/</span><span>
 </span><span>├──</span><span> bug_blocks</span><span>/<timestamp>/</span><span>bugs_with_bug_block_advice.jsonl
 </span><span>└──</span><span> bug_callsites</span><span>/<timestamp>/</span><span>bugs_with_bug_callsite_advice.jsonl
</span></span></code></div></div></pre>

---

## 5️⃣ 结构化导出（主路径）

* 将 LLM 审查结果以 **JSON / JSONL** 形式归档
* 可选扁平化导出为  **CSV** （Power BI 可直接消费）
* 输出示例：
  <pre class="overflow-visible! px-0!" data-start="2104" data-end="2163"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>issues_with_advice.csv
  bugs_with_*_advice.csv
  </span></span></code></div></div></pre>

---

## 6️⃣ 发布与可视化（主路径）

* **OneDrive 原子同步**
  * 临时文件 + 原子替换
  * 防止半文件同步
* **Power BI（可选）**
  * REST API 触发数据集刷新
  * 仪表盘接近实时更新

---

# 📊 数据流示意图（推荐替换版）

<pre class="overflow-visible! px-0!" data-start="2319" data-end="2791"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-text"><span><span>SonarQube
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

# 🧠 项目亮点（对齐当前能力）

* **端到端自动化**

  从 SonarQube → 上下文建模 → LLM 审查 → Power BI
* **上下文分层设计**

  snippet / bug block / callsite 按复杂度逐级增强
* **LLM 可控使用**

  通过最小上下文原则控制 token 与失败率
* **稳健的数据发布机制**

  原子同步，适合生产级报表管道
* **模块化架构**

  各阶段可独立运行，也可统一编排

---

# 🚀 下一步计划（Roadmap）

* 引入统一 **PipelineRunner** 串联全流程
* 定时调度（GitHub Actions / Windows Task Scheduler）
* 增强 CSV schema 校验与同步监控
* 引入失败分类统计（token 超限 / API 错误 / 解析失败）
