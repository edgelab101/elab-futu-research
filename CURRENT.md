# Current

## 做到哪了

- `elab-futu-research` 1.1.1 已完成，分支 `fix/v1.1.1-install-backup-and-docs`。
- 修复 1（install.sh 备份目录污染）：备份改到 `~/.elab-futu-research-backups/<agent>-<ts>/`，
  不再落在 skills 目录内；最多保留 3 份，自动清理旧备份；bash 3.2 兼容（无 mapfile）。
- 修复 2（README 粉丝说明）：新增"环境要求"（macOS/Linux/Windows bash/Python 3.9+/无依赖）、
  "账号安全 FAQ"（不登录/不读 Cookie/保守限速/--since 建议/遇验证码行为）、
  "产出物使用边界"（自用可以/完整归档不公开分发/分享脱敏/不构成投资建议）。
- 修复 3（样例报告）：`docs/sample-report.md` 全虚构数据，展示能力矩阵/市场状态分析/
  规则卡/证据分级/失败清单/完整性说明各一节；顶部标注"虚构数据演示"。
- README 末节"产出物使用边界"添加 docs/sample-report.md 链接。
- 版本号已更新：SKILL.md / futu_research.py VERSION / CHANGELOG.md / CURRENT.md。

## 下一步

- v1.2.0 待办（盲评 P2 两条）：① `_repost_original_obj` 对"非空 dict 但 richTextItems/pictureItems 均空"的边界加守卫，防真原创被误判转发；② tripwire 改用 `posts_with_images` 计数做守卫，消除纯文字博主的审计误报。
- 将分支 `fix/v1.1.1-install-backup-and-docs` PR 合并到 main 并发布。

## 基线验证

```bash
python3 -m compileall -q elab-futu-research tests
bash -n install.sh
python3 -m unittest discover -s tests -v
python3 elab-futu-research/scripts/futu_research.py doctor
```
