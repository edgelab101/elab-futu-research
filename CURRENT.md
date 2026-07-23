# Current

## 做到哪了

- `elab-futu-research` 1.2.0 已完成，分支 `feat/v1.2.0-evidence-media-and-claim-quality`。
- 新增 `--media {all,none,evidence}` 三档模式：`evidence` 只下载命中证据关键词帖子的媒体；
  `--skip-media` 保留为 `--media none` 别名，两者同给时 `--media` 优先并警告。
- 审计判重改为 `(profile_uid, feed_id)` 组合键，消除多博主归档中转发碰撞误报（实测 6 博主 7 例）。
- `_repost_original_obj` 空结构守卫：非空 dict 但 richTextItems/pictureItems 均空时不判转发。
- 媒体 tripwire 分母改 `posts_with_image_content`：纯文字博主不误报；`--media none` 标
  `skipped_by_mode`；有图但 0 媒体任务仍 WARN。
- `prepare` 尾部标签消噪：帖末连续 ≥3 个 `$symbol$` 标签且正文未讨论的 symbol 降为 D 级，
  不进方向性 claim（实测某港股博主 73% claim 为曝光标签，修复后显著改善）。
- 版本号已更新：SKILL.md / futu_research.py VERSION / CHANGELOG.md / CURRENT.md /
  docs/sample-report.md / README.md。

## Known Limitation

- `feed_index.json` 并发同目录写无文件锁——`fcntl` 不跨 Windows 且场景低频，推迟决策，
  v1.3.0 再议。

## 使用注记

- 订单截图型博主（图多但标题无关键词）建议重抓时加 `--media evidence`，可大幅降低下载量同时保留取证图片。

## 基线验证

```bash
python3 -m compileall -q elab-futu-research tests
bash -n install.sh
python3 -m unittest discover -s tests -v
python3 elab-futu-research/scripts/futu_research.py doctor
```
