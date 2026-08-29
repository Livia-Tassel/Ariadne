# ari — 实验预测、记录与复盘闭环

`ari` 是一个陪伴科研人员的本地实验工作台。它把**实验开跑前先写下对结果的预测**这件事变成低摩擦的流程，再让结果与预测的差异自动浮上来，逼出真正的反思。v0.4 的桌面应用与 CLI 功能对等，不再是它的子集。

核心闭环：

```
调研（分层阅读 → 瓶颈） → 想法 → plan（锁定预测） → result（录实测）
  → 自动判定 → review（复盘意外） → 信念 → 论文
```

调研那一段是可跳过的——不是每次开工都在进新领域。但它必须存在，否则「想法从哪来」这个问题系统一句话都没说。

两条贯穿全局的原则：

- **负结果与正结果同等重要。** 最没有价值的是没有任何起伏的实验批次。
- **写论文所需的一切材料，在过程中自然沉淀，而不是最后回头补。**

领域调研见 [`specs/2026-08-29-survey-v0.5-design.md`](specs/2026-08-29-survey-v0.5-design.md)，界面与闭环见 [`specs/2026-08-27-gui-v0.4-design.md`](specs/2026-08-27-gui-v0.4-design.md)，桌面壳见 [`specs/2026-08-25-desktop-v0.3-design.md`](specs/2026-08-25-desktop-v0.3-design.md)，领域规则见 [`specs/2026-08-23-experiment-loop-design.md`](specs/2026-08-23-experiment-loop-design.md)。

## 安装

需要 Python ≥ 3.11 与 [uv](https://docs.astral.sh/uv/)。

```bash
git clone <this-repo> ariadne && cd ariadne
uv sync          # 装依赖
```

## 跑起来：用 `bin/ari`

直接 `uv run ari` 在某些 macOS 环境下会失效：本机 `.venv` 里的文件被打上 `UF_HIDDEN` 标记时，CPython ≥ 3.13 会静默跳过 hidden 的 `.pth`，editable 安装因此不生效，且 `uv` 不报任何错。

`bin/ari` 用显式设置 `PYTHONPATH` 的方式绕开了对 `.pth` 的依赖。建议把它链进 PATH，这样任何目录下都能直接 `ari`：

```bash
ln -s "$(pwd)/bin/ari" ~/.local/bin/ari   # 或你 PATH 里的任意目录
```

之后：

```bash
ari --help
```

> 如果你的环境没有 hidden `.pth` 的问题，`uv run ari` 同样可用；`bin/ari` 只是更稳的入口。

## 桌面应用：推荐入口

开发仓库已经可以构建 macOS 应用：

```bash
uv sync --extra desktop --group package
./scripts/build_macos_app.sh
```

构建完成后，直接在 Finder 双击 `dist/Ariadne.app`。应用启动时会显示系统目录选择器：选择空目录即可创建项目，选择已有 Ariadne 目录则直接打开。之后不需要终端。

当前 `.app` 是本地预览构建，尚未使用 Apple Developer ID 签名与公证，不应直接作为公开下载版本发布。

## 浏览器 GUI

```bash
ari gui -p ~/exp/lr-sweep
```

浏览器会打开本地工作台。项目不存在时会自动初始化；假设、变量、指标、预测、实测与复盘都直接在页面里填写，不需要编辑 YAML 或 JSON。服务默认只监听 `127.0.0.1`，页面资源随程序打包，断网也能使用。

界面按**实验台账**来做：细线分隔而不是卡片，散文用衬线、数据一律等宽且按指标容差对齐小数位，全站只有一个饱和色——留给"意外"。判定不靠颜色单独承载语义，位置、字重、文字标签三重编码。

首屏不放统计瓦片，放一列排好序的待办：待复盘的意外在最前（信息量最大，且唯一会随时间衰减），其次是预测缺席但结果已在库的 run，然后才是等结果、补 seed、可收口。每行自己说清事由——`0.8200 → 0.7690　−0.051`——不用点进去才知道发生了什么。

下面是**校准记录**：命中率、带符号的平均偏差（一直高估和一直低估是两种不同的毛病），以及按你当时写下的置信度分档的命中率。如果说"高"的时候并不比说"低"时更准，界面会直说这个字段是噪声。

### 三件在 GUI 里做起来最顺的事

**录结果走自动发现。** 声明了 `result_path` 模板之后，点一次"扫描结果文件"，抽到的先给你看一眼——"抽到了这些，对吗？"——确认后才落盘。已经录过的 seed 会标出来并禁选；对得上模板却不属于任何 run 的文件单独列出（多半是模板写错，或跑了计划外的配置）；某个文件读不了不会让整次发现失败。

这不只是省敲键盘：`result_predates_prediction`（先看结果再补预测的嫌疑）靠结果文件的 mtime 判断，而 mtime 只存在于文件发现这条路上。手敲没有 mtime，也就没有这个检查。

**预测可以渐进锁定。** 开一个批次只要三样：假设、变量、指标。变量用一行紧凑语法（`model=base,large; aug=none,strong`），指标只要名字——方向与容差从名字推断。预测表移到批次页，逐个 run 填、逐个锁：约束是"某个 run 的预测必须先于它的结果"，这是逐 run 的，不需要在跑任何实验之前把 N×M 个格子填完。

**进新领域时先做一次调研。** 见下一节。

**AI 那一层在 GUI 里也有。** 见后面「AI 那一层」。

## 领域调研

```
今天   调研   批次   账本   论文
```

给一句话主题和一个 OpenAlex 检索式（可以让 AI 拟，你改完再存），系统抓回近几年的一批论文，然后**按引用图算出该你亲自读的那十来篇**：

```
19 引用 · 2016 · Deep Residual Learning for Image Recognition
16 引用 · 2019 · A survey on Image Data Augmentation for Deep Learning
 7 引用 · 2014 · Dropout: a simple way to prevent neural networks from overfitting
```

「19 引用」是**内部被引**——这批近期工作里有 19 篇引了它。这比原始被引数好：原始被引数受领域规模影响极大，一篇平庸的综述可能比奠基工作被引更多。

**里程碑不问 AI。** 理由与「AI 不给数值」同构但更严重：编造的数值跑一次实验就发现了，编造的引用会跟着你进 related work。所有条目来自 OpenAlex，每条都带 Work ID，可点开核实。分层可以人工改——算法给的是起点，不是判决。

**AI 摘要不等于你读过。** 这一层真正的风险不是幻觉，是读了 40 篇摘要之后记成自己调研过。所以它是结构保证不是界面标签：你的精读笔记落 `paper_read` 事件（必填「这篇给了我什么」），AI 摘要落 `note` 事件，而所有投影都跳过 `note`——「已读」在数据层面就不可能被 AI 写入。

调研以一句**瓶颈陈述**结束，一键立为想法。写完才能看 AI 的独立判断，和预测层是同一条锚定规则。草稿引用一个调研，导出时展开成里程碑清单与你的精读笔记——related work 的原始材料本来就是这些。

数据源是 OpenAlex：不需要 API key，限流是信用点制（约 1000 点/20 小时，一次调研约 20 点），界面上会显示剩余额度。断网时调研页照常显示已抓到的一切，只是抓不了新的。可以在 `config.toml` 里配 `[openalex] mailto` 以进入礼貌池。

## CLI：自动化与高级入口

```bash
ari init ~/exp/lr-sweep        # 建立项目骨架
ari plan  -p ~/exp/lr-sweep    # 编辑器里填批次设计，再填预测表，保存即锁定
# ……跑实验……
ari result -p ~/exp/lr-sweep   # 按 result_path 模板自动发现结果文件，确认后入库
ari review -p ~/exp/lr-sweep   # 逐个处理 SURPRISE，写复盘与信念，收口批次
ari board  -p ~/exp/lr-sweep   # 渲染看板，重新生成 board.md 与 beliefs.md
```

全程不需要手写一行 JSON。

### 命令

| 命令 | 作用 |
|---|---|
| `ari init <dir>` | 建立项目目录骨架（`runs.jsonl` / `logs/` / `config.toml`） |
| `ari plan` | 开批次：写假设、声明变量维度与指标规格，填预测表并锁定。支持 `--dims "model=base,large"` 预置维度跳过第一段编辑 |
| `ari result` | 录入实测：按 `result_path` 模板自动发现结果文件，或 `--manual` 手工填写。解析结果先展示「抽到了这些，对吗？」确认后才落盘 |
| `ari review` | 逐个复盘 SURPRISE 的 run，追问原因，写 `reflection`；顺手记下信念的增减；全部处理完后可写一条 batch 级收口 |
| `ari board` | 渲染看板，并重新生成 `board.md` 与 `beliefs.md`。未复盘的 SURPRISE 置顶 |
| `ari gui` | 启动本地可视化工作台，项目不存在时自动初始化 |

> GUI 与 CLI 共用同一套领域函数与同一份 `runs.jsonl`，两边可以混着用。

### 信念账本

复盘不该只留下一段感想。`ari review` 的草稿末尾会问两件事：

- **你现在相信什么？** 写下的每一条进账本，拿到一个不可变短 ID（`bel-7a3c`，内容 hash 前 4 位）。
- **这次结果动了哪些已有信念？** 把 `unchanged` 改成 `reinforced` / `weakened` / `refuted`。

两件事都挂在同一份草稿里，不另开编辑器，整段也可以删掉不填。

`beliefs.md` 由这些事件派生，随 `ari board` 一并重新生成。被推翻的信念不会消失，只是挪到「已推翻」一节——一条被证伪的判断连同证伪它的那次实验，正是 discussion 里最有价值的段落。

引用只用 ID，不用序号：用 `#3` 这类序号引用，插入或删除一条就会让历史上所有引用静默指向别的东西。`beliefs.md` 里的编号只是渲染层给人看的。

### AI 那一层

**先说保证：整层都是可选的。** 不配 `config.toml`、不设 API key、或者干脆没网，GUI 与全部非 AI 命令的行为都不变，只是少了 AI 那一段——不报错，不阻断，不需要加任何 flag。GUI 里拿不到就显示一行安静的说明，而不是红色报错。

配置在 `ari init` 生成的 `config.toml` 里，只写平台地址与**环境变量名**，密钥的值从环境读：

```toml
[roles]
reason = "anthropic:claude-opus-5"
```

```bash
export ANTHROPIC_API_KEY=...      # 或 OPENAI_API_KEY，取决于你配了哪家
```

两家 provider 各用官方 SDK（`anthropic` / `openai`）。`base_url` 可以指向 OpenAI 兼容的自建服务——OpenAI 侧走的是 `/chat/completions`，兼容面最宽。

它做两件事，CLI 与 GUI 共用同一个入口（`advising.advise` / `probing.probe`），两边的降级行为不会漂移：

**锁定预测之后，给一份定性判断。** 三样东西——预期的相对排序、每个变量的影响方向、你可能没考虑到的混淆因素。GUI 会把它和你的实测排序并排放，不一致的位次标红：分歧本身就是有信息量的信号。

**不给任何数值。** 通用模型对「你的私有数据集上 large 比 base 高几个点」没有有效先验，给出的数字看似精确实则编造，第一次离谱就把信任耗光了。这条是 schema 层面的保证，不是提示词里的一句请求。

调用发起在**你的预测已经写进 `runs.jsonl` 之后**。先看到 AI 的判断会产生锚定效应，你自己的预测随之失去独立性——而独立性正是这套机制价值的来源。所以不是「先算好、晚点再显示」，是那时候根本还没算：一个预测都没锁时，GUI 里这个按钮根本不出现，接口也会拒绝。

**复盘时给一条有针对性的追问。** 它会检索本项目历史上相似的意外与当时写下的结论，然后问具体的问题（「两组的数据增强配置一样吗」），而不是「你觉得是为什么呢」。CLI 里它以注释形式出现在复盘草稿里；GUI 里它出现在复盘表单上方。

AI 的输出只以 `note` 事件存档，**绝不参与判定**。verdict 永远是纯离线、可复现的。

### 判定

`runs.jsonl` 是唯一真相来源，只追加不修改。结果录入后自动判定：

- **CONFIRMED** —— 落在预测区间内，或偏差在判定阈值内
- **SURPRISE** —— 超出判定阈值，**无论方向**
- **NOISY** —— seed 间标准差已超过判定分辨率，本次判定无效，需补 seed
- **NO_RESULT / UNVERIFIED** —— 尚无结果 / 来源存疑待人工确认

### 完整性标记

判定之外还有一层：这条记录本身可不可信。三种标记都随事件流永存，界面上显著可见，且**不阻止你继续**——只是记录下来。

| 标记 | 含义 |
|---|---|
| `result_predates_prediction` | 结果文件的修改时间早于预测写入时间——先看结果再写预测的嫌疑 |
| `result_without_prediction` | 这个 run 有实测值却没有预测，无法判定 |
| `prediction_after_result` | 预测是在结果已经入库之后才写下的 |

最后一条比 mtime 比对更强：它以事件顺序本身作证据，`touch` 一下文件绕不过去。

工具的立场是：不阻止你事后补预测，也永不拒绝一次真实的测量——事件流是只追加的唯一真相，拒绝记录比记下它更糟。但那条记录会一直带着这个标记。

`board.md` 与 `beliefs.md` 都是 `runs.jsonl` 的派生产物，删掉可随时用 `ari board` 重新生成，不丢数据。

## 开发

```bash
uv run pytest -v          # 全量测试
```

判定内核（`runkey` / `verdict` / `metrics`）是纯函数，无副作用，测试覆盖率要求最高——这些是整个系统的地基。实现计划见 `specs/plans/`。
