# ph-human 中文对照

仅当用户明确点名 ph-human 并要求使用时执行；普通描述、名称提及和下一步建议不触发。明确启动后的继续不要求重复点名，不自动调用其他技能。伴读是解释快照，不是权威需求或验收证据。

# 维护人读伴读

以[伴读写作规范](references/human-writing.zh.md)为写作依据。开发技能发布本次变更产物时可以直接读此规范，不等于调用本技能。

## 执行步骤

1. 确定指定功能或全部范围，优先明确路径。用户要求全部或未限定时用 `--all`，不在并行工作区默选全局活动指针。
2. 只读盘点：

   ```text
   python3 .agents/scripts/ph_human.py status --repo <root> (--feature <feature-directory> | --all)
   ```

   按来源哈希和元数据解读 fresh、stale、orphan、user_modified、snapshot、unreadable、missing。哈希新鲜只证明来源对齐，不证明解释准确。
3. 只刷新用户要求的范围。仅检查请求保持只读。user_modified/unreadable 只报告、不覆盖；真正未决且影响写入范围时才问。没有当前来源的旧 analysis/issues 快照是历史，不编新报告、不复活退役技能。
4. 完整读取来源，在仓外临时文件撰写正文，然后发布：

   ```text
   python3 .agents/scripts/ph_human.py publish --repo <root> --source <source-relative-path> --candidate <temporary-body> --skill ph-human
   ```

   映射、来源/正文哈希、页脚和安全写入由脚本处理。候选不写机器元数据，不绕过冲突，不把伴读再作为来源。
5. 再跑 status，分别报告已刷新、仍陈旧、受保护用户改动及缺源项。

## 边界

只写伴读，不改需求、设计、任务、验证、宪法或验收状态，不调用其他技能、不做 Git/外部操作。伴读解释来源说了什么，不能替代用户验收、测试证据或现行规则。伴读缺失或过期不使权威来源本身失效。
