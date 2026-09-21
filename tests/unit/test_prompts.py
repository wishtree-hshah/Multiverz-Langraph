import pytest

from strategy_navigator.prompts import (
    PromptNotExportedError,
    _load_file,
    _mongo_template,
    available,
    bindings,
    prompt_source,
    registry,
    render,
    render_prompt,
)
from strategy_navigator.schemas.common import AgentRef, ProjectContext


def test_all_prompt_files_parse_into_blocks():
    stages = available()
    assert {"domain_agent", "idea_extraction", "voting", "_shared"} <= set(stages)
    for stage in stages:
        blocks = _load_file(stage)
        assert blocks, f"{stage}.md produced no blocks"


def test_project_vars_populates_every_alias(sample_project):
    v = bindings.build(ProjectContext.model_validate(sample_project))
    for name in registry.PROJECT_VARS:
        assert name in v, name
    assert "Grid Modernisation" in v["project_name"]
    assert v["client"] == v["client_org"] == v["client_organization"]
    # camelCase aliases for the 10-step templates
    assert v["projectName"] == v["project_name"]


def test_project_context_block_renders_from_vars(sample_project):
    v = bindings.build(ProjectContext.model_validate(sample_project))
    out = render("_shared.project_context", **v)
    assert "Grid Modernisation" in out
    assert "NorthGrid" in out
    assert "Regulator" in out


def test_every_registry_mongo_prompt_is_exported():
    """The n8n prompt_list export is committed under prompts/_mongo/."""
    missing = [p for p in registry.mongo_prompt_ids() if _mongo_template(p) is None]
    assert not missing, f"not exported: {missing}"


def test_render_prompt_uses_the_real_export(sample_project):
    v = bindings.build(ProjectContext.model_validate(sample_project), min_agents=3, max_agents=6)
    assert prompt_source("domain_agent.system") == "mongo-export"
    out = render_prompt("domain_agent.system", **v)
    assert "NorthGrid" in out
    assert "${" not in out  # every n8n placeholder was substituted


def test_render_prompt_inline_is_verbatim():
    assert prompt_source("custom_archetype.system") == "inline"
    out = render_prompt("custom_archetype.system", payload_json="{}")
    assert "custom report archetype" in out


def test_voting_port_diverges_uses_local_draft(sample_project):
    v = bindings.build(
        ProjectContext.model_validate(sample_project),
        agent=AgentRef(id=1, name="Dr X", designation="Economist", description="macro"),
    )
    assert prompt_source("voting.contextual").startswith("local-draft")
    out = render_prompt("voting.contextual", **v)
    assert "Dr X" in out  # the persona-driven child_system block, not the per-idea export


def test_prompt_not_exported_error_message():
    spec = registry.get("idea_extraction.document_ingestion")
    err = PromptNotExportedError(spec)
    assert "document_ingestion_prompt" in str(err)


def test_registry_mongo_ids_are_distinct():
    ids = registry.mongo_prompt_ids()
    assert len(ids) == len(set(ids))
    assert {"1", "consolidation_a", "3_10"} <= set(ids)


def test_strict_undefined_raises_on_missing_var():
    with pytest.raises(Exception):
        render("domain_agent.system")


def test_missing_block_raises():
    with pytest.raises(KeyError):
        render("domain_agent.nonexistent_block")
