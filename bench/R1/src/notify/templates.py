"""Message templates. Templates use `$name` placeholders (string.Template);
values are HTML-escaped because receivers render the text in a web inbox."""

import html
from string import Template


def render(template: str, context: dict) -> str:
    """Substitute `$placeholders` with HTML-escaped context values.

    Unknown placeholders are left as-is (safe_substitute) so a missing value
    never raises mid-batch.
    """
    safe = {k: html.escape(str(v), quote=True) for k, v in context.items()}
    return Template(template).safe_substitute(safe)


class TemplateStore:
    def __init__(self, templates: dict[str, str]):
        self._templates = dict(templates)

    def get(self, name: str) -> str:
        try:
            return self._templates[name]
        except KeyError:
            raise KeyError(f"unknown template: {name}") from None

    def get_localized(self, name: str, locale: str) -> str:
        """Prefer `<name>.<locale>` (e.g. `welcome.pt`), fall back to `name`."""
        return self._templates.get(f"{name}.{locale}") or self.get(name)
