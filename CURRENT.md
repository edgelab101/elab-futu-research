# Current

## 做到哪了

- `elab-futu-research` 1.0.0 的 Skill、标准库脚本、方法论、安装器和虚构测试夹具已完成。
- 离线端到端测试、Codex/Claude 双目录安装测试、接口结构探测和隐私关键词扫描已通过。
- 仓库只包含通用公开方法与虚构数据，不含创建者的 UID、帖子、持仓、Cookie 或研究结果。
- 用户已确认公开范围，1.0.0 发布到 `edgelab101/elab-futu-research`。

## 下一步

- 按基线命令持续运行离线测试；后续接口漂移或规则改动通过 PR 发布。

## 基线验证

```bash
python3 -m compileall -q elab-futu-research tests
bash -n install.sh
python3 -m unittest discover -s tests -v
python3 elab-futu-research/scripts/futu_research.py doctor
```
