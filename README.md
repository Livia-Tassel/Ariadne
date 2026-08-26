# ari — 实验预测、记录与复盘闭环

`ari` 是一个陪伴科研人员的本地实验工作台。它把**实验开跑前先写下对结果的预测**这件事变成低摩擦的流程，再让结果与预测的差异自动浮上来，逼出真正的反思。v0.3 提供可独立运行的桌面应用，CLI 继续作为自动化与高级入口。

核心闭环：

```
plan（填预测并锁定） → result（录实测） → 自动判定 → review（复盘 SURPRISE） → board（看板）
```

两条贯穿全局的原则：

- **负结果与正结果同等重要。** 最没有价值的是没有任何起伏的实验批次。
- **写论文所需的一切材料，在过程中自然沉淀，而不是最后回头补。**

当前桌面设计见 [`specs/2026-08-25-desktop-v0.3-design.md`](specs/2026-08-25-desktop-v0.3-design.md)，GUI 设计见 [`specs/2026-08-25-gui-v0.2-design.md`](specs/2026-08-25-gui-v0.2-design.md)，领域规则见 [`specs/2026-08-23-experiment-loop-design.md`](specs/2026-08-23-experiment-loop-design.md)。

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

## 浏览器 GUI：开发入口

```bash
ari gui -p ~/exp/lr-sweep
```

浏览器会打开本地工作台。项目不存在时会自动初始化；研究方向、变量维度、指标、预测、实测与复盘都可以直接在页面里填写，不需要编辑 YAML 或 JSON。服务默认只监听 `127.0.0.1`，页面资源随程序打包，断网也能使用。

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

### 信念账本

复盘不该只留下一段感想。`ari review` 的草稿末尾会问两件事：

- **你现在相信什么？** 写下的每一条进账本，拿到一个不可变短 ID（`bel-7a3c`，内容 hash 前 4 位）。
- **这次结果动了哪些已有信念？** 把 `unchanged` 改成 `reinforced` / `weakened` / `refuted`。

两件事都挂在同一份草稿里，不另开编辑器，整段也可以删掉不填。

`beliefs.md` 由这些事件派生，随 `ari board` 一并重新生成。被推翻的信念不会消失，只是挪到「已推翻」一节——一条被证伪的判断连同证伪它的那次实验，正是 discussion 里最有价值的段落。

引用只用 ID，不用序号：用 `#3` 这类序号引用，插入或删除一条就会让历史上所有引用静默指向别的东西。`beliefs.md` 里的编号只是渲染层给人看的。

### AI 那一层

**先说保证：整层都是可选的。** 不配 `config.toml`、不设 API key、或者干脆没网，GUI 与全部非 AI 命令的行为都不变，只是少了 AI 那一段——不报错，不阻断，不需要加任何 flag。

配置在 `ari init` 生成的 `config.toml` 里，只写平台地址与**环境变量名**，密钥的值从环境读：

```toml
[roles]
reason = "anthropic:claude-opus-5"
```

```bash
export ANTHROPIC_API_KEY=...      # 或 OPENAI_API_KEY，取决于你配了哪家
```

两家 provider 各用官方 SDK（`anthropic` / `openai`）。`base_url` 可以指向 OpenAI 兼容的自建服务——OpenAI 侧走的是 `/chat/completions`，兼容面最宽。

它做两件事：

**`ari plan`：填完预测之后，给一份定性判断。** 三样东西——预期的相对排序、每个变量的影响方向、你可能没考虑到的混淆因素。

**不给任何数值。** 通用模型对「你的私有数据集上 large 比 base 高几个点」没有有效先验，给出的数字看似精确实则编造，第一次离谱就把信任耗光了。这条是 schema 层面的保证，不是提示词里的一句请求。

调用发起在**你的预测已经写进 `runs.jsonl` 之后**。先看到 AI 的判断会产生锚定效应，你自己的预测随之失去独立性——而独立性正是这套机制价值的来源。所以不是「先算好、晚点再显示」，是那时候根本还没算。

**`ari review`：复盘时给一条有针对性的追问。** 它会检索本项目历史上相似的意外与当时写下的结论，然后问具体的问题（「两组的数据增强配置一样吗」），而不是「你觉得是为什么呢」。追问以注释形式出现在复盘草稿里，不多开一次编辑器。

AI 的输出只以 `note` 事件存档，**绝不参与判定**。verdict 永远是纯离线、可复现的。

### 判定

`runs.jsonl` 是唯一真相来源，只追加不修改。结果录入后自动判定：

- **CONFIRMED** —— 落在预测区间内，或偏差在判定阈值内
- **SURPRISE** —— 超出判定阈值，**无论方向**
- **NOISY** —— seed 间标准差已超过判定分辨率，本次判定无效，需补 seed
- **NO_RESULT / UNVERIFIED** —— 尚无结果 / 来源存疑待人工确认

`board.md` 与 `beliefs.md` 都是 `runs.jsonl` 的派生产物，删掉可随时用 `ari board` 重新生成，不丢数据。

## 开发

```bash
uv run pytest -v          # 全量测试
```

判定内核（`runkey` / `verdict` / `metrics`）是纯函数，无副作用，测试覆盖率要求最高——这些是整个系统的地基。实现计划见 `specs/plans/`。
