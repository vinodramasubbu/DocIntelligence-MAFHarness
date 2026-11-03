import asyncio
from types import SimpleNamespace

from agent_framework import AgentSession, SessionContext, SkillsProvider

from conftest import ROOT


async def turn(provider, session):
    context = SessionContext(input_messages=[])
    await provider.before_run(
        agent=SimpleNamespace(id="test-agent", name="test-agent"),
        session=session, context=context, state={},
    )
    return context


async def load(context, name):
    tool = next(tool for tool in context.tools if tool.name == "load_skill")
    return await tool.invoke(arguments={"skill_name": name}, skip_parsing=True)


def test_native_provider_advertises_metadata_then_loads_markdown():
    async def verify():
        provider = SkillsProvider.from_paths(ROOT / "api" / "skills", script_extensions=(), disable_caching=True)
        context = await turn(provider, AgentSession())
        advertised = "\n".join(context.instructions)
        for name in ("understand-template", "read-raw-data", "fill-template"):
            assert name in advertised
        assert not list((ROOT / "api" / "skills").rglob("*.py"))
        assert "Preserve historic values unless" not in advertised
        body = await load(context, "understand-template")
        assert "# Understand the template" in body
        assert "LocalShellTool" in body
        assert "Preserve historic values unless" in body
    asyncio.run(verify())


def test_markdown_only_skills_and_edits_are_discovered_on_next_turn(tmp_path):
    async def verify():
        folder = tmp_path / "broker-guidance"
        folder.mkdir()
        skill = folder / "SKILL.md"
        skill.write_text(
            "---\nname: broker-guidance\ndescription: Explain broker review expectations.\n"
            "---\n# Broker guidance\nAsk the broker to review all USD amounts.\n",
            encoding="utf-8",
        )
        provider = SkillsProvider.from_paths(tmp_path, disable_caching=True)
        session = AgentSession()
        first = await turn(provider, session)
        assert "all USD amounts" in await load(first, "broker-guidance")

        skill.write_text(skill.read_text().replace("USD", "EUR"), encoding="utf-8")
        extra = tmp_path / "review-notes"
        extra.mkdir()
        (extra / "SKILL.md").write_text(
            "---\nname: review-notes\ndescription: Read client review notes.\n"
            "---\n# Review notes\nRead every note before proposing a plan.\n",
            encoding="utf-8",
        )
        second = await turn(provider, session)
        assert "all EUR amounts" in await load(second, "broker-guidance")
        assert "USD" not in await load(second, "broker-guidance")
        assert "review-notes" in "\n".join(second.instructions)
        assert "Read every note" in await load(second, "review-notes")
    asyncio.run(verify())
