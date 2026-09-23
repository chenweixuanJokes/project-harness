#!/usr/bin/env python3
"""Contract tests for the PH unified WIP confirmation.

The unified confirmation applies wherever uncommitted changes actually block
a worktree operation: ph-worktree-enter's source tree, ph-worktree-exit's
task tree and the merge-target source tree. The question asks whether to
adopt a ``wip:`` commit as the way out of the current blocker - it is not a
per-file content approval. The skill layer - never the runtime script - must
perform a read-only dry-run listing (directory, branch, full
staged/unstaged/untracked list, proposed ``wip:`` message, safety screening
result) and then actually invoke the question tool with the fixed template
offering exactly the literal options 是 / 否; refusal, cancellation or no
answer keeps every change and stops.

Since the shipped skills were rewritten they delegate the fixed question and
conflict wording to the Git rules doc (Git规范.md) and pin the flow in
English; the spec text still carries the verbatim templates and the contract
tests anchor both layers. Answering 是 authorizes ONE combined invocation:
enter's confirmed WIP commit and the worktree creation, and exit's task-tree
WIP commit and the delivery, each happen inside a single ``enter --apply`` /
``exit --apply`` carrying the reviewed dry-run snapshot bindings
(--wip-message plus the --expect-* flags); the skill flow is never split into
a wip call followed by the enter/exit call (the independent wip subcommand
stays available for the user's direct use). The agent never hand-assembles
the commit, and the script cannot prove that a real user confirmed anything.
Ordinary content drift before the commit runs does not re-ask - the
authorization is not bound to a byte snapshot - but it is not long-term
either: once the commit runs the authorization is consumed, and every new
blocking instance is confirmed against the situation at hand.

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
ENGINEERING = SCAFFOLD / ".agents" / "project-harness" / "constraints" / "工程规范"

ENTER_SKILL = SCAFFOLD / ".agents/skills/ph-worktree-enter/SKILL.md"
EXIT_SKILL = SCAFFOLD / ".agents/skills/ph-worktree-exit/SKILL.md"
PARALLEL_SPEC = ENGINEERING / "Git规范.md"
CANONICAL_AGENTS = SCAFFOLD / ".agents/AGENTS.md"
ENTER_SCRIPT = SCAFFOLD / ".agents/scripts/ph_worktree.py"
EXIT_SCRIPT = ENTER_SCRIPT

CONFIRM_OPTION = "是"
STOP_OPTION = "否"
SPEC_OPTION_SENTENCE = "两个选项文案固定为字面“是”“否”"
OLD_CONFIRM_OPTION = "确认 WIP 并继续"
OLD_STOP_OPTION = "停止，保留现场"
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
        # creation is stopped first, then the unified confirmation runs; the
        # read-only dry-run reports the dirty sets and the screening result
        self.assertIn("stops creation", self.enter)
        self.assertIn("unified WIP question", self.enter)
        for term in ("sourceDirty, wipRisks", "dry-run and apply"):
            self.assertIn(term, self.enter)

    def test_exit_uses_the_same_confirmation_for_all_three_sites(self):
        self.assertIn("the Git rules' unified WIP question", self.exit)
        for term in (
            "read-only dry-run",
            "show branch, HEAD, all staged/unstaged/untracked paths",
            "the proposed `wip: <description>`",
        ):
            self.assertIn(term, self.exit)

    def test_question_asks_whether_to_adopt_wip_not_content_approval(self):
        # the skills delegate the fixed question wording to the Git rules; the
        # adoption-vs-content-approval boundary stays pinned by the spec while
        # both skills anchor the delegation
        for text, label in ((self.enter, "enter"), (self.exit, "exit")):
            with self.subTest(file=label):
                self.assertIn("the exact unified WIP question in the Git rules", text)
        self.assertIn("是否采用 `wip:` 提交解决当前这次阻断", self.spec)
        self.assertIn("不是对文件内容的逐项审批", self.spec)
        self.assertIn("用于说明现场与安全筛查结果", self.spec)

    def test_fixed_question_template_and_two_fixed_options(self):
        # the skills fix the yes/no choices and keep the host free-input
        # option; the spec doc words the same rule in its own sentence
        self.assertIn(
            "The fixed choices are the project's yes/no labels, with the host's free-input option retained",
            self.enter,
        )
        self.assertIn("Preserve its yes/no labels and host free input", self.exit)
        self.assertIn(SPEC_OPTION_SENTENCE, self.spec)
        # the literal options are 是 / 否 - the retired old option texts must
        # not survive anywhere
        for text, label in ((self.enter, "enter"), (self.exit, "exit"), (self.spec, "spec"), (self.agents, "agents")):
            with self.subTest(file=label):
                self.assertNotIn(OLD_CONFIRM_OPTION, text, label)
                self.assertNotIn(OLD_STOP_OPTION, text, label)
        # no extra preset options; host free input stays available in the spec
        self.assertIn("不添加其他预设选项", self.spec)
        self.assertIn("自由输入", self.spec)

    def test_actual_question_tool_call_with_degradation_only_when_unavailable(self):
        # the skills actually call the host question tool; the degradation
        # rule lives in the question-rules doc both skills reference, and the
        # spec carries it verbatim
        self.assertIn("through the host's question tool", self.enter)
        self.assertIn("using the host tool", self.exit)
        for text, label in ((self.enter, "enter"), (self.exit, "exit")):
            with self.subTest(file=label):
                self.assertIn("harness规范/对用户提问规范.md", text)
        self.assertIn("实际调用问答工具", self.spec)
        self.assertIn("没有可用问答工具或工具故障时", self.spec)
        self.assertIn("降级规则", self.spec)
        # the old open-ended ask is banned as the default question
        for text, label in ((self.enter, "enter"), (self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertNotIn("这次提交要包括哪些", text)

    def test_ordinary_content_drift_before_the_commit_does_not_re_ask(self):
        # the authorization targets adopting WIP for this blocker, not a
        # byte-level snapshot: ordinary content modification of an
        # already-shown path is not re-asked (no per-file hashing), while a
        # branch/HEAD/change-set change blocks and re-prechecks instead of
        # reusing the consumed confirmation
        self.assertIn("同一已展示路径的普通内容修改不需要重新确认", self.spec)
        self.assertIn("不逐字节比对文件内容", self.spec)
        self.assertIn("Ordinary edits within the same displayed path set do not require byte-by-byte reapproval", self.enter)
        self.assertIn("invalidate the snapshot and require fresh preflight and consent", self.enter)
        self.assertIn("same-path ordinary content edits do not trigger byte-by-byte reconfirmation", self.exit)
        self.assertIn("Branch/HEAD/path-status changes require new preflight and consent", self.exit)
        self.assertIn("不沿用", self.spec)
        self.assertIn("阻断并重新预检、重新确认", self.spec)
        self.assertIn("整单拒绝并要求重新预检", self.spec)
        self.assertIn("沿用旧确认提交新的改动范围", self.spec)

    def test_authorization_is_not_long_term(self):
        # the commit consumes the authorization; every new blocking instance
        # (later steps, the next delivery, the tree going dirty again) is
        # confirmed against the situation at hand
        self.assertIn("Consent is consumed by that one commit", self.enter)
        self.assertIn("later dirty-state blockers need their own consent", self.enter)
        self.assertIn("Consent is consumed by that commit", self.exit)
        self.assertIn("授权不是长期授权", self.spec)
        self.assertIn("该提交一经执行授权即消费", self.spec)
        self.assertIn("该阻断场景结束后再次被未提交改动阻断", self.spec)
        self.assertIn("按当时的现场重新确认", self.spec)

    def test_refusal_cancel_or_no_answer_keeps_every_change_and_stops(self):
        # the two skills spell out the full stop semantics; the spec keeps the
        # compact rule plus the fixed-template degradation sentence
        self.assertIn("Rejection, cancellation or no answer preserves changes and stops", self.enter)
        self.assertIn("do not reword the question to obtain agreement", self.enter)
        self.assertIn("Never stash", self.enter)
        self.assertIn("Rejection/cancellation/no answer preserves all content and stops without rewording the question", self.exit)
        self.assertIn("No automatic push, stash, reset --hard", self.exit)
        self.assertIn("拒绝、取消或未回答", self.spec)
        self.assertIn("同意才提交，拒绝、取消或未回答停止", self.spec)

    def test_authorization_covers_only_this_wip_commit(self):
        self.assertIn("a single enter apply combines the approved WIP and creation", self.enter)
        self.assertIn("Consent covers one WIP, not arbitrary submission", self.exit)
        self.assertIn("确认只覆盖这次 `wip:` 提交", self.spec)
        self.assertIn("不授权普通提交、清理或安全检查豁免", self.spec)
        # per-instance authorization: doing a worktree is not a WIP grant
        self.assertIn("必须取得**本次**提交授权", self.spec)
        self.assertIn("用户同意“做 worktree”不等于同意把未跟踪文件或密钥收进提交", self.spec)

    def test_safety_screening_and_no_blind_staging(self):
        self.assertIn("Suspected secrets", self.enter)
        self.assertIn("oversized files", self.enter)
        self.assertIn("unresolved conflicts", self.enter)
        self.assertIn("Ignored files are excluded", self.enter)
        self.assertIn("do not blindly git add -A", self.enter)
        self.assertIn("Secrets", self.exit)
        self.assertIn("oversized changes", self.exit)
        self.assertIn("no partial submission or blind git add -A", self.exit)
        self.assertIn("Ignored files stay excluded", self.exit)
        for term in ("不盲目 `git add -A`", "疑似密钥", "异常大文件", "ignored", "未解决的冲突"):
            self.assertIn(term, self.spec)

    def test_blockers_refuse_the_whole_wip_no_partial_commit(self):
        # the unified wip execution takes staged, unstaged and untracked
        # together, excludes ignored, and refuses the whole order instead of
        # partially committing around sensitive / oversized / conflicting files
        self.assertIn("block the whole operation, not a partial commit", self.enter)
        self.assertIn("all three path sets", self.enter)
        self.assertIn("block before committing; no partial submission", self.exit)
        self.assertIn("all staged/unstaged/untracked paths", self.exit)
        for term in ("staged、unstaged、untracked 一起收进", "ignored 排除", "不部分提交", "不得把", "当作干净继续"):
            self.assertIn(term, self.spec)

    def test_parallel_spec_carries_the_gate(self):
        # the rule index moved out of AGENTS.md: the constraint doc and the
        # skills carry the full gate wording
        self.assertIn(SPEC_OPTION_SENTENCE, self.spec)
        self.assertIn("不盲目 `git add -A`", self.spec)
        self.assertIn("不是对文件内容的逐项审批", self.spec)
        self.assertIn("授权不是长期授权", self.spec)


class UnifiedWipCommandContractTests(unittest.TestCase):
    """The confirmed commit runs through the script's unified wip subcommand."""

    def setUp(self):
        self.enter = ENTER_SKILL.read_text(encoding="utf-8")
        self.exit = EXIT_SKILL.read_text(encoding="utf-8")
        self.spec = PARALLEL_SPEC.read_text(encoding="utf-8")

    def test_dry_run_read_only_then_explicit_apply_after_confirmation(self):
        for text, label in ((self.enter, "enter"), (self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("--wip-message", text)
        self.assertIn("Dry-run and source protection", self.enter)
        self.assertIn("Run the read-only dry-run", self.exit)
        self.assertIn("先只读检查", self.spec)
        # the single apply carries the reviewed dry-run snapshot forward
        for text, label in ((self.enter, "enter"), (self.exit, "exit"), (self.spec, "spec")):
            with self.subTest(file=label):
                self.assertIn("--expect-staged", text)
                self.assertIn("--expect-unstaged", text)
                self.assertIn("--expect-untracked", text)
        # the combined-call contract: the confirmed WIP and the follow-up
        # action run inside one apply, never as wip-then-enter/exit
        self.assertIn("a single enter apply combines the approved WIP and creation", self.enter)
        self.assertIn("use a single exit apply with `--wip-message`", self.exit)
        self.assertIn("在同一个 `enter --apply` / `exit --apply` 调用内", self.spec)
        self.assertIn("Do not split into independent add/commit/enter operations", self.enter)
        self.assertIn("Do not split task WIP and exit into two invocations", self.exit)
        self.assertIn("技能流程不拆成两次调用", self.spec)
        self.assertIn("The standalone wip command is not this workflow's substitute", self.enter)
        self.assertIn("standalone wip command", self.exit)
        self.assertIn("独立 `wip` 子命令保留给用户直接使用", self.spec)
        # binding drift refuses the whole order
        self.assertIn("block the whole operation", self.enter)
        self.assertIn("no partial submission", self.exit)
        self.assertIn("整单拒绝", self.spec)

    def test_agent_never_hand_assembles_the_wip_commit(self):
        self.assertIn("not hand-written Git orchestration", self.enter)
        self.assertIn("manually git add/commit", self.exit)
        self.assertIn("不由 Agent 手写", self.spec)
        self.assertIn("受确认提交完成后脚本只见 clean 工作区", self.spec)
        # the single-apply wording per site
        self.assertIn("a single enter apply combines the approved WIP and creation", self.enter)
        self.assertIn("use a single exit apply with `--wip-message`", self.exit)

    def test_script_cannot_prove_user_confirmation(self):
        self.assertIn("The script does not itself prove human authorization", self.exit)
        self.assertIn("脚本无能力证明真实用户确认", self.spec)
        self.assertIn("人类确认由", self.spec)
        self.assertIn("调用 `--apply` 前完成", self.spec)

    def test_exit_never_commits_from_the_old_message_param(self):
        # exit no longer takes a commit message; legacy callers are accepted
        # but never committed from
        self.assertIn("绝不据此提交", self.spec)
        self.assertIn("do not silently substitute one for refused WIP", self.exit)

    def test_exit_opening_authorization_sentence_revised(self):
        self.assertIn(
            "Invocation authorizes the scoped merge, not a commit, push, branch deletion or worktree cleanup",
            self.exit,
        )
        self.assertIn("Invocation of this skill alone never confirms a commit", self.exit)
        self.assertIn("separately ask whether to remove this session's isolated directory", self.exit)
        self.assertIn("use a single exit apply with `--wip-message`", self.exit)

    def test_no_default_normal_commit_by_classification(self):
        self.assertIn("不再按分级默认普通提交", self.spec)
        # any dirty state (including the formerly auto-committed single classes)
        # goes through the unified confirmation before the script sees clean
        self.assertIn("只有 staged、只有 tracked unstaged、两者并存、含 untracked", self.spec)
        self.assertIn("Consent covers one WIP, not arbitrary submission", self.exit)

    def test_merge_target_source_dirty_wip_is_committed_in_the_source_tree(self):
        self.assertIn("handle a dirty source in that source worktree", self.exit)
        self.assertIn("It is a separate blocker, not part of the task-tree WIP", self.exit)
        self.assertIn("WIP 提交做在源工作区", self.spec)

    def test_exit_call_itself_is_not_a_commit_authorization(self):
        self.assertIn("Invocation of this skill alone never confirms a commit", self.exit)
        self.assertIn("调用退出技能不构成 WIP 或提交确认", self.spec)

    def test_explicitly_specified_formal_commits_are_still_honored(self):
        self.assertIn("A separately and explicitly specified formal commit may be performed as authorized", self.exit)
        self.assertIn("用户已在本次会话单独明确指定正式提交", self.spec)
        self.assertIn("可按指定执行", self.spec)

    def test_existing_protections_are_kept(self):
        self.assertIn("Ignored files stay excluded", self.exit)
        self.assertIn("No automatic push, stash, reset --hard, --no-verify, force removal or branch -D", self.exit)
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
        self.assertIn("doctor", self.exit)
        self.assertIn("read-only diagnosis", self.exit)
        self.assertIn("doctor", self.spec)
        self.assertIn("只读诊断", self.spec)

    def test_recover_needs_explicit_target_and_operations(self):
        self.assertIn("recover", self.exit)
        self.assertIn(
            "explicit `recover --repo <primary-worktree> --session <path> --action archive|adopt --apply`",
            self.exit,
        )
        self.assertIn("only for states the tool can prove recoverable", self.exit)
        self.assertIn("recover", self.spec)
        self.assertIn("显式指定", self.spec)
        self.assertIn("不猜测", self.spec)
        # the two confirmed recover actions and their preconditions
        self.assertIn("archive", self.exit)
        self.assertIn("adopt", self.exit)
        self.assertIn("initialTaskHead", self.spec)

    def test_redeliver_verifies_before_delivering_again(self):
        self.assertIn("inspect redeliver dry-run before", self.exit)
        self.assertIn("Do not reuse failed verification as current proof", self.exit)
        self.assertIn("redeliver", self.spec)
        self.assertIn("先核验再交付", self.spec)
        # redeliver only applies to those interrupted delivery states
        self.assertIn("merge_verify_failed", self.exit)

    def test_enter_expect_source_flags_stop_on_mismatch(self):
        self.assertIn("--expect-source-head", self.enter)
        self.assertIn("--expect-source-branch", self.enter)
        # --apply is bound to the reviewed snapshot: both values are mandatory
        # and a drift stops the run instead of silently accepting it.
        self.assertIn("Apply with both source snapshot bindings", self.enter)
        self.assertIn("invalidate the snapshot and require fresh preflight and consent", self.enter)

    def test_merge_identity_verified_before_continue_and_abort(self):
        self.assertIn("the recorded mergeSourceBranch/mergeSourceHead/mergeTaskHead identity", self.exit)
        self.assertIn("abort-merge", self.exit)
        self.assertIn("核对 merge 身份", self.spec)
        self.assertIn("abort-merge", self.spec)
        # the merge snapshot fields the identity check is based on
        self.assertIn("mergeSourceBranch", self.exit)
        self.assertIn("mergeSourceHead", self.exit)
        self.assertIn("mergeTaskHead", self.exit)

    def test_old_sessions_without_new_evidence_block_conservatively(self):
        self.assertIn("Old sessions lacking needed merge evidence remain blocked", self.exit)
        self.assertIn("never invent fields", self.exit)
        self.assertIn("缺少新增证据", self.spec)
        self.assertIn("保守阻断", self.spec)
        self.assertIn("不猜测补齐", self.spec)
        # no invented recovery promise for old merges
        self.assertIn("recover 不能恢复所有旧 merge", self.spec)

    def test_sessions_are_backward_compatible_and_migration_keeps_them(self):
        self.assertIn("新增字段非必填", self.spec)
        self.assertIn("不覆盖现有 session", self.spec)


class RuntimeBoundaryTests(unittest.TestCase):
    """Questions stay in the skill layer; the script never asks the user."""

    def test_scripts_never_ask_the_wip_question(self):
        # The script carries Chinese comments, so the check pins the retired
        # long option texts (and the conflict options) rather than the bare
        # single-character options 是 / 否.
        for path in (ENTER_SCRIPT, EXIT_SCRIPT):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(OLD_CONFIRM_OPTION, text, path)
            self.assertNotIn(OLD_STOP_OPTION, text, path)
            self.assertNotIn("这次提交要包括哪些", text, path)
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
        # references it through the host tool and fixes equivalent choices
        self.assertIn("任务分支<任务分支>合入源分支<源分支>时发生冲突", self.spec)
        self.assertIn("保留现场由你解决后继续，还是撤销这次合并", self.spec)
        self.assertIn("撤销会取消本次合并中的冲突处理，任务分支提交和隔离目录仍保留", self.spec)
        self.assertIn(KEEP_CONFLICT_OPTION, self.spec)
        self.assertIn(ABORT_CONFLICT_OPTION, self.spec)
        self.assertIn(
            "choices equivalent to “keep the scene; I will resolve and continue” and “abort this merge.”",
            self.exit,
        )
        # no preset stash / discard / ours / theirs / agent auto-resolve
        self.assertIn("No automatic ours/theirs, force or agent resolution option", self.exit)
        self.assertIn("through the host tool", self.exit)
        self.assertIn("stash", self.exit)
        self.assertIn("ours/theirs", self.exit)
        self.assertIn("Agent conflict resolution needs separate explicit authorization", self.exit)

    def test_real_conflict_verified_before_asking(self):
        self.assertIn("MERGE_HEAD", self.exit)
        self.assertIn("unmerged paths", self.exit)
        self.assertIn("Ask the exact project conflict question through the host tool", self.exit)
        self.assertIn("MERGE_HEAD", self.spec)
        self.assertIn("未合并条目", self.spec)
        self.assertIn("冲突清单", self.spec)
        self.assertIn("实际调用问答工具", self.spec)
        self.assertIn("没有可用问答工具或工具故障时", self.spec)

    def test_keep_option_stops_and_waits_without_polling(self):
        self.assertIn("stop and wait, not poll", self.exit)
        self.assertIn("Only after the user explicitly asks to continue following resolution/staging", self.exit)
        self.assertIn("停止等待", self.spec)
        self.assertIn("不立即 continue", self.spec)
        self.assertIn("不轮询", self.spec)

    def test_continue_needs_explicit_resolved_and_staged_continue(self):
        self.assertIn("verify no unmerged paths and the same merge identity", self.exit)
        self.assertIn("This creates a merge commit, not a WIP", self.exit)
        self.assertIn("No answer/cancellation means no abort, WIP or new question channel", self.exit)
        self.assertIn("已解决并暂存，请继续", self.spec)
        self.assertIn("只读核验", self.spec)
        self.assertIn("无未合并条目", self.spec)
        self.assertIn("merge 状态吻合", self.spec)
        self.assertIn("不重问", self.spec)
        self.assertIn("不是继续授权", self.spec)

    def test_abort_is_a_single_use_authorization_with_prior_warning(self):
        self.assertIn("authorizes only that merge's `abort-merge --repo <linked-worktree> --apply`", self.exit)
        self.assertIn("conflict-resolution edits are discarded", self.exit)
        self.assertIn("Do not retry the merge automatically", self.exit)
        self.assertIn("撤销", self.spec)
        self.assertIn("编辑会被撤销", self.spec)
        self.assertIn("仅本次", self.spec)

    def test_cancel_skip_or_unanswered_neither_aborts_nor_wips(self):
        self.assertIn("No answer/cancellation means no abort, WIP or new question channel", self.exit)
        self.assertIn("取消、跳过或未回答", self.spec)
        self.assertIn("不 abort", self.spec)
        self.assertIn("不做 WIP", self.spec)
        self.assertIn("不换问法重问", self.spec)

    def test_agent_delegation_is_separate_authorization(self):
        self.assertIn("Agent conflict resolution needs separate explicit authorization", self.exit)
        self.assertIn("business trade-offs still require the user", self.exit)
        self.assertIn("委托 Agent 解决冲突", self.spec)
        self.assertIn("单独授权", self.spec)
        self.assertIn("业务取舍", self.spec)

    def test_new_conflict_never_reuses_old_authorization(self):
        self.assertIn("Consent is consumed by that commit", self.exit)
        self.assertIn("新一次 merge 冲突", self.spec)
        self.assertIn("不复用旧授权", self.spec)

    def test_conflict_state_takes_priority_over_wip_flow(self):
        self.assertIn("takes precedence over WIP", self.exit)
        self.assertIn("never stage unresolved entries into a WIP", self.exit)
        self.assertIn("This creates a merge commit, not a WIP", self.exit)
        self.assertIn("优先于", self.spec)
        self.assertIn("不是 WIP", self.spec)
        self.assertIn("另行确认", self.spec)

    def test_parallel_spec_carries_the_conflict_gate(self):
        self.assertIn("冲突固定问句", self.spec)
        self.assertIn(KEEP_CONFLICT_OPTION, self.spec)
        self.assertIn(ABORT_CONFLICT_OPTION, self.spec)
        self.assertIn("已解决并暂存，请继续", self.spec)
        self.assertIn("不是 WIP", self.spec)
        # the spec keeps the merge-identity and old-session guidance
        self.assertIn("核对 merge 身份", self.spec)
        self.assertIn("doctor", self.spec)


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
        # user edits already-shown files in the meantime (the confirmation is
        # about the approach, not the file bytes), but a branch/HEAD/change-
        # set change blocks instead of reusing the consumed confirmation
        for payload, label in ((self.enter, "enter"), (self.exit, "exit")):
            with self.subTest(skill=label):
                self.assertTrue(
                    any(
                        "普通内容修改不需要重新确认" in t and "重新预检" in t
                        for t in self.texts(payload)
                    ),
                    f"{label} evals never sample the drift boundary",
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
