# Current

## 做到哪了

- `elab-futu-research` 1.1.0 已完成，分支 `fix/repost-attribution-and-startup-contract`。
- 需求 1（转发误标原创）：通过 `feedModel.original` / `moduleData[i].data.origin` 正确检测转发；
  `text` 拆分为自己评论，`original_text` 存被转内容，`original_author` 存原帖作者（如有）；
  转发标题不再复读原帖内容；月 Markdown 渲染"原创：否；转自：<author>"并以引用块展示原帖。
- 需求 2（启动对齐契约）：`SKILL.md` 新增"Startup alignment (required)"节，要求运行前
  对齐四项参数并输出一行摘要"博主 X · 范围 Y · 交付 Z · 输出目录 W · elab-futu-research by 杰尼马（EdgeLab）"。
- 品牌追加：报告 footer credit、README 品牌行、install.sh 完成提示均已更新。
- 测试：5 个测试全通过（新增 `test_repost_attribution` + end-to-end footer 断言）。

## 下一步

- v1.2.0 待办（盲评 P2 两条）：① `_repost_original_obj` 对"非空 dict 但 richTextItems/pictureItems 均空"的边界加守卫，防真原创被误判转发；② tripwire 改用 `posts_with_images` 计数做守卫，消除纯文字博主的审计误报。

- 将分支 `fix/repost-attribution-and-startup-contract` PR 合并到 main 并发布。
- 按基线命令持续运行离线测试；后续接口漂移或规则改动通过 PR 发布。

## 基线验证

```bash
python3 -m compileall -q elab-futu-research tests
bash -n install.sh
python3 -m unittest discover -s tests -v
python3 elab-futu-research/scripts/futu_research.py doctor
```
