#!/usr/bin/env python3
"""Contract tests for the PH 1.1.14 unified WIP confirmation.

The unified confirmation applies wherever uncommitted changes actually block
a worktree operation: ph-worktree-enter's source tree, ph-worktree-exit's
task tree and the merge-target source tree. The question asks whether to
adopt a ``wip:`` commit as the way out of the current blocker - it is not a
per-file content approval. The skill layer - never the runtime script - must
perform a read-only listing (directory, branch, full staged/unstaged/untracked
list, proposed ``wip:`` message, safety screening result) and then actually
invoke the question tool with the fixed template offering exactly
"确认 WIP 并继续" / "停止，保留现场"; refusal, cancellation or no answer
keeps every change and stops.

The confirmed commit itself is executed by the runtime script's unified
``wip`` subcommand (``wip --repo ... --message ...`` with a read-only dry-run
and an explicit ``--apply``); the agent never hand-assembles the commit, and
the script cannot prove that a real user confirmed anything. Ordinary content
drift before the commit runs does not re-ask - the authorization is not bound
to a snapshot of the listing - but it is not long-term either: once the commit
runs the authorization is consumed, and every new blocking instance is
confirmed against the situation at hand.

The same item also covers merge-conflict recovery: once a real merge conflict
exists (``MERGE_HEAD`` plus unmerged entries), the exit skill asks the shared
fixed conflict question (directory, task branch, source branch, list as the
only variables) with exactly "保留现场，我解决后继续" / "撤销这次合并"; no
stash / discard / ours / theirs / agent auto-resolve presets, keep means stop
and wait, abort is a single-use authorization granted by that option, and
``continue`` runs only after the user explicitly says the conflicts are
resolved, staged and to continue. Both ``continue`` and ``abort-merge`` verify
the merge identity against the session first; sessions that lack the new
evidence (old releases) are conservatively blocked and guided through the
read-only ``doctor`` and the explicit ``recover`` instead of guessed.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = ROOT / "assets" / "scaffold"
ENGINEERING = SCAFFOLD / "docs" / "约束规范" / "工程规范"

ENTER_SKILL = SCAFFOLD / ".agents/skills/ph-worktree-enter/SKILL.md"
EXIT_SKILL = SCAFFOLD / ".agents/skills/ph-worktree-exit/SKILL.md"
PARALLEL_SPEC = ENGINEERING / "Git与并行开发.md"
CANONICAL_AGENTS = SCAFFOLD / ".agents/AGENTS.md"
ENTER_SCRIPT = SCAFFOLD / ".agents/skills/ph-worktree-enter/scripts/ph_worktree.py"
EXIT_SCRIPT = SCAFFOLD / ".agents/skills/ph-worktree-exit/scripts/ph_worktree.py"

CONFIRM_OPTION = "确认 WIP 并继续"
STOP_OPTION = "停止，保留现场"
KEEP_CONFLICT_OPTION = "保留现场，我解决后继续"
ABORT_CONFLICT_OPTION = "撤销这次合并"


class UnifiedConfirmationContractTests(unittest.TestCase):
    """The shared confirmation flow stated identically at all blocked sites."""

    def setUp(self):
        self.enter = ENTER_SKILL.read_text(encoding="utf-8")
        self.exit = EXIT_SKILL.read_text(encoding="utf-8")
        self.spec = PARALLEL_SPEC.read_text(encoding="utf-8")
        self.agents = CANONICAL_AGENTS.read_text(encoding="utf-8")

    def test_enter_stops_creation_and_runs_the_unified_confirmation(self):
        # creation is stopped first, then the unified confirmation runs
        self.assertIn("停止创建", self.enter)
        self.assertIn("统一 WIP 确认", self.enter)
        # read-only listing before asking: directory, branch, full list, proposal
        for term in ("只读检查", "源工作区目录", "当前分支", "完整清单", "拟用的 `wip: <说明>` 提交信息"):
            self.assertIn(term, self.enter)

    def test_exit_uses_the_same_confirmation_for_all_three_sites(self):
        self.assertIn("统一 WIP 确认（enter 源树、本任务树、合并目标源树同一套）", self.exit)
        for term in ("只读检查", "当前分支", "完整清单", "拟用的 `wip: <说明>` 提交信息"):
            self.assertIn(term, self.exit)

    def test_question_asks_whether_to_adopt_wip_not_content_approval(self):
        # the listing explains the situation and the safety screening; the
        # decision is about adopting the WIP way out of this blocker
        for text, label in ((self.enter, "enter"), (self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("是否采用 `wip:` 提交解决当前这次阻断", text)
                self.assertIn("不是对文件内容的逐项审批", text)
                self.assertIn("说明现场", text)

    def test_fixed_question_template_and_two_fixed_options(self):
        for text, label in ((self.enter, "enter"), (self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("固定问句模板", text)
                self.assertIn(CONFIRM_OPTION, text)
                self.assertIn(STOP_OPTION, text)
                # no extra preset options; host free-input stays available
                self.assertIn("不添加其他预设选项", text)
                self.assertIn("自由输入", text)

    def test_actual_question_tool_call_with_degradation_only_when_unavailable(self):
        for text, label in ((self.enter, "enter"), (self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("实际调用问答工具", text)
                self.assertIn("没有可用问答工具或工具故障时", text)
                self.assertIn("降级规则", text)
                # the old open-ended ask is banned as the default question
                self.assertNotIn("这次提交要包括哪些", text)
        # the no-open-ended ban is spelled out in enter and the spec; the exit
        # skill states it as "no extra preset options" plus the free-input rule
        self.assertIn("不开放式问", self.enter)
        self.assertIn("不开放式问", self.spec)

    def test_ordinary_content_drift_before_the_commit_does_not_re_ask(self):
        # the authorization targets adopting WIP for this blocker, not a
        # snapshot of the listing; ordinary drift before the commit runs is
        # never bound to a listing hash
        for text, label in ((self.enter, "enter"), (self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("普通内容变化不需要重新确认", text)
                self.assertIn("不与提问时的清单逐字绑定", text)

    def test_authorization_is_not_long_term(self):
        # the commit consumes the authorization; every new blocking instance
        # (later steps, the next delivery, the tree going dirty again) is
        # confirmed against the situation at hand
        for text, label in ((self.enter, "enter"), (self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("授权不是长期授权", text)
                self.assertIn("该提交一经执行授权即消费", text)
                self.assertIn("该阻断场景结束后再次被未提交改动阻断", text)
                self.assertIn("按当时的现场重新确认", text)

    def test_refusal_cancel_or_no_answer_keeps_every_change_and_stops(self):
        # the two skills spell out the full stop semantics; the spec keeps the
        # compact rule plus the fixed-template degradation sentence
        for text, label in ((self.enter, "enter"), (self.exit, "exit")):
            with self.subTest(file=label):
                self.assertIn("用户拒绝、取消或未回答时保留全部改动并停止", text)
                self.assertIn("不 stash", text)
                self.assertIn("不换问法重问", text)
        self.assertIn("拒绝、取消或未回答", self.spec)
        self.assertIn("同意才提交，拒绝、取消或未回答停止", self.spec)

    def test_authorization_covers_only_this_wip_commit(self):
        for text, label in ((self.enter, "enter"), (self.exit, "exit")):
            with self.subTest(file=label):
                self.assertIn("WIP 确认只覆盖这次 `wip:` 提交", text)
                self.assertIn("不授权普通提交、清理或任何安全检查豁免", text)
        self.assertIn("确认只覆盖这次 `wip:` 提交", self.spec)
        self.assertIn("不授权普通提交、清理或安全检查豁免", self.spec)
        # per-instance authorization: doing a worktree is not a WIP grant
        self.assertIn("必须取得**本次**提交授权", self.spec)
        self.assertIn("用户同意“做 worktree”不等于同意把未跟踪文件或密钥收进提交", self.spec)

    def test_safety_screening_and_no_blind_staging(self):
        for text, label in ((self.enter, "enter"), (self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("不盲目 `git add -A`", text)
                self.assertIn("疑似密钥", text)
                self.assertIn("异常大文件", text)
                self.assertIn("ignored", text)
                self.assertIn("未解决的冲突", text)

    def test_blockers_refuse_the_whole_wip_no_partial_commit(self):
        # the unified wip execution takes staged, unstaged and untracked
        # together, excludes ignored, and refuses the whole order instead of
        # partially committing around sensitive / oversized / conflicting files
        for text, label in ((self.enter, "enter"), (self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("staged、unstaged、untracked 一起收进", text)
                self.assertIn("ignored 排除", text)
                self.assertIn("不部分提交", text)
                self.assertIn("不得把", text)
                self.assertIn("当作干净继续", text)

    def test_canonical_agents_rule_index_carries_the_gate(self):
        self.assertIn("停止推进并执行统一 WIP 确认", self.agents)
        self.assertIn(CONFIRM_OPTION, self.agents)
        self.assertIn(STOP_OPTION, self.agents)
        self.assertIn("不得自动收纳未知文件", self.agents)
        # the compact rule keeps the corrected semantics
        self.assertIn("不是对文件内容的逐项审批", self.agents)
        self.assertIn("授权不是长期授权", self.agents)


class UnifiedWipCommandContractTests(unittest.TestCase):
    """The confirmed commit runs through the script's unified wip subcommand."""

    def setUp(self):
        self.enter = ENTER_SKILL.read_text(encoding="utf-8")
        self.exit = EXIT_SKILL.read_text(encoding="utf-8")
        self.spec = PARALLEL_SPEC.read_text(encoding="utf-8")

    def test_dry_run_read_only_then_explicit_apply_after_confirmation(self):
        for text, label in ((self.enter, "enter"), (self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("wip --repo", text)
                self.assertIn("只读 dry-run", text)
                self.assertIn("显式加 `--apply`", text)

    def test_agent_never_hand_assembles_the_wip_commit(self):
        for text, label in ((self.enter, "enter"), (self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("不由 Agent 手写", text)
        self.assertIn("脚本只见 clean 工作区", self.exit)
        self.assertIn("脚本只见 clean 工作区", self.spec)

    def test_script_cannot_prove_user_confirmation(self):
        for text, label in ((self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("脚本无能力证明真实用户确认", text)
                self.assertIn("人类确认由", text)
                self.assertIn("调用 `--apply` 前完成", text)

    def test_exit_never_commits_from_the_old_message_param(self):
        # exit no longer takes a commit message; legacy callers are accepted
        # but never committed from
        self.assertIn("绝不据此提交", self.exit)
        self.assertIn("绝不据此提交", self.spec)

    def test_exit_opening_authorization_sentence_revised(self):
        self.assertIn("调用本技能表示用户授权完成必要的验证与合并", self.exit)
        self.assertIn("调用本技能本身不构成任何提交确认", self.exit)
        self.assertIn("清理 linked worktree 必须在合并完成后另行确认", self.exit)

    def test_no_default_normal_commit_by_classification(self):
        self.assertIn("不再按分级默认普通提交", self.exit)
        self.assertIn("不再按分级默认普通提交", self.spec)
        # any dirty state (including the formerly auto-committed single classes)
        # goes through the unified confirmation before the script sees clean
        self.assertIn("只有 staged、只有 tracked unstaged、两者并存、含 untracked", self.spec)

    def test_merge_target_source_dirty_wip_is_committed_in_the_source_tree(self):
        self.assertIn("源工作区不干净时", self.exit)
        self.assertIn("把 `wip: <说明>` 提交做在源工作区", self.exit)
        self.assertIn("WIP 提交做在源工作区", self.spec)

    def test_exit_call_itself_is_not_a_commit_authorization(self):
        self.assertIn("仅调用本技能不构成 WIP 或任何提交确认", self.exit)
        self.assertIn("调用退出技能不构成 WIP 或提交确认", self.spec)

    def test_explicitly_specified_formal_commits_are_still_honored(self):
        self.assertIn("用户已在本次会话单独明确指定任务树改动的正式提交", self.exit)
        self.assertIn("可按指定执行该提交", self.exit)
        self.assertIn("用户已在本次会话单独明确指定正式提交", self.spec)

    def test_existing_protections_are_kept(self):
        self.assertIn("ignored 文件永不加入", self.exit)
        self.assertIn("禁止 `git stash`、`reset --hard`、`--no-verify`", self.exit)
        self.assertIn("保留项目 hooks、签名和 Git author 配置", self.exit)
        self.assertIn("ignored 文件一律阻断清理", self.spec)
        # cleanup consent stays a separate question from the WIP confirmation
        self.assertIn("“能不能删这个目录”仍单独问", self.spec)


class RuntimeRecoveryContractTests(unittest.TestCase):
    """Doctor / recover / redeliver and enter source expectations are documented."""

    def setUp(self):
        self.enter = ENTER_SKILL.read_text(encoding="utf-8")
        self.exit = EXIT_SKILL.read_text(encoding="utf-8")
        self.spec = PARALLEL_SPEC.read_text(encoding="utf-8")

    def test_doctor_is_read_only_diagnosis(self):
        for text, label in ((self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("doctor", text)
                self.assertIn("只读诊断", text)

    def test_recover_needs_explicit_target_and_operations(self):
        for text, label in ((self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("recover", text)
                self.assertIn("显式指定", text)
                self.assertIn("不猜测", text)
        # the two confirmed recover actions and their preconditions
        self.assertIn("archive", self.exit)
        self.assertIn("adopt", self.exit)
        self.assertIn("initialTaskHead", self.exit)

    def test_redeliver_verifies_before_delivering_again(self):
        for text, label in ((self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("redeliver", text)
                self.assertIn("先核验再交付", text)
        # redeliver only applies to those interrupted delivery states
        self.assertIn("merge_verify_failed", self.exit)

    def test_enter_expect_source_flags_stop_on_mismatch(self):
        self.assertIn("--expect-source-head", self.enter)
        self.assertIn("--expect-source-branch", self.enter)
        self.assertIn("与实际不符时停止", self.enter)

    def test_merge_identity_verified_before_continue_and_abort(self):
        for text, label in ((self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("核对 merge 身份", text)
                self.assertIn("abort-merge", text)
        # the merge snapshot fields the identity check is based on
        self.assertIn("mergeSourceBranch", self.exit)
        self.assertIn("mergeSourceHead", self.exit)
        self.assertIn("mergeTaskHead", self.exit)

    def test_old_sessions_without_new_evidence_block_conservatively(self):
        for text, label in ((self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("缺少新增证据", text)
                self.assertIn("保守阻断", text)
                self.assertIn("不猜测补齐", text)
        # no invented recovery promise for old merges
        self.assertIn("recover 不能恢复所有旧 merge", self.exit)

    def test_sessions_are_backward_compatible_and_migration_keeps_them(self):
        self.assertIn("新增字段非必填", self.spec)
        self.assertIn("不覆盖现有 session", self.spec)


class RuntimeBoundaryTests(unittest.TestCase):
    """Questions stay in the skill layer; the script never asks the user."""

    def test_scripts_never_ask_the_wip_question(self):
        for path in (ENTER_SCRIPT, EXIT_SCRIPT):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(CONFIRM_OPTION, text, path)
            self.assertNotIn(STOP_OPTION, text, path)
            self.assertNotIn(KEEP_CONFLICT_OPTION, text, path)
            self.assertNotIn(ABORT_CONFLICT_OPTION, text, path)

    def test_both_skill_dirs_ship_the_same_script(self):
        self.assertEqual(
            ENTER_SCRIPT.read_text(encoding="utf-8"),
            EXIT_SCRIPT.read_text(encoding="utf-8"),
            "the two skill dirs ship the same script",
        )


class ConflictRecoveryContractTests(unittest.TestCase):
    """Merge conflicts keep Git's merge state and ask the shared fixed question."""

    def setUp(self):
        self.exit = EXIT_SKILL.read_text(encoding="utf-8")
        self.spec = PARALLEL_SPEC.read_text(encoding="utf-8")
        self.agents = CANONICAL_AGENTS.read_text(encoding="utf-8")

    def test_fixed_conflict_template_with_two_fixed_options(self):
        # the template text lives verbatim in the shared spec; the exit skill
        # references it and fixes the same two option wordings
        self.assertIn("任务分支<任务分支>合入源分支<源分支>时发生冲突", self.spec)
        self.assertIn("保留现场由你解决后继续，还是撤销这次合并", self.spec)
        self.assertIn("撤销会取消本次合并中的冲突处理，任务分支提交和隔离目录仍保留", self.spec)
        for text, label in ((self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn(KEEP_CONFLICT_OPTION, text)
                self.assertIn(ABORT_CONFLICT_OPTION, text)
                # no preset stash / discard / ours / theirs / agent auto-resolve
                self.assertIn("其他预设选项", text)
                self.assertIn("自由输入", text)
                for banned in ("stash", "ours/theirs", "Agent 代解决"):
                    self.assertIn(banned, text)

    def test_real_conflict_verified_before_asking(self):
        for text, label in ((self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("MERGE_HEAD", text)
                self.assertIn("未合并条目", text)
                self.assertIn("冲突清单", text)
                self.assertIn("实际调用问答工具", text)
                self.assertIn("没有可用问答工具或工具故障时", text)

    def test_keep_option_stops_and_waits_without_polling(self):
        for text, label in ((self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("停止等待", text)
                self.assertIn("不立即 continue", text)
                self.assertIn("不轮询", text)

    def test_continue_needs_explicit_resolved_and_staged_continue(self):
        for text, label in ((self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("已解决并暂存，请继续", text)
                self.assertIn("只读核验", text)
                self.assertIn("无未合并条目", text)
                self.assertIn("merge 状态吻合", text)
                self.assertIn("不重问", text)
                self.assertIn("不是继续授权", text)

    def test_abort_is_a_single_use_authorization_with_prior_warning(self):
        for text, label in ((self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("撤销", text)
                self.assertIn("编辑会被撤销", text)
                self.assertIn("仅本次", text)
        self.assertIn("不自动重试 exit", self.exit)
        self.assertIn("不删除任务分支或隔离目录", self.exit)

    def test_cancel_skip_or_unanswered_neither_aborts_nor_wips(self):
        for text, label in ((self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("取消、跳过或未回答", text)
                self.assertIn("不 abort", text)
                self.assertIn("不做 WIP", text)
                self.assertIn("不换问法重问", text)

    def test_agent_delegation_is_separate_authorization(self):
        self.assertIn("委托 Agent 解决冲突", self.exit)
        self.assertIn("单独授权", self.exit)
        self.assertIn("业务取舍", self.exit)

    def test_new_conflict_never_reuses_old_authorization(self):
        self.assertIn("新一次 merge 冲突", self.exit)
        self.assertIn("不复用旧授权", self.exit)

    def test_conflict_state_takes_priority_over_wip_flow(self):
        for text, label in ((self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("优先于", text)
                self.assertIn("不是 WIP", text)
                self.assertIn("另行确认", text)

    def test_canonical_agents_rule_index_carries_the_conflict_gate(self):
        self.assertIn("固定冲突问句", self.agents)
        self.assertIn(KEEP_CONFLICT_OPTION, self.agents)
        self.assertIn(ABORT_CONFLICT_OPTION, self.agents)
        self.assertIn("已解决并暂存，请继续", self.agents)
        self.assertIn("不是 WIP", self.agents)
        # the compact rule keeps the merge-identity and old-session guidance
        self.assertIn("核对 merge 身份", self.agents)
        self.assertIn("doctor", self.agents)


class EvalsCoverageTests(unittest.TestCase):
    """Shipped evals sample the unified confirmation's behaviors."""

    def setUp(self):
        self.enter = json.loads(
            (SCAFFOLD / ".agents/skills/ph-worktree-enter/evals/evals.json").read_text(encoding="utf-8")
        )
        self.exit = json.loads(
            (SCAFFOLD / ".agents/skills/ph-worktree-exit/evals/evals.json").read_text(encoding="utf-8")
        )

    @staticmethod
    def texts(payload):
        return [e["prompt"] + "\n" + e["expected_output"] for e in payload["evals"]]

    def test_fixed_options_sampled_in_both_skills(self):
        for payload, label in ((self.enter, "enter"), (self.exit, "exit")):
            with self.subTest(skill=label):
                self.assertTrue(
                    any(CONFIRM_OPTION in t and STOP_OPTION in t for t in self.texts(payload)),
                    f"{label} evals never sample the two fixed options",
                )

    def test_enter_covers_dirty_source_stop_and_safety_blocks(self):
        joined = "\n".join(self.texts(self.enter))
        self.assertIn("停止创建", joined)
        self.assertIn("不盲目 git add -A", joined)
        self.assertIn("server.key", joined)  # secret-file sample stays blocked
        self.assertIn("异常大文件", joined)

    def test_exit_covers_single_class_wip_unanswered_and_secrets(self):
        joined = "\n".join(self.texts(self.exit))
        self.assertIn("不再默认普通提交", joined)  # formerly-normal single class now asks
        self.assertIn("做在源工作区", joined)  # merge-target source tree case
        self.assertIn("没有回答", joined)  # unanswered counts as unconfirmed
        self.assertIn("id_rsa", joined)  # secret sample stays blocked

    def test_confirmed_scope_tolerates_ordinary_drift(self):
        # an already-confirmed, not-yet-executed wip does not re-ask when the
        # user edits files in the meantime - the confirmation is about the
        # approach, not the listing snapshot
        for payload, label in ((self.enter, "enter"), (self.exit, "exit")):
            with self.subTest(skill=label):
                self.assertTrue(
                    any("不需要重新确认" in t and "不与提问时的清单逐字绑定" in t
                        for t in self.texts(payload)),
                    f"{label} evals never sample the ordinary-drift no-re-ask",
                )

    def test_new_blocker_requires_a_fresh_confirmation(self):
        # a consumed wip authorization does not carry over: the next blocking
        # instance is confirmed against the situation at hand
        for payload, label in ((self.enter, "enter"), (self.exit, "exit")):
            with self.subTest(skill=label):
                self.assertTrue(
                    any("授权不是长期授权" in t and "重新" in t for t in self.texts(payload)),
                    f"{label} evals never sample the non-long-term authorization",
                )

    def test_exit_evals_cover_recovery_scenarios(self):
        joined = "\n".join(self.texts(self.exit))
        for term in (
            "先核验再交付",  # redeliver verifies before delivering again
            "只读诊断",  # doctor stays read-only
            "显式指定",  # recover needs explicit target and operations
            "保守阻断",  # unfamiliar merge / missing evidence blocks
            "merge 身份",  # identity checked before continue / abort
        ):
            self.assertIn(term, joined)

    def test_exit_evals_cover_conflict_recovery_scenarios(self):
        joined = "\n".join(self.texts(self.exit))
        for term in (
            "MERGE_HEAD",
            KEEP_CONFLICT_OPTION,
            ABORT_CONFLICT_OPTION,
            "实际调用问答工具提出固定冲突问句",
            "已解决并暂存，请继续",
            "不轮询",
            "不 abort",
            "不是 WIP",
            "未合并条目",
            "冲突清单",
        ):
            self.assertIn(term, joined)

    def test_unanswered_and_refusal_never_proceed(self):
        for payload, label in ((self.enter, "enter"), (self.exit, "exit")):
            with self.subTest(skill=label):
                self.assertTrue(
                    any("未回答" in t and ("暂停" in t or "停止" in t) for t in self.texts(payload)),
                    f"{label} evals never sample the unanswered stop",
                )
                self.assertTrue(
                    any("拒绝" in t and ("停止" in t or "暂停" in t) for t in self.texts(payload)),
                    f"{label} evals never sample the refusal stop",
                )


if __name__ == "__main__":
    unittest.main()
