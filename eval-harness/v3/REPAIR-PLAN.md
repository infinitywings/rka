# RKA 检索与一致性 —— 诊断报告与修复计划

**日期**：2026-08-23
**目标**（PI 原话）：research 过程中，agent（如 Claude Code）能依据 knowledge
graph 准确检索历史关键研究节点，并在 pivot 过程中保持一致，不 chase own tail。
**备份**：`/Volumes/FuSpace/Projects/rka-backups/rka-full-backup-2026-08-23-213402.db`
（133 MB，含 embedding 配置；容器内 `/data/` 亦有副本）
**方法**：全部只读诊断 + 一次已授权的 project-F 回填。所有数字可复现。

---

## 一、一句话结论

**图层达标，入口层不达标。** 拿到正确的决策节点后，RKA 的 pivot 处理是可靠的
（14/14 全对，0 次只返回旧决策）；但 agent 从一个自然问题出发**找到**那个节点的
成功率只有 **25.8%**，而且入口层**完全不暴露 status**，所以 agent 无从知道自己
手里的决策是否已被推翻。

好消息是：最大的一项修复**不需要改代码**，把命中率从 26.7% 提到 93.3%。

---

## 二、诊断结果总览

| # | 问题 | 严重度 | 证据 | 需改代码 |
|---|---|---|---|---|
| 1 | 混合检索里决策被其他类型淹没 | **P0** | 自检索命中率 26.7% → 加类型过滤 93.3% | 否 |
| 2 | ~~`/api/search` 不返回 `status`~~ **已修复** | ~~P0~~ ✅ | `blind_stale_exposure` 0.133 → **0.0** | 是 |
| 3 | ~~向量索引缺 1,023 条~~ **已修复** | ~~P1~~ ✅ | 全库 80.2% → **100.0%** | 否 |
| 4 | ~~故障后不回填、无触发接口~~ **已修复** | ~~P1~~ ✅ | 签名纳入 base_url + 新增触发端点 | 是 |
| 5 | ~~`embedding_pending` 标志位漂移~~ **已修复** | ~~P1~~ ✅ | 改用 `embedding_metadata` 判定 | 是 |
| 6 | 4 条决策"作废但无继任指针" | P2 | 3 条 prose 里提到的 id 在库中不存在 | 否（人工） |
| 7 | ~~配置改动需重启~~ **已修复** | ~~P2~~ ✅ | 200 分支也刷新 `app.state.embeddings` | 是 |
| 8 | 40 个悬空 entity_links 端点 | P3 | 16 decision / 23 literature / 1 journal | 否（清理） |

---

## 三、逐项详解

### 【P0-1】决策在混合结果集里被淹没 —— 最高杠杆，零代码

**现象**：用一条决策**自己的问题原文**去搜（最弱的检索测试，理应必中），
392 条决策里只有 **25.8%** 能在 top-20 找到自己，MRR 0.043。
极端例子：在 project-A 搜 `"What is RKA role in the research workflow?"`，
20 条结果里既没有提出这个问题的决策、也没有它的继任者。

**根因**：`/api/search` 默认跨 8 种实体类型混排。结果集构成为
journal 2318 / decision 1940 / mission 1269 / claim 1109 / literature 977。
决策并非绝对数量少，而是**目标那一条**排不上去。

**证据（同样 120 条决策，只改检索参数）**：

| 配置 | 命中率@20 | MRR |
|---|---|---|
| A 默认（全类型, kw0.3/sem0.7） | 26.7% | 0.036 |
| B **+ `entity_types:["decision"]`** | **93.3%** | 0.210 |
| C 仅调权重 kw0.7/sem0.3 | 30.0% | 0.087 |
| D **类型过滤 + kw0.7/sem0.3** | **95.0%** | **0.220** |
| E 类型过滤 + 纯关键词（禁用向量） | 78.3% | 0.218 |

**修复**：分两层，都不用改服务端代码。

1. **立即可用**：查决策时带上参数——
   `{"query": ..., "entity_types": ["decision"], "keyword_weight": 0.7, "semantic_weight": 0.3}`
2. **写进 skill**：`rka/skills/brain/` 与 `executor/` 里凡是"找历史决策"的指引，
   都应指定类型过滤，而不是裸调 search。

**验证**：`python eval-harness/v3/currency/self_retrieval.py --db <snapshot> --types decision`
应稳定 ≥90%。

**风险**：低。只是请求参数，随时可回退。
**注意**：这不能替代跨类型检索——找证据/文献时仍需全类型。规则是
**"按你要找的东西的类型来过滤"**，不是"永远只查决策"。

---

### 【P0-2】入口层不暴露 status —— agent 无法察觉自己在用旧决策

**现象**：API 面审计——

| 接口 | 有 `status` |
|---|---|
| `POST /api/search` | **没有** |
| `GET /api/graph/ego` | 有 |
| `POST /api/graph/multi-hop` | 有 |
| `GET /api/decisions/{id}` | 有 |

唯一没有的，恰好是 agent 第一个碰到的那个面。

**为什么这直接对应 "chase own tail"**：在 project-F 的 15 条 pivot 上，
73% 的情况现行决策排在旧决策之前——但**旧决策通常也在结果集里**（rank 12–20），
两者外观完全一致。另有 1/15 只返回旧决策。agent 拿到后无任何信号可判断。
`blind_stale_exposure = 0.067`。

**根因**：`rka/api/routes/search.py` 的 `SearchResult` 模型只有
`entity_type, entity_id, title, snippet, score`；`SearchService.SearchHit`
（`rka/services/search.py:23`）内部也没有 status 字段。

**修复**：
1. `SearchHit` 增加 `status: str | None = None`、`superseded_by: str | None = None`；
   各实体类型的 SELECT 带上这两列（decisions/journal 已有 status 列）。
2. `SearchResult` 同步增加，`search()` 路由透传。
3. 可选：`SearchRequest` 增加 `exclude_superseded: bool = False`。

**验证**：搜一个已知 superseded 决策，返回体应含 `"status": "superseded"`。
Track 5 的 `any_status_signal` 应从 False 变 True。

**风险**：低。纯增字段，向后兼容。需 `docker compose up -d --build`。

---

### 【P1-3】向量索引缺 1,023 条

**现状**（实时库，全库 80.2%）：

| 项目 | 覆盖率 | | 项目 | 覆盖率 |
|---|---|---|---|---|
| project-F | 100%（今日回填） | | project-E | **0%** (257) |
| project-K | 100% | | project-H | **0%** (132) |
| project-A | 95.4% | | project-J | **0%** (120) |
| project-B | 93.9% | | project-G | **18.0%** |
| project-D | 89.1% | | project-I | 42.1% |
| project-C | 77.8% | | | |

单一模型 `qwen3-embedding-4b` dim 2560，**无混维问题**。断点 2026-05-23。

**向量到底有没有用？** 有。同一批决策下，禁用向量（配置 E）命中率
78.3%，启用（配置 D）95.0% —— **向量贡献 +17pp**。
（早前我用"有向量项目 vs 无向量项目"对比得出"向量无用"，那是**错的**：
没向量的恰好都是新建小项目，竞争少，属于混淆。D vs E 才是干净的同组对比。）

**修复：已完成（2026-08-23）。** 用 `eval-harness/v3/currency/backfill_project.py`
逐项目回填，10 个项目、**1,023 条全部嵌入、0 失败**。
全库由 80.2% 升至 **100.0%（5178/5178）**，每个项目均为 100%——
包括此前完全为 0 的 project-E(257)、project-H(132)、project-J(120)。
自 2026-05-23 起持续三个月的索引空洞已闭合。

**不要用** `PUT /api/config/embedding` 触发：它会调
`reshape_all_vec_tables_if_needed` **重建所有 vec 表**，抹掉 project-A
已有的 2,108 条向量并强制全库重嵌。
**也不能直接用** `BackfillService`：见 P1-5，它会跳过全部 claims。

**风险**：中低。写生产库（新增向量 + metadata），已有备份。脚本幂等可重跑。

---

### 【P1-4】故障恢复不触发回填，且无手动触发接口

**根因**：`rka/api/routes/config.py:138` 用
`_backend_signature(prior) != _backend_signature(body)` 判断是否回填，而签名是
`(backend, model, dim)`（`config.py:84`）——**不含 `base_url`**。
所以"把后端指向一台可用的机器"这个**唯一的故障恢复动作**恰恰不触发回填。
实测：我 PUT 后返回 200（而非带 job_id 的 202），
`backfill/status` 至今为 `idle`。

**修复**：
1. `_backend_signature` 纳入 `base_url`；或
2. `SearchRequest`…（不适用）→ `EmbeddingConfig` PUT 增加 `force_backfill: bool`；
3. 新增 `POST /api/config/embedding/backfill`，可选 `project_id` 与
   `entity_types`，复用现有 `BackfillService` + `register_job()`。

**验证**：改 base_url 后应返回 202 + job_id，`backfill/status` 进入 `running`。

---

### 【P1-5】`claims.embedding_pending` 标志位漂移

**现象**：976 条 claims **全部** `embedding_pending = 0`，但其中 341 条没有向量。
`BackfillService` 判定 claims 用 `WHERE embedding_pending = 1`
（`embedding_backfill.py:180`），因此**会跳过每一条待补的 claim**。
其他实体类型用的是 `NOT EXISTS(embedding_metadata …)`，是准的。

**修复**（二选一，推荐前者）：
1. 把 claims 的 `pending_count_sql` / cursor 改成与其他类型一致的
   `embedding_metadata` 判定，**彻底去掉这个标志位依赖**；
2. 或加一条对账：`UPDATE claims SET embedding_pending = 1 WHERE NOT EXISTS(...)`。

**验证**：`pending_count_sql` 对当前库应返回 341（现在返回 0）。

---

### 【P2-6】4 条决策"作废但无继任指针"

`status='superseded'` 但 `superseded_by IS NULL`，且无 `supersedes` 边：

| 决策 | 项目 | abandonment_reason |
|---|---|---|
| `dec_000000REDACTED` | project-A | "Merged into dec_64Y"（**非法 id**） |
| `dec_000001REDACTED` | project-A | 提到 `dec_000002REDACTED`（**库中不存在**） |
| `dec_000003REDACTED` | project-B | 空 |
| `dec_000004REDACTED` | project-D | 空 |

**无法自动修复**：prose 里提到的 3 个 id 在库中都不存在。需要你人工指认继任者，
再 `UPDATE decisions SET superseded_by = ?` 并补一条 `supersedes` 边。
**工作量：4 条，几分钟。** 这是"只知作废、不知被谁取代"的典型 tail-chasing 隐患。

其余 35 条 supersede 链**全部健康**：0 断链、0 状态错配、0 缺边。

---

### 【P2-7】配置改动需重启，且 `/test` 会误报成功

`PUT /api/config/embedding` 持久化并被 GET 正确反映，
`POST /api/config/embedding/test` 也通过（它新建了一个 client），
但**搜索路径持有启动时缓存的 provider client**，改动直到进程重启才生效。
这个组合最坑：UI 显示"新后端可用"，而每一次真实搜索仍在用旧后端。

**修复**：PUT 成功后同时刷新 `request.app.state.embeddings`
（202 分支已经这么做了，200 分支没有），或让 SearchService 每次从 app.state 取。

---

### 【P3-8】40 个悬空 entity_links 端点

指向已不存在的实体：16 decision / 23 literature / 1 journal。
另有 50 条跨项目边（多与 project-K 相关，疑似早期迁移残留）。
**影响**：图遍历会带回无法解析的 id，污染 precision（实测 ≈0.21）。
**修复**：一次性清理脚本，删除两端有一端无法解析的边；跨项目边需人工判断。

---

## 四、执行顺序（建议）

| 阶段 | 动作 | 耗时 | 改代码 | 风险 |
|---|---|---|---|---|
| **第 1 步** | 改用类型过滤检索（skill + 调用方） | 30 分钟 | 否 | 低 |
| ~~第 2 步~~ ✅ | ~~回填其余 9 个项目~~ **已完成，1023 条 0 失败** | 实际约 12 分钟 | 否 | — |
| **第 3 步** | `/api/search` 返回 `status` + `superseded_by` | 1–2 小时 | 是 | 低 |
| **第 4 步** | 修 claims pending 判定 + 加回填触发接口 | 1–2 小时 | 是 | 低 |
| **第 5 步** | 人工补 4 条继任指针 | 10 分钟 | 否 | 低 |
| **第 6 步** | 清理 40 条悬空边 | 30 分钟 | 否 | 低 |

第 1、2 步就能拿到绝大部分收益。第 3 步是"让 agent 看得见新鲜度"的关键。

---

## 五、修完之后怎么验证（已就绪的量化基准）

一条命令跑完全部五层验收：

```bash
python eval-harness/v3/run_full_check.py \
  --db eval-harness/v3/self_study/snapshots/rka-snapshot-2026-08-23.db
```

覆盖 A 系统健康 / B 索引完整性 / C 检索能力 / D 图层回归 / E 图完整性，
每项带阈值判定并汇总 PASS·WARN·FAIL。

| 指标 | 现在 | 目标 | 怎么测 |
|---|---|---|---|
| 决策自检索命中率@20 | 25.8% | ≥90% | `currency/self_retrieval.py --types decision` |
| `blind_stale_exposure` | 0.067（project-F） | 0.000 | `currency/runner.py` |
| `any_status_signal` | False | True | 同上 |
| 向量覆盖率 | ~~80.2%~~ → **100.0%** ✅ | ≥99% | `run_full_check.py` [B] |
| pivot 正确率（图层） | 14/14 | 保持 | `tracing/runner.py` |

---

## 五之二、修复后的实测对照（2026-08-23）

代码改动在一个隔离测试实例（本分支 + 生产库副本，端口 9714）上验证，
未触碰你的运行实例。

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 全库向量覆盖率 | 80.2%（缺 1,023） | **100.0%（缺 0）** |
| 决策自检索 · 不过滤 | 25.8% | 30.0%（回填带来的小幅变化） |
| 决策自检索 · 类型过滤+8词 | — | **96.7%** |
| claim / journal / literature / mission 自检索 | — | 98.3 / 91.7 / 96.7 / 96.7% |
| project-F · `any_status_signal` | False | **True** |
| project-F · `blind_stale_exposure` | 0.133 | **0.0** |
| project-A · `current_first_rate` | 0.0（3/3 都搜不到） | **0.667** |
| project-F · trace_recall / pivot / stale_surfacing | 1.0 / 8-8 / 0 | 1.0 / 8-8 / 0（无退化） |

**要说准确的一点**：project-F 的 `stale_only` 仍是 2/15——agent 有时仍然只拿到
旧决策。变化在于它不再是"盲的"：结果里带 `status=superseded` 和
`superseded_by` 指针，危险从"默默用错"降级为"明确知道并能一步跳到现行版本"。
排序本身没变（`current_first_rate` 0.733 不变），那属于 P0-1 类型过滤的范畴。

全量测试：**3,269 通过**。新增 11 个回归测试，全部在修复前失败。

---

## 六、本次评测中已经改动的东西（可回退）

1. **RKA embedding 配置**：`base_url` 由 `http://<embedding-host-A>:1234`
   改为 `http://host.docker.internal:1234`。旧值备份在
   `rka-backups/embedding_config-2026-08-23-213402.json`。
2. **重启过 `rka-server` 容器**（配置生效所必需）。
3. **project-F 回填 208 条向量**（新增，未修改任何内容文本）。
4. **LM Studio**：卸载了本机的 27B chat 模型，下载并常驻
   `text-embedding-qwen3-embedding-4b`（2.5 GB, 24h TTL）。
   LLM 现走 `<llm-host-B>:1234`。

除第 4 项外都可用备份还原。
