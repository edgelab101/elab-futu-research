# Current

## 做到哪了

- `elab-futu-research` 1.3.0 已完成，分支 `feat/v1.3.0-tiger-adapter`。
- 多平台 adapter 架构：`CaptureAdapter` 基类 + 域名 dispatcher 自动路由。
  - `FutuAdapter`：原有 JSON 接口抓取（不变）。
  - `TigerAdapter`：纯标准库 HTML 解析 laohu8.com，提取帖文、时间戳、互动数、`$Name(CODE)$` 股票符号。
  - 老虎用法：`--profile "https://www.laohu8.com/personal/<uid>/"`，下游 prepare/market/report/export 全复用。
- 审计按 adapter 声明的 `expected_streams` 判流，不再硬编双流；老虎单流（dynamics only）可通过完整性检查。
- 月度 Markdown 标题和报告头部改为平台中性措辞。
- `export-authors` 主页链接改用归档条目内记录的平台 URL，不再硬编富途 URL 格式。
- 老虎路由只认 laohu8.com URL；纯数字 UID 仍归富途（两平台 UID 格式相同，无法区分）。
- 版本号已更新：SKILL.md / CHANGELOG.md / CURRENT.md / README.md / docs/sample-report.md。

## Backlog

- 老虎媒体抓取（`--media` 对老虎当前等价 `none`，待实现）
- 老虎转发识别（当前 `is_repost=False`，转发帖待解析）
- 老虎专栏概念（老虎无专栏，待确认是否有等价入口）

## Known Limitation

- `feed_index.json` 并发同目录写无文件锁——`fcntl` 不跨 Windows 且场景低频，推迟决策。

## 使用注记

- 订单截图型博主（图多但标题无关键词）建议重抓时加 `--media evidence`，可大幅降低下载量同时保留取证图片。
- 老虎博主须传完整 laohu8.com URL；传纯数字 UID 会走富途路由。

## 基线验证

```bash
python3 -m compileall -q elab-futu-research tests
bash -n install.sh
python3 -m unittest discover -s tests -v
python3 elab-futu-research/scripts/futu_research.py doctor
```
