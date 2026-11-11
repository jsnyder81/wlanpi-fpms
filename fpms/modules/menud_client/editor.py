"""Local editor for the prompts the service cannot drive with its cursor.

``select``, ``confirm`` and ``integer`` prompts are answered on the shared
screen with ``input`` frames. ``string`` and ``form`` prompts "need a
keyboard": the surface collects the value and sends an ``answer`` frame.
The panel has no keyboard, so this is a button editor:

Form (a list of the fields, then Send and Cancel)
    up/down     move between rows
    center/right  edit the field, or activate Send / Cancel
    left        cancel the prompt
    key1        send        key3  cancel

Editing a field
    enum        up/down pick a choice, center/right keep it, left discard
    integer     up/down step the value, center/right keep it, left discard
    string      up/down pick a character, right append it, left delete the
                last one (leave when empty), center keep the text,
                key2 jump to the next character group

Everything works with the five-way switch alone (the WLAN Pi Pro has no
key1 to key3); the keys are shortcuts.

The editor draws nothing itself. ``view()`` describes its screen as view
blocks, so it goes through the same renderer as a server view.
"""

from __future__ import annotations

from typing import Any

CHAR_GROUPS = (
    "abcdefghijklmnopqrstuvwxyz",
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "0123456789",
    " .-_@:/!#$%&*+=?,;'\"()[]{}<>\\|~^`",
)
CHARS = "".join(CHAR_GROUPS)
MASK = "•"

Action = tuple[str, dict[str, Any]]  # ("answer", {one answer field}) | ("redraw", {})
REDRAW: Action = ("redraw", {})


def _cancel() -> Action:
    return ("answer", {"cancel": True})


class PromptEditor:
    def __init__(self, prompt: dict[str, Any]):
        self.prompt = prompt
        self.prompt_id = str(prompt["prompt_id"])
        self.single = prompt.get("kind") != "form"
        if self.single:
            # A string prompt is a form of one unnamed string field.
            field: dict[str, Any] = {
                "name": "value",
                "label": prompt.get("title", "Value"),
                "type": "string",
            }
            if isinstance(prompt.get("default"), str):
                field["default"] = prompt["default"]
            self.fields = [field]
        else:
            self.fields = list(prompt.get("fields") or [])
        self.values: dict[str, Any] = {}
        for f in self.fields:
            if "default" in f:
                self.values[f["name"]] = f["default"]
            elif f["type"] == "enum":
                self.values[f["name"]] = f["choices"][0]["value"]
            elif f["type"] == "integer":
                self.values[f["name"]] = f.get("minimum", 0)
        self.row = 0
        self.editing: dict[str, Any] | None = None
        self.draft: Any = None
        self.char = 0
        self.message: str | None = None
        if self.single:
            self._begin(self.fields[0])

    # ------------------------------------------------------------------ keys

    def handle(self, key: str) -> Action:
        self.message = None
        if key == "key3":
            return _cancel()
        if self.editing is not None:
            return self._edit_key(key)
        rows = len(self.fields) + 2
        if key == "up":
            self.row = (self.row - 1) % rows
        elif key == "down":
            self.row = (self.row + 1) % rows
        elif key == "left":
            return _cancel()
        elif key == "key1":
            return self._submit()
        elif key in ("center", "right"):
            if self.row == len(self.fields):
                return self._submit()
            if self.row == len(self.fields) + 1:
                return _cancel()
            self._begin(self.fields[self.row])
        return REDRAW

    def _begin(self, field: dict[str, Any]) -> None:
        if field["type"] == "adapter":
            self.message = "Pick the adapter on another surface"
            return
        self.editing = field
        self.draft = self.values.get(field["name"])
        if field["type"] == "string":
            self.draft = self.draft or ""
            self.char = 0

    def _keep(self) -> Action:
        assert self.editing is not None
        self.values[self.editing["name"]] = self.draft
        if self.single:
            return self._submit()
        self.editing = None
        return REDRAW

    def _edit_key(self, key: str) -> Action:
        field = self.editing
        assert field is not None
        kind = field["type"]
        if key == "key1":
            self.values[field["name"]] = self.draft
            return self._submit()
        if kind == "string":
            if key == "up":
                self.char = (self.char - 1) % len(CHARS)
            elif key == "down":
                self.char = (self.char + 1) % len(CHARS)
            elif key == "key2":
                self.char = self._next_group()
            elif key == "right":
                limit = field.get("max_length")
                if limit is not None and len(self.draft) >= limit:
                    self.message = f"At most {limit} characters"
                else:
                    self.draft += CHARS[self.char]
            elif key == "left":
                if self.draft:
                    self.draft = self.draft[:-1]
                elif self.single:
                    return _cancel()
                else:
                    self.editing = None
            elif key == "center":
                return self._keep()
            return REDRAW
        if key == "left":
            self.editing = None  # discard the draft
        elif key in ("center", "right"):
            return self._keep()
        elif key in ("up", "down") and kind == "integer":
            step = field.get("step", 1) * (1 if key == "up" else -1)
            value = (self.draft if isinstance(self.draft, int) else 0) + step
            if "minimum" in field:
                value = max(field["minimum"], value)
            if "maximum" in field:
                value = min(field["maximum"], value)
            self.draft = value
        elif key in ("up", "down") and kind == "enum":
            values = [c["value"] for c in field["choices"]]
            at = values.index(self.draft) if self.draft in values else 0
            self.draft = values[(at + (1 if key == "down" else -1)) % len(values)]
        return REDRAW

    def _next_group(self) -> int:
        start = 0
        for group in CHAR_GROUPS:
            if start <= self.char < start + len(group):
                return (start + len(group)) % len(CHARS)
            start += len(group)
        return 0

    def _submit(self) -> Action:
        if self.single:
            return ("answer", {"value": self.values.get("value", "")})
        for f in self.fields:
            if f.get("required", True) and self.values.get(f["name"]) in (None, ""):
                self.message = f"{f['label']} is required"
                self.editing = None
                return REDRAW
        values = {k: v for k, v in self.values.items() if v not in (None, "")}
        return ("answer", {"values": values})

    # ------------------------------------------------------------------ screen

    def _shown(self, field: dict[str, Any], value: Any) -> str:
        if value is None or value == "":
            return "-"
        if field["type"] == "enum":
            for c in field["choices"]:
                if c["value"] == value:
                    return str(c["label"])
        if field["type"] == "string" and field.get("secret"):
            return MASK * len(str(value))
        return str(value)

    def view(self) -> dict[str, Any]:
        """The editor's screen as a view frame body (title, blocks, hints)."""
        title = self.prompt.get("title", "")
        blocks: list[dict[str, Any]] = []
        if self.prompt.get("message"):
            blocks.append({"type": "text", "text": self.prompt["message"]})
        field = self.editing
        if field is None:
            items = [
                {
                    "label": f["label"],
                    "detail": self._shown(f, self.values.get(f["name"])),
                }
                for f in self.fields
            ]
            items += [{"label": "Send"}, {"label": "Cancel"}]
            blocks.append(
                {"type": "list", "text": "", "items": items, "selected": self.row}
            )
            hints = {"left": "Cancel", "center": "Edit", "key1": "Send"}
        elif field["type"] == "string":
            text = self._shown(field, self.draft) if self.draft else ""
            if not self.single:
                blocks.append(
                    {"type": "text", "text": field["label"], "style": "muted"}
                )
            blocks.append(
                {
                    "type": "text",
                    "text": f"{text}[{CHARS[self.char]}]",
                    "style": "heading",
                }
            )
            blocks.append(
                {
                    "type": "text",
                    "text": "Up/Down: character\nRight: add  Left: delete",
                    "style": "muted",
                }
            )
            hints = {"center": "OK", "key2": "abc/123"}
        else:
            blocks.append({"type": "text", "text": field["label"], "style": "muted"})
            blocks.append(
                {
                    "type": "text",
                    "text": f"< {self._shown(field, self.draft)} >",
                    "style": "heading",
                }
            )
            hints = {"left": "Back", "center": "OK"}
        if self.message:
            blocks.append({"type": "status", "level": "warn", "text": self.message})
        return {"screen": "prompt", "title": title, "blocks": blocks, "hints": hints}
