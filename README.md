# elab-futu-research

by 杰尼马 · [EdgeLab](https://github.com/edgelab101)：给散户的可审计投研工具箱

把一个或多个富途牛牛公开主页，变成”可复查的完整归档 + 结合当时行情的博主研究报告”。

它不是荐股器，也不会把“提到某只股票”误判成“真实持仓”。它保存原始证据、动态、专栏、图片、失败清单与审计结果，再把观点、交易动作、行情背景和事后结果分开分析。

## 最省事的用法

启动后 skill 会先确认四项参数（研究对象、时间范围、交付物、其他约束），已提供的不重复问，缺的一次性集中问完，确认后再开始抓取。

### 安装

```bash
git clone https://github.com/edgelab101/elab-futu-research.git
cd elab-futu-research
bash install.sh
```

安装脚本会同时安装到：

- Codex：`~/.codex/skills/elab-futu-research`
- Claude Code：`~/.claude/skills/elab-futu-research`

不需要 API Key，也不会读取或复制浏览器 Cookie。

### 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | macOS / Linux 开箱即用；Windows 需 Git Bash 或 WSL（`install.sh` 是 bash 脚本） |
| Python | 3.9+（核心归档和审计仅用标准库，无需额外安装） |
| 第三方依赖 | 无 |
| API Key | 无需；不登录、不读取 Cookie |

如只运行 CLI 而不使用安装脚本，Windows 的 PowerShell/CMD 可先 `cd elab-futu-research` 再调用 `python3 scripts\futu_research.py`，或从仓库根目录用完整路径 `python3 elab-futu-research\scripts\futu_research.py`。Python 3.9+ 在 Windows 下无需额外安装 tzdata，脚本遇到时区初始化失败时会自动 fallback 到固定 UTC+8，不影响核心功能。

### 在 Codex 中

```text
$elab-futu-research 分析这个博主：https://q.futunn.com/profile/<uid>
```

### 在 Claude Code 中

```text
/elab-futu-research 分析这个博主：https://q.futunn.com/profile/<uid>
```

默认行为：

- 同时抓取“动态”和“专栏”；
- 未指定日期时，抓取当前仍公开可见的全部历史；
- 保存正文、转发关系、标的、互动数、原始 JSON 和公开图片；
- 自动续跑，不重复下载已经成功保存的内容；
- 生成 CSV、JSONL、按月 Markdown、行情补全、初步报告和审计文件；
- 只有主页链接是必填项。

也可以直接运行：

```bash
python3 elab-futu-research/scripts/futu_research.py run \
  --profile "https://q.futunn.com/profile/<uid>" \
  --output "./futu-research-output"
```

多位博主就重复传入 `--profile`：

```bash
python3 elab-futu-research/scripts/futu_research.py run \
  --profile "https://q.futunn.com/profile/<uid-a>" \
  --profile "https://q.futunn.com/profile/<uid-b>"
```

日期筛选：

```bash
python3 elab-futu-research/scripts/futu_research.py run \
  --profile "https://q.futunn.com/profile/<uid>" \
  --since 2025-01-01 \
  --until 2025-12-31
```

## 为什么分析不是简单算“荐股胜率”

公开发言至少要分四层：

1. 看到或提到一个标的；
2. 对标的有方向性观点；
3. 明确声称自己买入、卖出、加仓或减仓；
4. 有订单、成交、成本、仓位或盈亏证据。

这四层不能混为一谈。研究流程会先在“不看未来收益”的状态下冻结观点和证据等级，再补充发言当时已经发生的行情，最后才观察 1/5/20/60 个交易日的后续路径、MFE、MAE 和相对基准表现。

最终输出的是能力矩阵、风格、纪律、不同市场状态下的应对、反例和可迁移规则，而不是一个诱导跟单的总分榜。

## 输出目录

```text
futu-research-output/
├── raw/          # 原始分页和逐帖详情
├── media/        # 公开图片
├── archive/      # JSONL、CSV、按月 Markdown
├── analysis/     # 候选观点、复核观点、行情与事件
├── reports/      # 画像、能力矩阵、规则卡
├── qa/           # 抓取完整性和对抗审查
└── manifest.json
```

`raw/` 是证据层，派生分析可以重建，不应手工改写。

## 完整性的真实边界

“完整历史”指运行时富途仍然返回的全部公开内容。删帖、私密内容、地区限制内容、平台没有返回的旧记录，以及仅在登录后可见的内容，不可能被本工具宣称为已经抓到。

富途网页和内部接口可能变化。工具会先检查响应结构；遇到登录、验证码、限流或接口漂移时会停止并留下明确错误，不会绕过访问控制，也不会悄悄生成假数据。

## 隐私与安全

- 仓库只包含通用方法、脚本和虚构测试夹具。
- 不包含创建者的 UID、帖子、持仓、交易记录、Cookie、Token 或分析结果。
- 默认只处理公开主页内容。
- 发布或转发研究报告前，仍应检查用户名、头像、图片和正文是否符合你的使用目的、平台规则与当地法律。

## 运行环境

- Python 3.9+
- 核心归档、标准化、审计使用 Python 标准库
- 行情按“本地 CSV → 无 Key 公共日线接口”的顺序尝试；每条记录写明真实来源，接口失败时明确记录缺失
- OCR/图片理解是可选能力，由 Codex、Claude Code 或本机可用工具完成

## 运行测试

```bash
python3 -m unittest discover -s tests
```

标准库即可运行，无需安装 pytest。如已安装 pytest，也可用 `pytest tests/`。

## 账号安全 FAQ

**工具会登录我的富途账号吗？**
不会。工具只访问公开主页接口，不需要登录，也不读取浏览器 Cookie 或本地凭据。

**会被识别或限流吗？**
工具采用保守限速，单次请求间隔随机在合理范围内。如果富途返回登录跳转、验证码或限流信号，工具会立即停止并输出明确错误，不会绕过访问控制。

**批量抓取历史怎么办？**
对于有大量历史的博主，建议加 `--since YYYY-MM-DD` 限制窗口，例如只抓近一年的数据，可以显著降低请求量，也更快完成。抓取结果支持断点续跑，下次运行会跳过已保存的内容。

**遇到接口变动或验证码怎么办？**
工具会停下并在日志中记录具体原因，不会悄悄生成假数据或绕过访问控制。按提示检查对应的 `qa/` 审计文件，了解本次运行的完整性边界。

## 产出物使用边界

工具运行本身合规，不等于产出物可以随意分发。使用前请了解以下边界：

- **自用研究和复盘没有问题。** 把归档和报告用于你自己的投资分析、学习记录、回溯验证，均属正常使用。
- **含他人帖子原文的完整归档或报告，不建议对外公开分发。** 富途帖子的原文著作权属于原作者，平台条款也对此有限制。你可以分享你自己的分析结论，但整份归档或含大量转载原文的报告应仅供自用。
- **分享时应脱敏可识别信息。** 如果你分享分析结论，建议隐去对方的真实昵称、头像和具体帖子链接，只呈现你归纳出的规律和观点。
- **本工具不构成投资建议，历史发言和后续涨跌不是 Alpha。** 报告展示的是能力评估，不是荐股依据。

样例报告（虚构数据）：[docs/sample-report.md](docs/sample-report.md)

## 许可与声明

采用 CC BY-NC 4.0：允许署名分享和修改，不允许商业售卖或打包进收费产品。

仅供研究与教育，不构成投资建议。历史公开发言和后续价格表现不能证明稳定 Alpha。
