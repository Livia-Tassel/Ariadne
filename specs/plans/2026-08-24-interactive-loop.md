# 交互闭环 实现计划（v1 第二阶段）

> **For agentic workers:** 每个任务遵循 @superpowers:test-driven-development：先写失败的测试，跑一遍确认失败，再写最小实现，最后提交。

**Goal:** 补齐 `plan` / `result` / `review` 三个命令，让整条闭环不需要手写 JSONL 就能走完，并解决 `ari` 命令本身在本机跑不起来的问题。

**Architecture:** 三个命令共享同一套交互形态——**生成带注释的 YAML 草稿 → `$EDITOR` 打开 → 保存后校验 → 写入事件流**。草稿的构造与解析是纯函数（可严格断言），编辑器调用隔离在 `editor.py` 一个函数里（测试时 monkeypatch）。业务逻辑不碰 `$EDITOR`，也不碰 typer。

**Spec:** `specs/2026-08-23-experiment-loop-design.md` §4、§5
**前置:** `specs/plans/2026-08-23-kernel-and-board.md`（已完成）

**本计划不含：** LLM 层（provider 适配器、AI 的那份判断、复盘时的针对性追问）与信念账本。这两块留给计划三；spec §8 要求「LLM 不可用时所有非 LLM 功能必须能离线工作」，所以本计划交付的就是那个可离线工作的完整闭环。

---

## 交付定义

一个从没见过这个工具的人，能够：

```bash
ari init ~/exp/lr-sweep
ari plan    -p ~/exp/lr-sweep     # 编辑器里填批次设计，再填预测表，保存即锁定
# ...跑实验...
ari result  -p ~/exp/lr-sweep     # 自动找到结果文件，确认后入库
ari review  -p ~/exp/lr-sweep     # 逐个处理 SURPRISE，写复盘
ari board   -p ~/exp/lr-sweep     # 看板
```

全程不手写一行 JSON。

## 文件结构

```
bin/ari                  可执行包装脚本，绕开本机 editable 安装失效的问题
README.md                安装与用法
src/ari/
  editor.py              $EDITOR 调用的唯一入口（测试时 monkeypatch 这一个函数）
  drafts.py              YAML 草稿的公共部分：注释头、数值解析、校验错误回填
  planning.py            ari plan：批次设计草稿 / 预测表草稿 / 校验 / 事件构造
  ingest.py              ari result：路径模板反解、结构化文件解析、手填草稿
  reviewing.py           ari review：待复盘队列、复盘草稿、事件构造
  cli.py                 入口（新增 plan / result / review）
tests/
  test_editor.py  test_drafts.py  test_planning.py
  test_ingest.py  test_reviewing.py  test_e2e_loop.py
  fixtures/results/      真实形态的 results.json / metrics.csv 样本
```

## 贯穿全局的两条交互原则

1. **绝不吞掉用户已经敲进去的内容。** 校验不过就把原文连同错误注释一起重新打开，让人在原地改。这是最容易偷懒、也最不可原谅的地方。
2. **草稿里写满注释。** 用户第一次打开时不该需要查文档：每个字段旁边写清楚填什么、为什么要填。

---

## Task 1: `bin/ari` 包装脚本与 README

本机 `.venv` 下所有文件被打了 macOS `UF_HIDDEN` 标记，CPython ≥3.13 会静默跳过 hidden 的 `.pth`，导致 editable 安装失效、`uv run ari` 报 ModuleNotFoundError。这是机器层面的问题，仓库里改不掉，但可以让调用方式不依赖 `.pth`。

**Files:** Create `bin/ari`、`README.md`

- [ ] **Step 1: 写 `bin/ari`**，显式设置 `PYTHONPATH` 后 `exec ... python -m ari "$@"`，`chmod +x`
- [ ] **Step 2: 验证** `./bin/ari --help` 与 `./bin/ari board -p /tmp/ari-demo` 均可用
- [ ] **Step 3: 写 README**：安装、把 `bin/ari` 链进 PATH、五个命令的用法、hidden `.pth` 问题的说明
- [ ] **Step 4: 提交**

## Task 2: `editor.py` — 编辑器调用隔离

**Files:** Create `src/ari/editor.py`、`tests/test_editor.py`

接口：`edit_text(initial: str, suffix: str = ".yaml") -> str | None`，包装 `click.edit`，用户未改动或清空时返回 `None`。整个项目里只有这一处碰 `$EDITOR`，其余模块全部是纯函数——测试只 monkeypatch 这一个函数。

- [ ] 测试：透传返回值；未改动返回 None；`$EDITOR` 未设置时报清晰的错而不是栈回溯
- [ ] 实现 → 跑通 → 提交

## Task 3: `drafts.py` — 草稿公共件

**Files:** Create `src/ari/drafts.py`、`tests/test_drafts.py`

- `parse_number(value)` → float，接受 `1e-4` / `0.0001` / `80%`（转 0.8）
- `parse_prediction(value)` → float 或 (low, high)，接受 `0.83` / `[0.80, 0.84]` / `0.80~0.84`
- `with_errors(text, errors)` → 在草稿顶部插入 `# ⚠ ...` 错误注释块，保留原文
- `strip_error_header(text)` → 重新解析前剥掉上一轮的错误注释

测试重点：`with_errors` 反复调用不会累积多份错误块（用 `strip_error_header` 先剥）；原文一字不改。

## Task 4: `ari plan` 第一段——批次设计草稿

**Files:** Create `src/ari/planning.py`、`tests/test_planning.py`

- `next_batch_id(batches)` → `b1` / `b2` / ...
- `build_design_draft(batch_id)` → 带注释的 YAML：`hypothesis` / `dimensions` / `metrics` / `result_path` / `expected_ranking`
- `parse_design(text)` → `Design` 或 `ValidationError` 列表
- `expand_runs(dimensions)` → 笛卡尔积 → `runkey.make_run_key` 规范化后的 run 列表

校验：hypothesis 非空；dimensions 至少一维且每维至少一个取值；metrics 至少一个且每个都能拿到 spec（拿不到就要求显式声明 direction/compare/tolerance）。

测试重点：笛卡尔积顺序稳定；`1e-4` 与 `0.0001` 归一到同一 run；空 hypothesis 被拒；未知指标名报错并指名道姓。

## Task 5: `ari plan` 第二段——预测表草稿

**Files:** Modify `src/ari/planning.py`、`tests/test_planning.py`

- `build_prediction_draft(design, runs)` → 每个 run 一块，字段 `<metric>` / `confidence` / `rationale`，注释里写明「区间比点估计更诚实」「rationale 必填，缺了它事后无法定位错的是哪个假设」
- `parse_predictions(text, design)` → `{run: payload}` 或错误列表
- `build_events(design, predictions, now)` → `batch_opened` + 每个 run 一条 `prediction`

校验：每个 run 的每个指标都有值；`rationale` 非空；`confidence` ∈ low/medium/high；`expected_ranking.order` 里的 run 必须都存在。

测试重点：漏填一格 → 错误里指名哪个 run 哪个指标；rationale 留空 → 拒绝；区间三种写法都能解析；事件的 `ts` 由参数注入（不调 `Date.now` 之类，保证可测）。

## Task 6: `ari plan` 命令接线

**Files:** Modify `src/ari/cli.py`、Create `tests/test_cli_plan.py`

流程：读现有事件 → 生成设计草稿 → 编辑 → 校验（失败则回填错误重开）→ 展开 runs → 生成预测表草稿 → 编辑 → 校验（同上）→ 追加事件 → 提示下一步。

支持 `--dims "model=base,large"` 跳过第一段编辑。

测试（monkeypatch `edit_text` 返回预置文本）：完整走通写出正确事件；第一段校验失败时**用户内容不丢**且错误出现在重开的文本里；用户放弃编辑（返回 None）时不写任何事件。

## Task 7: `ari result` ——结果文件发现与解析

**Files:** Create `src/ari/ingest.py`、`tests/test_ingest.py`、`tests/fixtures/results/`

- `compile_template(template)` → 把 `logs/{model}_{lr}/s{seed}/results.json` 编译成正则，`{seed}` 特殊对待
- `discover(root, template, runs)` → `[(run, seed, path)]`，匹配不上的文件明确列出不静默跳过
- `parse_result_file(path, metric_names)` → `{metric: value}` + 定位信息；支持 `.json`（顶层扁平 + 一层嵌套 + 点号路径）与 `.csv`（表头 + 取最后一行，并在确认页说明「取的是最后一行」）
- 缺失指标明确报告，不填空

测试重点：模板反解出的变量能对上规范化后的 run key；`{seed}` 缺省为 0；JSON 缺字段 → 报告缺失；CSV 取末行；未知扩展名 → 清晰报错。

## Task 8: `ari result` ——确认与手填

**Files:** Modify `src/ari/ingest.py`、`src/ari/cli.py`、Create `tests/test_cli_result.py`

- 解析结果先渲染成「抽到了这些，对吗？」表格，确认后才落盘
- `--manual` 或无模板时：生成 run×metric 的手填草稿，编辑器填
- 每条 `run_result` 带 `source`（path / kind / mtime），mtime 供时序校验用

测试：确认后事件写入且 `source.kind` 正确；拒绝确认时不写；手填草稿往返；重复录入同一 (run, seed) 时覆盖并提示。

## Task 9: `ari review`

**Files:** Create `src/ari/reviewing.py`、`tests/test_reviewing.py`、`tests/test_cli_review.py`

- `pending(batches)` → 未复盘的 SURPRISE run，按批次顺序
- `build_reflection_draft(run)` → 顶部以注释形式并排展示：预测、实测（含各 seed 与 sd）、**具体哪个指标偏了多少**、当初写下的 rationale；下面是 `cause` / `next` 两个待填字段
- `parse_reflection(text)` → payload 或错误（`cause` 必填）
- 全部 SURPRISE 处理完后，询问是否写 batch 级 reflection 收口

测试：队列顺序；草稿里含偏差数字与原 rationale；cause 留空被拒；写入后该 run 从队列消失；无待复盘时给出友好提示而非空跑。

## Task 10: 端到端全闭环

**Files:** Create `tests/test_e2e_loop.py`

在 tmp 目录里 monkeypatch 编辑器，完整跑 `init → plan → result → review → board`，断言：

- `runs.jsonl` 的事件类型与顺序正确
- 看板上 SURPRISE 置顶 → 复盘后消失、批次转「已收口」
- 全程没有任何一步需要手写 JSON

## Task 11: 人工验收

真跑一遍，用编辑器实际填一次预测表。重点看：**填预测这件事本身别扭不别扭**——这是整个项目的头号风险，草稿的措辞、字段顺序、注释密度都在这一步定生死。发现的问题当场修。

## 完成检查

- [ ] `uv run pytest` 全绿
- [ ] `./bin/ari` 五个命令都能跑
- [ ] Task 11 的人工验收做过
- [ ] 校验失败时用户输入的内容一个字都没丢（有测试覆盖）
- [ ] 全程无需手写 JSON
