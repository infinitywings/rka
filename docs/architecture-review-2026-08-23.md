# RKA 架构评审 —— API / MCP / Skill 三层

**日期**：2026-08-23 · **方法**：只读实测（191 条 REST 路由、150 个 MCP operation、
5,178 条生产实体、rka/skills 全量），结论均可复现。

---

## 一、总体判断

**分层是清楚的，问题不在结构而在"面积"。**

`MCP → REST → Service → DB` 的分层干净：MCP 是无状态代理，业务逻辑集中在
service 层，REST 只做适配。这个骨架没问题。

真正的风险集中在一点：**接口面积远大于实际使用面积**。150 个 MCP operation 里
**61 个（41%）服务于生产库中零行数据的子系统**；191 条 REST 路由里手稿与规划
两块占了 38 条，而这两块的实体表全是空的。agent 的选择空间里有四成是它这辈子
用不上的东西。

---

## 二、MCP 层 —— 你最担心的那点

### 2.1 dispatch 设计本身是对的，不要推翻

v2.7.0 把 150 个 operation 收进 3 个 dispatch 工具，连接时只广播 **5 个**工具。
这恰恰是"接口过多让 agent confuse"的正解：

- agent 的**首选空间只有 5 个**，不是 150 个
- 150 个分支以 `oneOf` + `discriminator` 落在 inputSchema 上，非法枚举值
  （如 `confidence="confirmed"`）在**离开客户端之前**就被拒绝
- `rka_describe("")` 提供 <250 token 的索引，按需展开

这个设计比"150 个独立 MCP 工具"好一个数量级。**问题不在 dispatch，在 dispatch
背后的 operation 清单该不该有 150 项。**

### 2.2 41% 的 operation 服务于零使用子系统

| 子系统 | operation 数 | 生产行数 |
|---|---|---|
| manuscript 手稿 | 17 | 3 个 manuscript，**0 unit / 0 claim / 0 binding** |
| planning 规划分支 | 16 | **0** |
| experiments 实验 | 9 | **0** |
| semantic patch 提案 | 7 | **0** |
| hooks 自动化 | 6 | **0** |
| interpretation 解释候选 | 4 | **0** |
| claim_scope 断言作用域 | 2 | **0** |
| **合计** | **61 / 150 = 41%** | |

这不是"功能没用"的价值判断——这些子系统可能正处在设计前置阶段。但**对 agent
而言，它们是 41% 的噪声**：`rka_describe("")` 的索引里它们与核心操作平权列出，
agent 需要读完才能确认"这些跟我无关"。

**建议**：给 operation 加 `maturity` 标记（`stable` / `preview`），
`rka_describe("")` 默认只列 stable，`rka_describe("", include_preview=True)`
才展开。零代码风险、零功能损失，agent 的默认选择空间从 150 降到 89。

### 2.3 六对易混淆命名

| A | B | 问题 |
|---|---|---|
| `scan_workspace`（写） | `workspace_scan`（读） | **同词反序、分属不同 dispatch 工具**，最危险 |
| `create_manuscript` | `register_manuscript` | 后者是 legacy Writer 兼容层，仍在一等公民位置 |
| `summarize` | `generate_summary` | 后者 v2.4.0 已摘除 LLM 路径，是 stub |
| `update_mission` | `update_mission_status` | 一个资源两个写操作 |
| `bootstrap_workspace` | `bootstrap_review` | 一写一读，前缀相同 |
| `search` | `collect_report_context` | 职责重叠，且**没有任何地方说明何时该用后者** |

第一对尤其值得修：agent 要在 `rka_query` 里找 `workspace_scan`、在 `rka_execute`
里找 `scan_workspace`，两者只差词序。建议把读操作改名为
`workspace_scan_result` 或直接并入 `bootstrap_review`。

最后一对是**实际造成过损失的**：eval-v3 的 retention `rka` arm 用单条整段查询走
`search`，得分 0.17；而 `collect_report_context` 的 docstring 自己写着
"整段式 seeding 实测 0.32 recall，角度分解 0.80"。**接口存在、文档存在、但
调用方不知道该用哪个。**

---

## 三、REST 层

191 条路由 / 228 个方法端点。GET 112 · POST 92 · PUT 20 · DELETE 3 · PATCH 1。

### 3.1 好的部分

- **只有 3 个 DELETE、1 个 PATCH** —— 对一个溯源系统这是**正确**的取舍：
  记录以追加与 supersede 表达变更，而非原地删改。这一点与 `superseded_by` /
  `entity_links` 的设计自洽。
- 28 条动词式端点（`/resolve`、`/transition`、`/promote`）不是 REST 洁癖问题：
  这些是**生命周期状态迁移**，用动词比强行造资源更诚实。

### 3.2 三处命名不一致（会直接绊到调用方）

1. **资源段大小写混用**：42 个 kebab-case 段中混着 4 个 snake_case ——
   `decision_options`、`dominated_by`、`link_zotero`、`pi_selection`。
2. **同一概念两套 id 参数名并存**：
   `{mis_id}`(2) 与 `{mission_id}`(1)、`{chk_id}`(2) 与 `{checkpoint_id}`(1)
   同时存在于当前 API。`{dec_id}`/`{lit_id}` 用缩写，而
   `{manuscript_id}`/`{experiment_id}`/`{cluster_id}` 用全称。
3. **缩写与全称无规则**：没有一条能解释为什么 decision 缩成 `dec` 而
   manuscript 不缩。

这三处都是纯改名，但对生成式调用方（agent 按 OpenAPI 猜参数名）影响不小。

### 3.3 一个结构性建议

手稿 22 条 + 规划 16 条 = **38 条路由（20%）挂在零数据子系统上**。
如果这两块仍在设计中，建议挪到 `/api/preview/` 前缀下，OpenAPI 里用 tag 分组，
让 `/api/` 主面反映"已在用的系统"。

---

## 四、Skill 层

### 4.1 好的部分：零悬空引用

skill 中出现的 **48 个 operation 引用全部真实存在**，无一指向不存在的接口。
考虑到 v2.6→v2.7 换过一整套工具面，这说明迁移做得认真。

而且 skill **没有推销零使用子系统**：61 个 dead operation 里只有 7 个被提及。
方向是对的。

### 4.2 覆盖缺口：46%

89 个"有数据"的 operation 里，skill 只覆盖 41 个。**48 个服务于真实数据的操作
没有任何指引**，其中不乏核心项：

`clusters`、`claims`、`create_cluster`、`assign_claims_to_cluster`、
`advance_rq`、`calibration_metrics`、`belief_as_of`、`changes_since`、
`staleness_impact`、`contradictions`、`brain_notifications`

`belief_as_of`（重建某历史时点的认知状态）和 `staleness_impact`
（陈旧知识的下游影响面）**正是"不 chase own tail"最直接的工具**，却完全没写进
任何 skill。这是最可惜的一处。

### 4.3 结构不一致：四个 skill 没有一个共同章节

| skill | H2 数 |
|---|---|
| brain | 18 |
| writer | 18 |
| executor | 13 |
| **pi** | **4** |

四者的 H2 标题集合**交集为空**。原因不是内容缺失，而是同一概念各起各的名：

| 概念 | brain | executor | pi | writer |
|---|---|---|---|---|
| 工具面 | `Tool Surface (v2.7.0+) — No-Compromise…` | 同左 | 同左 | `Tool Surface` |
| 会话开始 | `Session Start — Do This Every Time` | `Session Start` | `Session Start` | `Session Start` |
| 检索策略 | `Retrieval Strategy — Drive RKA…` | `Retrieving Context — Drive RKA…` | **无** | **无** |
| 禁忌 | `Anti-Patterns — Common Mistakes…` | `Guardrails` | `Guardrails` | `Anti-Patterns` |
| 溯源 | `Provenance` | `Evidence-recording boundary` | **无** | `Provenance` |

**"禁忌"用了两个词（Anti-Patterns / Guardrails）**，语义相同却让人以为是两回事。

### 4.4 PI skill 过薄，且缺的正是它最该有的

pi/SKILL.md 只有 4 个 H2、无检索策略、无 status 陷阱说明。但 PI 是**唯一会去
质疑"这条结论是不是基于旧决策"的角色**——它比谁都需要知道
`/api/search` 不返回 status、需要知道 `belief_as_of` 和 `staleness_impact`
的存在。

---

## 五、建议（按性价比排序）

| # | 动作 | 状态 | 收益 |
|---|---|---|---|
| 1 | operation 加 `maturity` 标记 | ✅ **已完成** | 默认索引 150 → **85**，隐藏 65 |
| 2 | skill 补 currency 操作用法 | ✅ **已完成** | 6 个反 tail-chasing 操作全部覆盖 |
| 3 | 四个 skill 统一章节骨架 | ✅ **已完成** | 共有章节 0 → 2，并加测试锁定 |
| 4 | 补厚 PI skill | ✅ **已完成** | 新增 Retrieval Strategy 节 |
| 7 | `search` vs `collect_report_context` 选择规则 | ✅ **已完成** | Brain 新增调用选择表 |
| 5 | 消歧 `scan_workspace` / `workspace_scan` | 待办 | 改名会破坏现有调用方，需过渡期 |
| 6 | 统一 REST id 参数命名 | 待办 | 需保留旧名重定向 |
| 8 | 手稿/规划路由移入 `/api/preview/` | 待办 | maturity 标记已先解决 MCP 侧 |

### 已完成部分的实测

| 指标 | 改动前 | 改动后 |
|---|---|---|
| `rka_describe('')` 列出的 operation | 150 | **85**（隐藏 65，可用 `include_preview=True` 展开）|
| skill 引用的真实 operation | 48 | **67** |
| 四个 skill 共有 H2 章节 | **0** | **2**（`Tool Surface` / `Session Start`）|
| `belief_as_of` 等 6 个 currency 操作被提及 | 0 / 6 | **6 / 6** |

`Guardrails`（角色权限边界）与 `Anti-Patterns`（用法错误）**刻意未合并**——
两者语义不同，合并会丢失区分。

第 5、6、8 项都涉及破坏性改名，留待你决定过渡策略。

---

## 六、一句话结论

**架构没有走错方向。** dispatch 收敛、append-only 溯源、typed-arg 强约束这三个
选择都是对的，而且是同类系统里少见的清醒。当前的问题是**成熟度分层缺失**：
已验证的核心（journal / decision / claim / cluster / mission）与仍在设计中的
子系统（manuscript / planning / experiment / semantic-patch）在接口面上平权
并列，agent 无法区分。加一层 maturity 标记，比删任何功能都划算。
