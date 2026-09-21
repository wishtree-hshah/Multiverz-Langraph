"""Prompt loader.

Two kinds of prompt, both resolved through :func:`render_prompt`:

* **INLINE** — the text was in the n8n node and is checked in as a named block in
  ``<stage>.md``. Rendered directly.
* **MONGO** — the n8n ``agent`` node used ``{{ $json.prompt }}`` and the template
  came from MongoDB ``prompt_list`` at runtime. Run ``strategy-navigator prompts
  pull`` to export those into ``prompts/_mongo/<promptId>.md``; until then :func:`render_prompt`
  falls back to the stage's local draft block (``registry.PromptSpec.local_block``)
  or raises :class:`PromptNotExportedError` if there is no draft.

Direct block access stays available:

    from strategy_navigator.prompts import render
    system = render("_shared.summarizer", content=text)

File convention: ``<stage>.md`` may hold multiple blocks delimited by lines of the
form ``=== name ===``. ``render("<stage>.<name>")`` renders one block;
``render("<stage>")`` renders the whole file.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from strategy_navigator.logging import get_logger
from strategy_navigator.prompts import bindings, registry
from strategy_navigator.prompts.registry import PromptSource, PromptSpec

log = get_logger(__name__)

_DIR = Path(__file__).parent
_MONGO_DIR = _DIR / "_mongo"
_env = Environment(
    undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True, autoescape=False
)

# n8n templates carry ${var}; convert to Jinja {{ var }} on load.
_NBN_VAR = re.compile(r"\$\{\s*([a-zA-Z_][\w]*)\s*\}")

__all__ = [
    "PromptNotExportedError",
    "available",
    "bindings",
    "prompt_source",
    "registry",
    "render",
    "render_prompt",
]


class PromptNotExportedError(RuntimeError):
    """A Mongo-sourced prompt has no export and no local draft to fall back to."""

    def __init__(self, spec: PromptSpec) -> None:
        super().__init__(
            f"Prompt {spec.ref!r} lives in MongoDB prompt_list (promptId="
            f"{spec.prompt_id!r}) and has not been exported. Run:\n"
            f"    strategy-navigator prompts pull\n"
            f"or place the template at prompts/_mongo/{spec.prompt_id}.md"
        )
        self.spec = spec


@lru_cache
def _load_file(stage: str) -> dict[str, str]:
    path = _DIR / f"{stage}.md"
    if not path.exists():
        raise FileNotFoundError(f"No prompt file for stage {stage!r} ({path})")
    return _split_blocks(path.read_text(encoding="utf-8"))


def _split_blocks(raw: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    current = "_full"
    buf: list[str] = []
    for line in raw.splitlines():
        if line.startswith("=== ") and line.rstrip().endswith(" ==="):
            if buf:
                blocks[current] = "\n".join(buf).strip()
            current = line.strip().strip("= ").strip()
            buf = []
        else:
            buf.append(line)
    if buf:
        blocks[current] = "\n".join(buf).strip()
    blocks.setdefault("_full", raw.strip())
    # drop the HTML doc-comment header from _full so it never renders
    blocks["_full"] = re.sub(r"<!--.*?-->", "", blocks["_full"], flags=re.DOTALL).strip()
    return blocks


def render(ref: str, /, **variables: object) -> str:
    """Render one local block. ``ref`` is ``<stage>`` or ``<stage>.<block>``."""
    stage, _, block = ref.partition(".")
    blocks = _load_file(stage)
    key = block or "_full"
    if key not in blocks:
        raise KeyError(f"Prompt block {block!r} not found in {stage}.md (have: {list(blocks)})")
    return _env.from_string(blocks[key]).render(**variables).strip()


@lru_cache
def _mongo_template(prompt_id: str) -> str | None:
    path = _MONGO_DIR / f"{prompt_id}.md"
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    # strip an optional front-matter fence we write on export
    raw = re.sub(r"\A---\n.*?\n---\n", "", raw, flags=re.DOTALL)
    return _NBN_VAR.sub(r"{{ \1 }}", raw).strip()


def prompt_source(ref: str) -> str:
    """What :func:`render_prompt` would actually use for ``ref``."""
    spec = registry.get(ref)
    if spec.source is PromptSource.INLINE:
        return "inline"
    exported = bool(spec.prompt_id and _mongo_template(spec.prompt_id) is not None)
    if spec.port_diverges:
        return "local-draft (export diverges)" if exported else "local-draft"
    if exported:
        return "mongo-export"
    if spec.local_block:
        return "local-draft"
    return "missing"


def render_prompt(ref: str, /, **variables: object) -> str:
    """Resolve a registry prompt ref to text, Mongo-export first, draft second."""
    spec = registry.get(ref)

    if spec.source is PromptSource.INLINE:
        return render(f"{spec.stage}.{spec.local_block}", **variables)

    if spec.prompt_id and not spec.port_diverges:
        tpl = _mongo_template(spec.prompt_id)
        if tpl is not None:
            return _env.from_string(tpl).render(**variables).strip()

    if spec.local_block:
        if not spec.port_diverges:
            log.warning(
                "prompt.using_local_draft",
                ref=ref,
                prompt_id=spec.prompt_id,
                hint="run `strategy-navigator prompts pull` for the production wording",
            )
        return render(f"{spec.stage}.{spec.local_block}", **variables)

    raise PromptNotExportedError(spec)


def available() -> list[str]:
    return sorted(
        p.stem for p in _DIR.glob("*.md") if not p.stem.startswith("_") or p.stem == "_shared"
    )
