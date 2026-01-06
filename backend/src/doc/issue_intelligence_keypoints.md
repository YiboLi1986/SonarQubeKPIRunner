### **A. 基于影响的优先级分析**

这一阶段的核心是判断哪些问题最值得优先修复。

通过综合 SonarQube 的严重等级、代码依赖中心性、修改频率（churn）以及文件热点等指标，为每个 issue 计算量化的  **优先级得分** 。

这样可以区分“紧急但影响小”与“影响大但不显眼”的问题，使工程资源集中在最能降低整体风险的部分。

### **B. 依赖感知的改动风险控制**

并非所有高优先级问题都可以立即修改。

在应用 Copilot 或其他 LLM 提供的修复建议前，系统会评估其  **改动风险** ：包括依赖深度、下游影响、API 暴露程度、测试覆盖率等。

对于高风险修改，系统设有多重 **安全护栏** —— 如干运行（Dry-run）审查、依赖清单、CI 验证等，以防止引入新的错误或破坏其他模块。

### **C. 聚类归类与持续学习**

在优先级和风险都评估后，系统对 issue 进行  **语义聚类** ，按规则类型、目录结构、文本相似度分组。

每个聚类将形成一个可复用的  **修复模式模板** ，作为未来 LLM 提示（few-shot）的示例。

随着时间推移，系统能够从历史经验中不断学习，总结常见的“问题–解决”模式，实现更智能的自动分类、解释与修复。

### **A. Impact-Based Prioritization**

Focus on identifying which issues are  *worth fixing first* .

By combining SonarQube severity, dependency centrality, code churn, and file-level hotspots, each issue receives a quantified  **priority score** .

This helps distinguish between *urgent but small* issues and *moderate but high-impact* ones, ensuring engineering effort aligns with overall product risk.

### **B. Dependency-Aware Change Risk Control**

Not all high-priority issues are safe to fix immediately.

Before applying LLM or Copilot-generated code suggestions, the system assesses **change risk** based on dependency depth, downstream impact, API exposure, and local test coverage.

High-risk changes are placed under **guardrails** — dry-run reviews, dependency checklists, and CI validation — to prevent new regressions or cross-module breakages.

### **C. Issue Clustering and Continuous Learning**

After issues are prioritized and controlled, they are grouped into **semantic clusters** based on rule type, directory, and textual similarity.

Each cluster becomes a reusable  **pattern template** , feeding future LLM prompts as few-shot examples.

Over time, the system “learns” recurring problem–solution patterns, enabling smarter automated triage, explanation, and safer patch generation.
