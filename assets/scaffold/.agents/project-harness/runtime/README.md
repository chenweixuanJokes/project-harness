# runtime/（PH 最小自有运行时）

本目录是 Project Harness 自研 SDD 流程的最小运行时资产，不绑定 GitHub Spec Kit。

## 内容

- `templates/sdd/`：八份产物骨架模板（requirement、change、design、review、tasks、verify-plan、acceptance、verification）。模板只是书写参考，不是执行规则；`ph_sdd.py` 不会复制它们。
- 旧 Spec Kit 的 `scripts/`、`templates/`、`integration.json`、`init-options.json` 已随绑定移除。

## 机器端约定

- 规格目录：`.agents/project-harness/specs/<id>/`，功能元数据为目录内 `ph-feature.json`。
- CLI：`python3 .agents/scripts/ph_sdd.py --help`，子命令 `create / adopt / mark / check / status / archive`，全部显式传 `--repo` 与 `--feature`。
- 产物流程：full 用 requirement+design+review，small 用 change 替代 requirement/design/review，其余产物共用。
- 旧指针 `runtime/feature.json`（`feature_directory` 键）只兼容读取，本运行时不写入。
