from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = (REPO_ROOT / "skills" / "project-osmos" / "SKILL.md").read_text(encoding="utf-8")
FIRST_RUN_EXPERIENCE = (
    REPO_ROOT / "skills" / "project-osmos" / "references" / "first-run-experience.md"
).read_text(encoding="utf-8")
URL_PARSING = (REPO_ROOT / "skills" / "project-osmos" / "references" / "url-parsing.md").read_text(
    encoding="utf-8"
)
ENVIRONMENT_ROUTING = (
    REPO_ROOT / "skills" / "project-osmos" / "references" / "environment-routing.md"
).read_text(encoding="utf-8")
AUTH_AND_ROUTING = (
    REPO_ROOT / "skills" / "project-osmos" / "references" / "auth-and-routing.md"
).read_text(encoding="utf-8")


class ProjectOsmosHostContextTests(unittest.TestCase):
    def test_fabric_copilot_routing_is_per_run_and_schema_flexible(self) -> None:
        self.assertIn("### Per-run host routing", SKILL)
        self.assertIn("On every run", SKILL)
        self.assertIn("whether you are Copilot running in Microsoft Fabric", SKILL)
        self.assertIn("Fabric page context", SKILL)
        self.assertIn("exact JSON shape and field names may change", SKILL)
        self.assertIn("pasted JSON does not identify the host", SKILL)
        self.assertNotIn("Fabric UCC host context", FIRST_RUN_EXPERIENCE)
        self.assertNotIn("```json", FIRST_RUN_EXPERIENCE)
        for field_name in ("pageUrl", "activeWorkspace", "activeArtifact", "artifactObjectId"):
            self.assertNotIn(field_name, f"{SKILL}\n{FIRST_RUN_EXPERIENCE}")

    def test_environment_is_routed_before_discovery(self) -> None:
        environment_reference = "[Environment routing](references/environment-routing.md)"
        self.assertIn(environment_reference, SKILL)
        self.assertIn("Before resolving workspace/Lakehouse names or making any Fabric API call", SKILL)
        self.assertLess(SKILL.index(environment_reference), SKILL.index("search-consumption-cli"))
        self.assertIn("before workspace/Lakehouse name discovery", ENVIRONMENT_ROUTING)
        if "Internal validation contexts" in ENVIRONMENT_ROUTING:
            self.assertIn("Do not use `search-consumption-cli`", ENVIRONMENT_ROUTING)
            self.assertIn("Use `invoke-mwc-platform-api`", ENVIRONMENT_ROUTING)
        else:
            self.assertNotIn("invoke-mwc-platform-api", ENVIRONMENT_ROUTING)
        self.assertIn("--fabric-api-host <selected-fabric-api-host>", AUTH_AND_ROUTING)
        self.assertIn("-FabricApiHost <selected-fabric-api-host>", AUTH_AND_ROUTING)

    def test_context_menu_offers_names_and_url(self) -> None:
        self.assertIn("Use workspace `<workspace_name>`, Lakehouse `<lakehouse_name>`", SKILL)
        self.assertIn("Use workspace `<workspace_name>` and choose a different Lakehouse", SKILL)
        self.assertIn("Provide a Lakehouse URL", SKILL)
        self.assertIn("Provide workspace and Lakehouse names", SKILL)
        self.assertIn("Use workspace `<workspace_name>` and choose a Lakehouse", SKILL)

    def test_names_are_resolved_with_fabric_skills(self) -> None:
        self.assertIn("Never discard supplied names and ask for a URL instead", SKILL)
        self.assertIn("Microsoft Fabric Skills", SKILL)
        self.assertIn("search-consumption-cli", SKILL)
        self.assertIn("resolve the workspace by `displayName`", SKILL)
        self.assertIn("resolve the Lakehouse by `displayName`", SKILL)
        self.assertIn("Use this reference only when the user chooses **Provide a Lakehouse URL**", URL_PARSING)

    def test_url_parser_uses_strict_path_uuid_patterns(self) -> None:
        self.assertIn("urlsplit(...).path", URL_PARSING)
        self.assertIn("WORKSPACE_PATH_RE.match(parts.path)", URL_PARSING)
        self.assertIn("LAKEHOUSE_PATH_RE.match(parts.path)", URL_PARSING)
        self.assertNotIn("[0-9a-f-]{36}", URL_PARSING)
        self.assertNotIn("URL_RE.search(url)", URL_PARSING)
        self.assertIn("valid workspace-only path returns `lakehouse_id: None`", URL_PARSING)

    def test_generic_path_does_not_identify_the_agent(self) -> None:
        self.assertIn("Otherwise use the generic-agent path", SKILL)
        self.assertIn("Do not identify or distinguish the generic agent, client, or runtime", SKILL)
        guidance = f"{SKILL}\n{FIRST_RUN_EXPERIENCE}"
        for client_name in ("UCC", "CLI-family", "GitHub Copilot CLI", "Claude Code", "Codex", "Hermes"):
            self.assertNotIn(client_name, guidance)


if __name__ == "__main__":
    unittest.main()
