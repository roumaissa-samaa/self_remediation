import json as _json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_SPLIT_MARKER = "---USER---"

_env = Environment(
    loader=FileSystemLoader(_PROMPTS_DIR),
    variable_start_string="<<",
    variable_end_string=">>",
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["tojson"] = lambda v, indent=2: _json.dumps(v, indent=indent, ensure_ascii=False)


def load_prompt(template_name: str, **kwargs) -> tuple[str, str]:
    rendered = _env.get_template(template_name).render(**kwargs)
    parts = rendered.split(_SPLIT_MARKER, 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", rendered.strip()
