# ph-init 中文对照

仅当用户明确点名 ph-init 并要求使用时执行；普通描述、名称提及和下一步建议不触发。明确启动后的继续不要求重复点名。不自动调用其他技能；已请求升级时读取 ph-merge-update 作为内部步骤是明确例外。不要与宿主 /init、git init、git pull、worktree 或功能实现混淆。

# 安装与维护 Project Harness

PH 的项目约束和技能位于 `.agents/`，根 AGENTS.md 是通用入口；声明的 Claude 适配层提供 CLAUDE.md 和 `.claude/skills/`。原生读 canonical 的客户端不需额外副本。沿用项目锁定 portable/symlink 模式，本操作不转换模式。

开发技能为 PH 自有：ph-require、ph-clarify、ph-design、ph-design-review、ph-tasks、ph-verify-plan、ph-small-change、ph-implement、ph-verify、ph-archive。安装执行均不依赖上游 Spec Kit。发行还包括安装升级、独立 worktree 进入退出、记忆和伴读工具。必需名单以 release.json 为准，不另写独立数量常量。

## 来源与准备

唯一官方源为 `https://github.com/chenweixuanJokes/project-harness.git`。历史 `https://github.com/chenweixuanJokes/ph-init.git` 重定向至同仓，在 1.x 回执中仍是兼容身份，不改写有效历史来源。稳定版本使用 vMAJOR.MINOR.PATCH；latest 取数值最大稳定标签并固定 commit。当前包 1.2.3，不拿本地开发树或 main 冒充最新发行。

安装/升级先在目标仓外准备：

```text
python3 <ph-init-root>/scripts/ph_release.py prepare --version latest --repo <target>
```

读取 root/version/tag/commit/source，再读该 root 的 SKILL.md。后续固定同一版本/commit及其脚本。网络失败、缺标签、元数据不一致则停止，不回退旧资产。离线包只能安装其确定版本，不声称最新。

旧入口可能拒绝新契约：1.1.7 及以前要求 schema_version，Spec Kit 时代验证器要求现已退役的上游契约。不改旧验证器绕过、不原样重试、不声称项目已升级。本次过渡应从正式已发布 v1.2.3 标签取得仓外新安全目录，用其自带 ph_release.py prepare 固定版本并读返回根。标签尚未发布则如实报告不可用；本地候选测试不是公网安装。早期历史过渡保留在原迁移说明。

准备只获取和校验发行，不点星或创建账号副本。独立 support 命令仅在用户明确授权相应账户操作后使用，不能为完成安装或复现历史默认行为而执行。测试旧下载器时隔离其 support 钩子，不能改变真实账号。未登录不阻断安装，不索取登录，不把账号副本当官方源。

在本次维护范围内从准备根执行一次用户入口刷新：

```text
python3 <release-root>/scripts/ph_release.py user-entry
```

只刷新可识别的旧入口，有备份/回滚。不存在、非目录、版本未知或不旧时可跳过，如实报告，不新建全局入口、不降级。用户入口刷新不等于项目升级。

## 按目标状态分流

- 无清单：先盘点旧内容，再安装/adopt。
- 已装旧版：读取准备根 `assets/scaffold/.agents/skills/ph-merge-update/SKILL.md`，同次操作内执行。这是请求升级的内部步骤，不是新自动技能。禁止对已装旧项目 init --apply/adopt。
- 同版：按请求检查、同步适配或续补文档，不重装、不顺便升级。
- 项目比包新：停止，不降级。
- 仅 check/sync：使用项目已装内核离线执行，不 prepare、不获取、不改项目事实或升级。

```text
python3 <release-root>/scripts/ph_init.py init --repo <target> [--mode auto|portable|symlink] [--adopt-plan <plan.json>] [--apply]
python3 <installed-ph-init>/scripts/ph_init.py check --repo <target> [--mode portable|symlink]
python3 <installed-ph-init>/scripts/ph_init.py sync --repo <target> [--mode portable|symlink] [--apply]
```

默认预检。sync 只修声明适配层漂移，不改 canonical、不补装升级技能。新装 auto 在 apply 探测链接能力，适用时回退 portable；明确 symlink 失败则停止，不暗改模式。portable 是正式支持。拒绝硬链、junction、不安全嵌套链接、仓外路径及镜像未托管附加文件。

## 安装或接入存量内容

从同一发行根读取[接入规范](references/接入规范.md)、[补全规范](references/补全规范.md)、[项目化验收](references/项目化验收.md)，不修改准备好的发行包。

1. 盘点 Git、入口、模块、代码、配置、锁文件、测试、CI和已有约束文档，保护用户改动。优先复用权威正文或引用，不制造第二份事实。
2. 预检并分类计划、跳过、冲突、阻断。需要决定时先读提问规则。根 AGENTS 有而 canonical 无、受跟踪 worktree、不安全路径仍阻断，不搬开障碍强装。
3. 存量未初始化项目在仓外准备合并候选和来源哈希，不先装模板再覆盖旧正文。实际写入范围缺授权时通过正确通道取得。
4. adopt JSON 包含 version=1、绝对 repo、release_version、仓内相对路径到 SHA256/null 的 sources、UTF-8候选 files。sources 包括 `.agents/AGENTS.md`、`AGENTS.md`、`CLAUDE.md` 三个入口及全部候选目标。落点限 canonical、docs、PH constraints/documents，不含秘密。哈希防错仓/漂移，不证明语义完整，需代理独立审阅。
5. 同候选同发行根先预检再 apply，安装自包含技能/运行时、项目内 ph-init 及声明适配，不加其他厂商镜像。安装失败如实处理；成功后跑已装 check。
6. 基于实际代码和真实技术版本补全文档。可委派独立调查，主会话保留文件归属协调和最终语义审查。外部搜索只发通用技术问题，不发私有项目。无子代理能力则说明并串行。
7. 授权迁移前保全原件，将仍有效规则、事实、需求、记忆迁到适合分区，修引用索引后退役旧活动入口。归档不等于有效内容迁移完成。未知事实、未执行命令和未采纳建议分别标注。
8. 维护 `.agents/init-report.md` 和内容证据报告，每篇受管文档单独登记。使用随包 ph_governance.py 物化宪法并刷新逐文件导航，保留原则。执行 verify-content 和普通 check，脚本成功不替代语义审查。

## 项目内容与完成

现行规则 constraints、项目事实 documents、活动需求 specs、参考记忆 memory、历史原件 archive、运行资产 runtime。长规则不放 AGENTS.md。保留既有有效决定，不造 ADR、访谈、记忆或测试结果填模板。

伴读只解释真实产物，ph_human.py 管映射哈希，写作规范管正文，不证明用户验收。worktree 进入退出独立点名；功能归档不合并或删除工作区。

分别报告安装检查与文档补全，列已核验/复用/不适用/待核实/冲突。空模板、有效内容未承接、未决冲突不能报完成。中断按磁盘及报告恢复，不重装。不能为完成安装自动提交、推送、发布、部署或通知。
