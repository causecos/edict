import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _load_skill_manager(openclaw_home, hub_base=None):
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "skill_manager.py"

    env = {"OPENCLAW_HOME": str(openclaw_home)}
    if hub_base is not None:
        env["OPENCLAW_SKILLS_HUB_BASE"] = hub_base

    spec = importlib.util.spec_from_file_location("skill_manager_under_test", script_path)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, env, clear=False):
        if hub_base is None:
            os.environ.pop("OPENCLAW_SKILLS_HUB_BASE", None)
        spec.loader.exec_module(module)
    return module


class SkillManagerTests(unittest.TestCase):
    def test_default_skills_do_not_use_removed_openclaw_hub(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill_manager = _load_skill_manager(Path(tmp) / ".openclaw")

        self.assertIn("code_review", skill_manager.OFFICIAL_SKILLS_HUB)
        # 所有 URL 必須為有效的 SKILL.md 連結
        self.assertTrue(
            all(
                url.startswith("https://") and url.endswith("/SKILL.md")
                for url in skill_manager.OFFICIAL_SKILLS_HUB.values()
            )
        )

    def test_custom_hub_base_restores_hub_skill_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill_manager = _load_skill_manager(
                Path(tmp) / ".openclaw",
                hub_base="https://example.com/openclaw-skills",
            )

        self.assertEqual(
            skill_manager.OFFICIAL_SKILLS_HUB["code_review"],
            "https://example.com/openclaw-skills/code_review/SKILL.md",
        )
        self.assertEqual(
            skill_manager.OFFICIAL_SKILLS_HUB["test_framework"],
            "https://example.com/openclaw-skills/test_framework/SKILL.md",
        )

    def test_import_official_hub_uses_per_skill_recommended_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill_manager = _load_skill_manager(Path(tmp) / ".openclaw")

        calls = []

        def fake_add_remote(agent_id, skill_name, source_url, description=""):
            calls.append((agent_id, skill_name, source_url, description))
            return True

        with mock.patch.object(skill_manager, "add_remote", fake_add_remote):
            self.assertTrue(skill_manager.import_official_hub([]))

        # import_official_hub([]) with no agents: collects all recommended agents
        # from SKILL_AGENT_MAPPING (6 unique), then 6 skills × 6 agents = 36 calls
        self.assertEqual(len(calls), 36)

        # Verify code_review dispatched to all expected agents
        code_review_agents = {c[0] for c in calls if c[1] == "code_review"}
        self.assertEqual(code_review_agents, {"bingbu", "xingbu", "menxia", "gongbu", "hubu", "libu"})

        # Verify all 6 skills were dispatched
        dispatched_skills = {c[1] for c in calls}
        self.assertEqual(dispatched_skills, {"code_review", "api_design", "security_audit", "data_analysis", "doc_generation", "test_framework"})

        # Verify URL format
        for call in calls:
            self.assertTrue(call[2].endswith(f"/{call[1]}/SKILL.md"))


if __name__ == "__main__":
    unittest.main()
