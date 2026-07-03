# Quant_LLM_Wiki

[English](./README.md) | **简体中文**

> 面向量化投研的 Karpathy 式 wiki-first 知识库工具。

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/LLM-OpenAI_Compatible-orange.svg" alt="LLM">
  <img src="https://img.shields.io/badge/vector_store-ChromaDB-purple.svg" alt="ChromaDB">
</p>

Quant_LLM_Wiki 把公众号文章、网页和研究 PDF 喂进来，由 LLM 编译成一份 Markdown 知识库，用于量化投研。它遵循 Andrej Karpathy 的 [LLM-built KB 方法](https://karpathy.bearblog.dev/)：`raw/` 层负责原始入库，`wiki/` 层由 LLM 编译概念文档，`schema/` 是 LLM 和工具共同遵守的规则。向量 RAG 作为兜底基底保留，**不是**主检索路径。三个稳定的动词 —— `ingest`、`query`、`lint` —— 驱动整个流程。内置的 **Rethink Layer** 会在输出前对头脑风暴产生的想法进行新颖性和质量打分。

> 目标是**研究启发与跨文档的想法重组**，不是产出可直接交易的策略。

## 功能特性

- **多源采集**：单个 URL、批量 URL 列表、本地 HTML、PDF；对被标记为 rejected 的源会在再入库时警告
- **LLM 结构化补全**：抽取 idea blocks、迁移目标、组合钩子、失败模式等字段；并发执行，可配置并行度
- **Wiki-first 检索**：`ask` 与 `brainstorm` 都先查稳定 wiki 概念，向量 RAG 仅作兜底
- **Rethink Layer**：对头脑风暴输出做事后新颖性（向量相似度）+ 质量（LLM-as-judge）打分
- **Schema 强约束**：`wiki_lint` 每次运行都检查 frontmatter / 章节 / source 锚点；`--fix` 由 LLM 自动修复
- **Query → wiki 回流**：每次 `ask`/`brainstorm` 都回写到 wiki；`lint --maintain` 把查询日志蒸馏成补洞建议
- **交互式 Agent**：基于 LangGraph ReAct，提供 15 个工具（外加 7 个记忆工具），实时流式进度
- **Agent skills**：多步 workflow（一条龙入库、概念审核、库健康检查、概念解释、策略脑暴）固化为磁盘上的 SOP，agent 按 trigger 匹配并逐步执行，需要你决策的地方会停下等待
- **工作记忆**：agent 跨会话续接上下文——交接记录、任务、决定、按 thread 隔离的研究笔记，严格不进 wiki
- **策略对话**：带着一个模糊的策略方向来即可；agent 负责澄清、盘点 wiki 覆盖、给出带来源和失败模式的候选想法，最终收敛成落盘的策略简报
- **Provider 无关**：支持任意 OpenAI-compatible LLM（智谱 GLM、DeepSeek、月之暗面、通义、OpenAI、Ollama 等）
- **Local-first**：所有数据以 Markdown + ChromaDB 形式保存在本地

完整的架构、三动词流水线、检索不变量与设计原则见 [docs/architecture.md](docs/architecture.md)。

## 快速开始

选一种安装方式，全程使用同一列。

|                  | **A. pipx（终端用户）**                       | **B. git clone（开发者）**              |
| ---------------- | -------------------------------------------- | --------------------------------------- |
| 适用场景         | 只想运行 `qlw`，建一个个人 KB                | 想阅读/修改源码、跑测试、贡献代码        |
| 仓库在本地？     | 否                                           | 是                                      |
| 工作目录         | 任意目录（或 `$QLW_KB_ROOT`）                | 克隆出来的仓库本身                       |
| `.env` 位置      | `<工作目录>/.env`（从 CWD 自动加载）         | `<工作目录>/.env`（从 CWD 自动加载）    |
| `schema/`        | 需要一次性 fetch（见下）                     | 克隆里已有                              |

### 1. 安装

```bash
# A. pipx（推荐）
pipx install quant-llm-wiki

# B. git clone + editable install
git clone https://github.com/jackwu321/Quant_LLM_Wiki.git
cd Quant_LLM_Wiki && python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

> **需要 pipx ≥ 1.5**（旧版 pipx 自带 pip 24.0 会错误解析 `langgraph` 的新版 wheel metadata）。若安装报 `ResolutionImpossible`，先升级 pipx：`python3 -m pip install --user --upgrade --break-system-packages pipx && hash -r`。

### 2. 选定工作目录

`qlw` 会把数据写到它判定的 **KB root**，解析顺序为：显式 `--kb-root` → `$QLW_KB_ROOT` → 当前目录。

```bash
# pipx 用户 —— 引导一个工作目录并 fetch schema/
mkdir -p ~/my-kb && cd ~/my-kb
export QLW_KB_ROOT="$PWD"
curl -fsSL https://github.com/jackwu321/Quant_LLM_Wiki/archive/refs/heads/main.tar.gz \
  | tar xz --strip=1 --wildcards "*/schema/*" "*/llm_config.example.env"

# clone 用户 —— 克隆出来的仓库本身就是工作目录
cd Quant_LLM_Wiki
```

### 3. 配置 LLM

```bash
cp llm_config.example.env .env
# 把 .env 里的 API key 和 provider 信息改成你自己的
```

`.env` 的自动加载顺序：`$QLW_KB_ROOT/.env` → `$(pwd)/.env` → 包目录。也可以直接 `export` 到 shell。完整的 provider 示例见 [`llm_config.example.env`](llm_config.example.env)。

### 4. 跑一遍内置示例（不需要你自己的研究资料）

```bash
cd examples/tiny_kb
export QLW_KB_ROOT="$PWD"

qlw enrich            # 对预置示例文章做 LLM 补全
qlw embed             # 建向量索引
qlw compile           # 编译 wiki
qlw ask --query "What signals do these articles describe?"
qlw brainstorm --query "Combine momentum and sector ETF rotation"
```

具体生成的产物及查看位置见 [examples/tiny_kb/README.md](examples/tiny_kb/README.md)。

### 5. 用你自己的文章

```bash
qlw ingest --url "https://mp.weixin.qq.com/s/..."   # 公众号 / 网页 URL
qlw ingest --html-file saved.html                    # 本地保存的 HTML
qlw ingest --pdf-file paper.pdf                      # 研究 PDF
qlw ingest --url-list urls.txt                       # 批量

qlw enrich --limit 10
qlw embed
qlw ask --query "讨论了哪些动量因子？"
qlw brainstorm --query "把动量和波动率择时结合，做 ETF 轮动"
```

Ingest 成功后自动运行 `enrich` → `compile` → `embed`。用 `--no-enrich` 跳过富化（仍会 compile）；`--no-compile` 只写 raw（跳过 enrich、compile、embed）。若未设置 `LLM_API_KEY`，则只写 raw，并跳过 enrich/compile/embed 并给出提示。每个 URL 有 120 秒上限，每篇 LLM 补全有 360 秒上限，可通过 `INGEST_URL_TIMEOUT` / `LLM_ARTICLE_TIMEOUT` 覆盖。

### Wiki 维护

```bash
qlw lint                       # Schema + 健康度审计
qlw lint --fix                 # 用 LLM 自动修复不合规概念
qlw lint --maintain            # 缺口分析：未映射的 source、欠支撑的概念、过期的概念
qlw lint --maintain --apply    # 把查询驱动的 state 更新落盘（幂等）
```

## Agent 模式

```bash
qlw agent                                          # 交互式 REPL
qlw agent --query "list all articles"              # 一次性
qlw agent --query "brainstorm: 因子择时 + 风险平价"
qlw agent --thread futures                         # 续接一个具名记忆 thread
qlw agent --no-memory                              # 完全无状态运行
qlw memory show                                    # 查看工作记忆
```

Agent 会调度 [docs/architecture.md#agent-layer](docs/architecture.md#agent-layer) 列出的 15 个工具，记忆启用时（默认开启）再加 7 个工作记忆工具。多步 workflow——一条龙入库、概念审核、库健康检查、概念解释、策略脑暴——以 **skill** 形式运行：agent 按 trigger 匹配磁盘上的 SOP 并逐步执行，需要你决策的地方会停下等待。`qlw memory promote-procedure <id>` 可以把你自己的常用流程升级为 KB 级 skill。

**工作记忆**（`<kb_root>/.qlw/memory/`）让会话有连续性：一份可手改的 `workflow.md`，加一个存放会话 / 任务 / 决定 / 按 thread 隔离的研究笔记的 SQLite 库，均可通过 `qlw memory` 查看管理。带着一个模糊的策略方向开场（"想看看宏观周期和商品期限结构有没有结合点"），agent 会澄清约束、盘点 wiki 覆盖、给出带来源和失败模式的候选想法，并且——只在你明确示意后——把对话收敛成 `outputs/brainstorms/` 下的策略简报。

## 配置项

| 变量                          | 默认值                                  | 说明                                              |
| ---------------------------- | -------------------------------------- | ------------------------------------------------ |
| `LLM_API_KEY`                | —                                      | API key                                          |
| `LLM_BASE_URL`               | `https://open.bigmodel.cn/api/paas/v4` | OpenAI-compatible 接口地址                       |
| `LLM_MODEL`                  | `glm-4.7`                              | 对话模型                                         |
| `LLM_EMBEDDING_MODEL`        | `embedding-3`                          | 嵌入模型                                         |
| `LLM_CONNECT_TIMEOUT`        | `15`                                   | 连接超时（秒）                                   |
| `LLM_READ_TIMEOUT`           | `180`                                  | 读超时（秒）                                     |
| `LLM_MAX_RETRIES`            | `4`                                    | 最大重试次数                                     |
| `LLM_MIN_INTERVAL_SECONDS`   | `2.0`                                  | 进程内 LLM 请求之间的最小间隔                    |
| `LLM_CONCURRENCY`            | `3`                                    | 补全 worker 并发度                               |

向前兼容：旧的 `ZHIPU_*` 前缀变量也能作为 fallback。当 provider 返回 HTTP 429 时，同进程后续 LLM 请求会遵循一个共享 cooldown（优先使用 `Retry-After` 头）。

文章 status 生命周期与 `content_type` 分类见 [docs/metadata-schema.md](docs/metadata-schema.md)。

## 文档导航

- [docs/architecture.md](docs/architecture.md) — 系统架构、三动词流水线、检索不变量、设计原则
- [docs/metadata-schema.md](docs/metadata-schema.md) — 文章 frontmatter 字段与枚举
- [docs/brainstorm-output-spec.md](docs/brainstorm-output-spec.md) — 头脑风暴输出契约
- [docs/releasing.md](docs/releasing.md) — 维护者发布流程
- [`schema/`](schema/) — `qlw lint` 强制执行的契约
- CLI 详细参数请用 `qlw <subcommand> --help`（命令本身就是 source of truth）。

## 跑测试

测试在仓库里，wheel 里没有 —— 请用 git clone 的方式（安装方式 B）。

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m unittest discover -s tests/robustness -p 'test_*.py' -v
```

`tests/robustness/` 覆盖 Layer 1（工具输入）、Layer 2（工作流整合）、Layer 3（Agent 路由）、Layer 4（LLM API 超时与重试）。

## 贡献

1. Fork 并新建 feature 分支
2. 为新功能写测试
3. 跑通 `python3 -m unittest discover -s tests -p 'test_*.py'`
4. 提 PR

## License

MIT —— 见 [LICENSE](LICENSE)。

## 免责声明

Quant_LLM_Wiki 是一个用于产生投资策略灵感的研究工具，**不**生成可直接交易的策略，也不构成任何投资建议。所有生成的想法在用于真实场景前都需要独立验证、回测和风险评估。使用者自行承担风险。
