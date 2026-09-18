#!/usr/bin/env python3
"""Contract tests for the PH 1.1.14 ph-intent-verify acceptance contract.

These are STATIC text checks: they only assert that the shipped SKILL.md and
evals.json contain the agreed wording. They are not behavior verification and
must not be reported as if the skill's real execution behavior had been
exercised; behavior is verified separately by dispatching the skill against
real fixtures.

The 1.1.14 release pins the skill's execution semantics without touching its
invocation gate: entries are chosen per the intent's actual target users with
the formal entry first (business users are never handed only a curl command);
remote localhost addresses are never claimed as user-side addresses and
"opened" distinguishes provided / request-accepted / user-side-loaded; a
point with no operable entry is uniformly recorded as blocked with the
reason noted, and whether it is a delivery defect is judged by the intent's
scope — a missing formal UI is a defect only when the scope demands one,
while an API-only scope merely lacks an auxiliary way for business users to
operate (not an implementation defect); auxiliary tools are prepared only
under separate authorization as a separate task whose scope and recovery
conditions are handed over, and never mock business results; when the user
explicitly asks for the missing entry to be implemented this session, the
flow converts to normal implementation without auto-invoking other skills;
one round yields one independent acceptance result that may span steps
without expanding the standard and its content lands in the user-visible
message; standards covering several clients or roles are verified per client
and role; async operations are observed as accepted-or-completed per the
standard, completion is observed within a bounded budget (polling allowed,
no unbounded waiting) whose expiry is not a product failure — a still-pending
task is recorded 未验收 with sanitized job id / entry / recovery hints and no
automatic rescheduling; file standards actually obtain the file; deep links
never prove navigation/permission standards; the four-state user feedback
stays separated from pre-check evidence with contradiction clarification
over object/environment/input/role and no fabricated failures; docs do not
authorize by themselves — scripts and configs referenced by docs are checked
read-only for their real targets and side effects first, then authorization
is confirmed, then execution happens; authorized normal cache/log byproducts
are not re-asked but the exception never covers tracked files, snapshots or
real database data — writes are identified before execution, changes are
checked after, unexpected modifications stop and report without automatic
rollback, gitignored is not safe, and read-only approaches are preferred;
read-only sessions start no writing preparations; before any request is sent the
target service is verified to belong to the current project and the authorized
environment — a reachable localhost port never implies ownership and unrelated
services are not probed; records carry entry /
role / known build (never fabricated) / pre-check evidence and exclude
secrets, sensitive inputs and credentialed URLs; non-read-only writes only
append the target intent's 记录 section, read-only also prepares no writes;
recovery re-verifies only affected points and resubmits points blocked by
host tool failures once the tool is ready.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = ROOT / "assets" / "scaffold"
SKILL = SCAFFOLD / ".agents" / "skills" / "ph-intent-verify" / "SKILL.md"
EVALS = SCAFFOLD / ".agents" / "skills" / "ph-intent-verify" / "evals" / "evals.json"


class DescriptionWriteBoundaryTests(unittest.TestCase):
    """The frontmatter ambiguity fix: “只读不写” is replaced by exact scope."""

    @classmethod
    def setUpClass(cls):
        text = SKILL.read_text(encoding="utf-8")
        cls.description = text.split("---", 2)[1]

    def test_description_states_the_write_boundary_precisely(self):
        self.assertIn("除追加目标意图的「记录」节外不写其他文件", self.description)
        self.assertIn("用户要求只读时不写任何文件、也不准备写操作", self.description)
        # the old ambiguous shorthand is gone
        self.assertNotIn("只读不写。", self.description)

    def test_description_keeps_the_invocation_gate(self):
        for term in ("明确点名", "不触发", "已显式启动", "不要求每轮重复点名",
                     "不触发其他技能"):
            self.assertIn(term, self.description)


class EntryContractTests(unittest.TestCase):
    """展示真实入口: formal entry first, per target user, honest boundaries."""

    @classmethod
    def setUpClass(cls):
        text = SKILL.read_text(encoding="utf-8")
        cls.show = text.split("## 展示真实入口", 1)[1].split("\n## ", 1)[0]

    def test_formal_entry_first_per_target_user(self):
        self.assertIn("按意图的实际目标用户选择入口，正式入口优先", self.show)
        for term in ("可复制的命令", "最小调用方式"):
            self.assertIn(term, self.show)
        self.assertIn("不以自制页面、临时包装或内部测试工具代替正式入口", self.show)

    def test_remote_localhost_is_never_a_user_side_address(self):
        self.assertIn("localhost / 127.0.0.1", self.show)
        self.assertIn("不把它当作用户可打开的地址", self.show)

    def test_missing_entry_no_default_page_and_authorized_tools_only(self):
        self.assertIn("如实报告「无入口」并注明原因", self.show)
        self.assertIn("不默认自制演示页面", self.show)
        self.assertIn("不自动实现缺失的产品入口", self.show)
        self.assertIn("取得另行授权", self.show)
        self.assertIn("其准备属于另行任务", self.show)
        self.assertIn("不代替正式入口的验收点", self.show)

    def test_prior_opening_evidence_rules_are_kept(self):
        for term in ("隔离浏览器", "可访问的地址不等于已打开", "打开操作返回成功",
                     "实际打开", "不只给一个链接", "假称打开", "非网页"):
            self.assertIn(term, self.show)

    def test_opening_has_three_states_only_user_side_load_counts(self):
        self.assertIn("区分三态", self.show)
        self.assertIn("只说明系统接受了打开请求，不等于用户侧已加载", self.show)
        self.assertIn("页面在用户侧真实加载或用户确认看到", self.show)
        self.assertIn("只有第三种状态才可以说“已打开”", self.show)

    def test_open_tool_failure_is_separate_from_product_failure(self):
        self.assertIn("宿主工具自身的失败", self.show)
        self.assertIn("与产品自身故障分开记录", self.show)
        self.assertIn("不据此把产品记「不通过」", self.show)

    def test_no_operable_entry_blocks_uniformly_with_reason(self):
        self.assertIn("没有用户可操作的入口时如实报告「无入口」并注明原因", self.show)
        self.assertIn("该验收点统一记「阻断」", self.show)

    def test_delivery_defect_judged_by_intent_scope(self):
        self.assertIn("是否属于交付缺陷按意图范围判断", self.show)
        self.assertIn("范围或标准要求正式入口而正式入口缺失或故障的，属于交付缺陷，记录缺陷与来源", self.show)
        self.assertIn("该点尚无用户实际操作结果时不编造「不通过」", self.show)

    def test_api_only_scope_lacks_auxiliary_way_not_a_defect(self):
        self.assertIn("范围只覆盖接口、标准并未要求面向该用户的正式入口时", self.show)
        self.assertIn("只算缺少辅助操作方式，不算实现缺陷", self.show)

    def test_explicit_request_converts_to_normal_implementation_without_auto_skills(self):
        self.assertIn("用户明确要求在本次会话补上实现时，按用户要求转入普通实现流程办理", self.show)
        self.assertIn("本技能不自动调用其他技能", self.show)

    def test_auxiliary_tools_never_mock_business_results(self):
        self.assertIn("不得 mock 或伪造业务结果", self.show)
        self.assertIn("只用真实调用取得结果", self.show)
        self.assertIn("向用户交代该任务的范围与恢复条件", self.show)

    def test_business_users_are_not_handed_only_api_commands(self):
        self.assertIn("业务用户等不适合命令行调用的人", self.show)
        self.assertIn("只给 curl 之类的接口命令不算其入口", self.show)
        self.assertIn("按「无入口」如实报告实现与标准的差距", self.show)


class StepContractTests(unittest.TestCase):
    """逐步验收: round granularity, coverage, observation, feedback separation."""

    @classmethod
    def setUpClass(cls):
        text = SKILL.read_text(encoding="utf-8")
        cls.step = text.split("## 逐步验收", 1)[1].split("\n## ", 1)[0]

    def test_one_point_per_round_is_one_independent_result(self):
        self.assertIn("一轮只验收一个点", self.step)
        self.assertIn("一个独立的验收结果，可以包含多个操作步骤", self.step)
        self.assertIn("不把多个独立判断合并成一个点", self.step)
        self.assertIn("不扩张标准", self.step)

    def test_multi_client_and_role_coverage(self):
        self.assertIn("逐端逐角色验收", self.step)
        self.assertIn("不以单端单角色的结果代表全部", self.step)

    def test_async_file_and_navigation_observation_per_standard(self):
        self.assertIn("「受理」或「完成」", self.step)
        self.assertIn("不一律等完成，也不把受理冒充完成", self.step)
        self.assertIn("实际取得该文件并核对内容", self.step)
        self.assertIn("不以“已生成”“导出成功”之类的提示代替文件本身", self.step)
        self.assertIn("从真实导航路径以对应角色进入验证", self.step)
        self.assertIn("直接用深链打开目标页不能证明导航与权限标准", self.step)

    def test_feedback_separated_from_precheck_with_contradiction_clarification(self):
        self.assertIn("用户反馈与预检证据分离", self.step)
        self.assertIn("单独记为预检证据，不写成用户反馈", self.step)
        self.assertIn("先向用户澄清反证再记录", self.step)
        self.assertIn("不把矛盾结果直接记为通过", self.step)
        self.assertIn("也不替用户编造未发生的不通过", self.step)
        # the four user states and the overall summary stay pinned
        self.assertIn("通过 / 不通过 / 阻断 / 未验收", self.step)
        self.assertIn("整体结论由逐项状态汇总", self.step)

    def test_clarification_checks_object_env_input_role_without_changing_standard(self):
        self.assertIn("核对用户确认的对象、环境、输入与角色是否与本验收点一致", self.step)
        self.assertIn("澄清是核实事实，不借此修改验收标准", self.step)

    def test_async_observation_is_bounded_not_unbounded_and_not_poll_banned(self):
        self.assertIn("对完成的观察是有界的", self.step)
        self.assertIn("在观察预算内等待或轮询", self.step)
        self.assertIn("不无限等待，也不一概禁止轮询", self.step)
        self.assertIn("观察预算按标准或与用户约定", self.step)

    def test_budget_expiry_is_not_a_product_failure_and_leaves_recovery_hints(self):
        self.assertIn("预算到点任务仍在处理中时记「未验收」", self.step)
        self.assertIn("观察预算到点不等于产品失败阈值，不记「不通过」", self.step)
        self.assertIn("留下可恢复的线索（任务标识、查询入口、恢复方式，含凭据的先脱敏）", self.step)
        self.assertIn("是否继续等待由用户决定，不自动定时重查", self.step)

    def test_point_content_lands_in_the_user_visible_message(self):
        self.assertIn("这四件事出现在用户可见的消息正文里", self.step)
        self.assertIn("不只写在工具调用参数或执行日志中", self.step)


class EnvironmentContractTests(unittest.TestCase):
    """环境准备: docs-missing investigation, authorization, byproducts."""

    @classmethod
    def setUpClass(cls):
        text = SKILL.read_text(encoding="utf-8")
        cls.env = text.split("## 环境准备", 1)[1].split("\n## ", 1)[0]

    def test_missing_docs_investigated_readonly_via_scripts_and_configs(self):
        self.assertIn("先只读查脚本与配置实现", self.env)
        for term in ("启动脚本", "构建配置", "容器编排", "CI 配置"):
            self.assertIn(term, self.env)
        self.assertIn("再核实所需动作在本次验收授权内后才执行", self.env)

    def test_readonly_side_effect_check_then_authorization_then_execution(self):
        self.assertIn("先只读核实其真实目标与副作用", self.env)
        self.assertIn("对照脚本与配置实现", self.env)
        self.assertIn("再核实该执行在本次验收授权内，才执行", self.env)
        self.assertIn("文档写明本身不构成授权", self.env)
        self.assertIn("执行始终限于本次验收授权内", self.env)

    def test_default_free_actions_stay_banned_even_after_investigation(self):
        for term in ("不默认重启服务", "安装", "改配置", "公开到外部网络",
                     "付费服务", "写入生产", "单独授权"):
            self.assertIn(term, self.env)

    def test_authorized_operations_are_not_re_asked(self):
        self.assertIn("已授权操作的正常副产物不因此重复征求授权", self.env)
        full_text = SKILL.read_text(encoding="utf-8")
        self.assertIn("用户已明确授权且条件未变化的操作不重复征求授权", full_text)

    def test_byproducts_never_exempt_tracked_snapshots_and_real_data(self):
        self.assertIn("属于该操作的正常副产物", self.env)
        self.assertIn("不属于修改产品", self.env)
        self.assertIn("不豁免对项目真实状态的写入", self.env)
        self.assertIn("tracked 文件、快照、数据库真实数据", self.env)
        self.assertIn("执行前先识别这次操作会写入什么", self.env)
        self.assertIn("执行后核查实际变化是否与预期一致", self.env)
        self.assertIn("发现预期外的修改立即停止", self.env)
        self.assertIn("不自动回滚", self.env)
        self.assertIn(".gitignore 忽略不等于写入安全", self.env)
        self.assertIn("优先只读", self.env)

    def test_read_only_starts_no_writing_preparations(self):
        self.assertIn("只读会话中本条例外不适用", self.env)
        self.assertIn("不执行会产生写入或外部副作用的准备", self.env)
        self.assertIn("已就绪服务的只读使用不受影响", self.env)

    def test_precheck_verifies_service_ownership_before_sending_requests(self):
        self.assertIn("向目标服务发起请求前", self.env)
        self.assertIn("先核实该服务属于当前项目且在本次授权的验收环境内", self.env)
        self.assertIn("不以 localhost / 127.0.0.1 上某端口可连通就默认其归属本项目", self.env)
        self.assertIn("不探测与本次验收无关的服务或端口", self.env)


class RecordContractTests(unittest.TestCase):
    """记录: fields, write boundary, read-only preparation ban."""

    @classmethod
    def setUpClass(cls):
        text = SKILL.read_text(encoding="utf-8")
        cls.record = text.split("## 记录", 1)[1].split("\n## ", 1)[0]

    def test_record_fields_carry_entry_role_build_and_precheck(self):
        for term in ("入口（地址、命令或调用方式）", "角色",
                     "已知构建（版本、commit 等已知标识）", "预检证据位置"):
            self.assertIn(term, self.record)

    def test_write_boundary_non_read_only_appends_only_the_intent_record(self):
        self.assertIn("非只读模式下本技能只追加目标意图的「记录」节，不写其他文件", self.record)

    def test_read_only_also_prepares_no_writes(self):
        self.assertIn("只读模式不写任何文件，也不准备写操作", self.record)
        self.assertIn("不生成待写入文件、不暂存改动", self.record)
        self.assertIn("待归档、未写入项目", self.record)

    def test_sensitive_inputs_and_credentialed_urls_are_never_recorded(self):
        self.assertIn("验收中的敏感输入与带凭据的 URL", self.record)
        self.assertIn("同样不落记录", self.record)
        self.assertIn("必要时脱敏", self.record)

    def test_known_build_recorded_from_available_information_never_fabricated(self):
        self.assertIn("已知构建按实际可得信息记录", self.record)
        self.assertIn("不编造", self.record)
        self.assertIn("也不因此阻断验收", self.record)


class RecoveryContractTests(unittest.TestCase):
    """失败与恢复: recovery re-verifies only affected points."""

    @classmethod
    def setUpClass(cls):
        text = SKILL.read_text(encoding="utf-8")
        cls.fail = text.split("## 失败与恢复", 1)[1].split("\n## ", 1)[0]

    def test_recovery_reverifies_only_affected_points(self):
        self.assertIn("只重验受影响点", self.fail)
        self.assertIn("未受影响的已确认通过点不重复打扰用户", self.fail)
        self.assertIn("中断恢复", self.fail)

    def test_not_yet_operated_and_skipped_points_are_pending(self):
        self.assertIn("尚未操作或用户跳过的点记「未验收」", self.fail)

    def test_tool_recovery_resubmits_affected_points(self):
        self.assertIn("宿主工具故障（问答、打开等）受阻的点", self.fail)
        self.assertIn("工具恢复就绪后重新提交相关验收点", self.fail)


class GateUnchangedTests(unittest.TestCase):
    """The 1.1.14 contract item must not alter the invocation gate."""

    @classmethod
    def setUpClass(cls):
        text = SKILL.read_text(encoding="utf-8")
        cls.gate = text.split("## 调用门禁", 1)[1].split("\n## ", 1)[0]

    def test_gate_sentences_survive(self):
        for term in ("仅当用户当轮明确点名本技能并要求使用时才执行",
                     "都不触发", "门禁只管入口", "预检", "取消", "沉默"):
            self.assertIn(term, self.gate)


class EvalsCoverageTests(unittest.TestCase):
    """Shipped evals sample the acceptance contract's behaviors."""

    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(EVALS.read_text(encoding="utf-8"))

    @classmethod
    def texts(cls):
        return [e["prompt"] + "\n" + e["expected_output"] for e in cls.payload["evals"]]

    def test_evals_sample_the_new_contract_behaviors(self):
        joined = "\n".join(self.texts())
        for topic in ("深链", "逐端逐角色", "受理", "实际取得", "127.0.0.1",
                      "无入口", "另行授权", "澄清", "不准备写操作",
                      "只重验受影响点", "正式入口",
                      # review-fix behaviors
                      "对照脚本与配置实现核实", "正常副产物", "接受了打开请求",
                      "mock 或伪造业务结果",
                      "curl", "用户可见的消息正文", "观察预算", "带凭据的 URL",
                      "不编造", "另行任务", "交付缺陷",
                      "范围与恢复条件", "不自动回滚", "不自动调用其他技能",
                      "不自动定时重查",
                      # service-ownership pre-check behavior
                      "端口可连通", "不探测无关服务"):
            self.assertIn(topic, joined, topic)

    def test_new_scenarios_are_present(self):
        prompts = [e["prompt"] for e in self.payload["evals"]]
        for marker in ("/finance/report", "受理编号", "CSV", "127.0.0.1",
                       "临时写个页面", "500", "只读会话", "第 1、3、5 点",
                       # review-fix scenarios
                       "scripts/start.sh", "缓存、日志和几条测试数据",
                       "打开页面的操作返回成功", "mock 工具", "curl 调用方式",
                       "问答工具的参数", "状态还是处理中", "带了个 token",
                       "commit 号", "打开工具刚才报错",
                       "tracked 的 application.yml", "入口页面实现出来",
                       "怎么交接",
                       # service-ownership pre-check scenario
                       "18080"):
            self.assertTrue(any(marker in p for p in prompts), marker)

    def test_evals_carry_the_static_sample_disclaimer(self):
        # every shipped eval notes it is a static sample, not a measured run
        for e in self.payload["evals"]:
            self.assertIn("本 eval 不表示已实测", e["expected_output"], e["id"])


if __name__ == "__main__":
    unittest.main()
