#!/usr/bin/env python3
"""Contract tests for the rewritten question spec (PH 1.1.12).

The spec ``.agents/project-harness/constraints/harness规范/对用户提问规范.md`` is organized as an execution
contract: whether to ask / the right channel with real tool execution /
question quality / handling real answers / correcting mistakes and recovery /
boundary examples / a completion checklist. It has no numbered sections, so
references must not pin section numbers, and the old per-scenario sentence
banks are gone. These tests assert the shipped semantics and structure, never
fixed user-facing question wording; the degradation to plain text is an
explicit exception with a real cause, so no test may treat visible text as
forbidden in every case.
"""
from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = ROOT / "assets/scaffold"
QUESTIONS = SCAFFOLD / ".agents/project-harness/constraints/harness规范/对用户提问规范.md"

SECTIONS = (
    "何时需要用户决定",
    "通过正确通道实际提问",
    "把问题写成可回答的决定",
    "根据真实回答推进",
    "纠正失误与恢复中断",
    "边界示例",
    "完成检查",
)


class QuestionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = QUESTIONS.read_text(encoding="utf-8")

    def test_contract_sections_without_numbered_headings(self):
        headings = re.findall(r"(?m)^## (.+)$", self.text)
        self.assertEqual(headings, list(SECTIONS))
        self.assertIsNone(
            re.search(r"(?m)^## \d+\. ", self.text),
            "the contract must not use numbered sections",
        )

    def test_decide_before_asking(self):
        # researchable facts are not questions; ordinary in-scope choices are
        # handled autonomously; answered questions and granted operations are
        # never asked or re-confirmed; defaults never bypass required approval
        self.assertIn("能查清的事实，先查不问", self.text)
        self.assertIn("授权内的普通选择，自主处理", self.text)
        self.assertIn("同一问题不重复问", self.text)
        self.assertIn("已授权的同一操作不追加", self.text)
        self.assertIn("绕过必要授权", self.text)

    def test_channel_requires_actual_tool_call(self):
        # a structured tool that can reasonably express the question must be
        # really invoked; listing options in prose or promising to ask later
        # never substitutes the call; only the actual result counts
        self.assertIn("有能合理表达当前问题的结构化问答工具时，必须实际调用", self.text)
        self.assertIn("都不能代替调用", self.text)
        self.assertIn("检查实际结果", self.text)
        self.assertIn("调用失败不代表问题已成功提交", self.text)
        self.assertIn("才可作为决定依据", self.text)

    def test_degradation_is_a_cause_bounded_exception(self):
        # text fallback needs a real cause (no tool, unrecoverable failure, or
        # a format that cannot reasonably express an open question); causes are
        # discriminated instead of treating every error as a technical fault;
        # refusal/cancellation stays pending and is never read as consent
        self.assertIn("降级必须有实际原因", self.text)
        self.assertIn("用可见文字提出同等问题并等待回答", self.text)
        self.assertIn("不声称已通过工具提问", self.text)
        self.assertIn("无法合理表达时如实说明格式限制，用文字提出开放问题", self.text)
        self.assertIn("不仅凭“error”状态判断", self.text)
        self.assertIn("权限拒绝、用户取消或跳过", self.text)
        self.assertIn("无法确认原因的无有效回答，都保留未决状态", self.text)
        self.assertIn("不换通道重复施压", self.text)
        self.assertIn("不解释成同意", self.text)

    def test_dedicated_channels_for_approval_and_secrets(self):
        self.assertIn("宿主专用审批能力", self.text)
        self.assertIn("没有允许的替代流程则说明阻断并停止依赖审批的操作", self.text)
        self.assertIn("不把普通问答伪装成审批完成", self.text)
        self.assertIn("不得要求用户在聊天、普通问答或纪要里填写秘密", self.text)
        self.assertIn("没有安全通道时停止采集", self.text)

    def test_question_quality_states_real_alternatives(self):
        self.assertIn("已经知道什么、现在请用户决定什么、选择会影响什么", self.text)
        self.assertIn("伪装成两个不同选择", self.text)
        self.assertIn("有充分依据才推荐，推荐项置首并说明理由", self.text)
        self.assertIn("不编造原因", self.text)
        self.assertIn("不虚构选择", self.text)
        self.assertIn("不能用“简化处理”代替“删除已有数据”", self.text)
        # technical words are not banned wholesale; internal field names must
        # not replace the decision the user has to make
        self.assertIn("而不是禁止所有技术词", self.text)

    def test_answer_states_are_kept_apart(self):
        self.assertIn("已提交问题、收到回答、取得操作授权是三个不同状态", self.text)
        self.assertIn("不用推荐项、预选值、沉默或代理推断补齐答案", self.text)
        self.assertIn("未获得决定时，不执行依赖它的动作", self.text)
        self.assertIn("以当前有效请求为准", self.text)

    def test_recovery_resubmits_for_real(self):
        self.assertIn("实际提交问题", self.text)
        self.assertIn("不能只回复", self.text)
        self.assertIn("不能以修改规范代替本次提问", self.text)
        self.assertIn("不从头重复整轮访谈", self.text)
        self.assertIn("仅改隔离副本不能声称指定作用域已生效", self.text)

    def test_boundary_examples_cover_authorization_reason_and_failure(self):
        self.assertIn("### 已授权的操作不重问", self.text)
        self.assertIn("### 问真实原因，不替用户编理由", self.text)
        self.assertIn("### 故障、拒绝和纠正不是同一件事", self.text)
        self.assertIn("实际清理仍需明确授权", self.text)

    def test_examples_are_judgment_not_templates(self):
        # examples explain how to judge; they must not demand repeating the
        # question in every flow nor copying questions into plain replies
        self.assertIn("以下示例说明判断方式，不是要求每个流程都重复询问", self.text)
        self.assertIn("问题内容应放进实际工具调用", self.text)


class AppliedContractClausesTests(unittest.TestCase):
    """The contract's actual-call and open-question rules applied by intent docs.

    These three spots previously kept conditional tool clauses and a fake
    "add a reason first" recommendation; they must now state the contract
    directly so the wording drift cannot reintroduce them.
    """

    @classmethod
    def setUpClass(cls):
        # The intent tree was retired with 1.2.1: 意图与访谈.md is kept only
        # as read-only history under archive/constraints-history, and it must
        # not resurface as a live constraints document.
        cls.interview = (
            SCAFFOLD / ".agents/project-harness/archive/constraints-history/意图与访谈.md"
        ).read_text(encoding="utf-8")
        cls.constraints = SCAFFOLD / ".agents/project-harness/constraints"
        self_check = [p for p in cls.constraints.rglob("意图与访谈*")]
        assert self_check == [], self_check

    def test_interview_one_question_one_answer_requires_actual_call(self):
        # 意图与访谈 §3: same actual-call rule with the semantic anchor
        # (links are textified in the archive copy).
        self.assertIn("实际调用可用问答工具", self.interview)
        self.assertIn("文字选项和口头承诺不能替代调用", self.interview)
        self.assertIn("见工程规范/对用户提问.md", self.interview)

    def test_drop_reason_is_an_open_question_not_a_fake_option(self):
        # 意图与访谈 §3: unconfirmed motives are not offered, the "补充原因后
        # 再废弃" handling is not disguised as a reason option, and a real
        # open question is asked instead; no answer keeps the item pending
        self.assertIn("不把“补充原因后再废弃”这种处理方式冒充原因选项", self.interview)
        self.assertIn("提出开放问题，取得用户说明的真实原因后再记录", self.interview)
        self.assertIn("未获原因时保留未决状态", self.interview)
        self.assertNotIn("先不放弃", self.interview)


class QuestionReferenceTests(unittest.TestCase):
    """References point at semantic sections; numbered anchors must be gone."""

    def test_no_section_number_anchors_into_the_contract(self):
        offenders = []
        candidates = sorted(SCAFFOLD.rglob("*.md")) + [ROOT / "SKILL.md"]
        for path in candidates:
            text = path.read_text(encoding="utf-8")
            if re.search(r"对用户提问\.md\)[^\n]*第\s*\d+\s*节", text) or re.search(
                r"对用户提问\.md`[^\n]*第\s*\d+\s*节", text
            ):
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])

    def test_index_row_describes_the_contract(self):
        contract = SCAFFOLD / ".agents/project-harness/constraints/harness规范/对用户提问规范.md"
        self.assertIn("使用时机：", contract.read_text(encoding="utf-8"))
        self.assertFalse((contract.parent / "README.md").exists())

    def test_contract_has_old_vs_new_and_recovery_evals(self):
        data = json.loads((ROOT / "evals/evals.json").read_text(encoding="utf-8"))
        by_id = {item["id"]: item for item in data["evals"]}
        misuse = by_id[26]
        self.assertRegex(misuse["prompt"], r"没[有用]*调用工具|没用任何问答工具")
        self.assertRegex(misuse["prompt"], r"已提交问题.*已批准|问题已经提交.*用户已同意")
        self.assertIn("实际调用", misuse["expected_output"])
        self.assertIn("问题提交、收到回答、取得授权三者不同", misuse["expected_output"])
        self.assertIn("未得到真实回答前停止", misuse["expected_output"])

        recovery = by_id[27]
        self.assertIn("工具故障后恢复", recovery["prompt"])
        self.assertIn("无法恢复", recovery["expected_output"])
        self.assertIn("可见文字提问", recovery["expected_output"])
        self.assertIn("实际提交未决问题", recovery["expected_output"])
        self.assertIn("不换通道重问、不推定同意", recovery["expected_output"])


if __name__ == "__main__":
    unittest.main()
