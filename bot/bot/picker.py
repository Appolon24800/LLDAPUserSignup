"""Group multi-select picker: pure state machine + inline keyboard builder.

Telegram does not support argument autocomplete for custom commands, so
``/gen`` uses a paginated inline keyboard with checkboxes. The group list
arrives from the backend already ordered (most members first) and its order
is preserved: popular groups land on page one. Callback data is kept tiny
(Telegram caps it at 64 bytes): ``g:<idx>``, ``pg:<+|->``, ``ok``, ``cx``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

PAGE_SIZE = 8

_CB_TOGGLE_RE = re.compile(r"^g:(\d+)$")
_CB_PAGE_RE = re.compile(r"^pg:([+-])$")
_CB_CONFIRM = "ok"
_CB_CANCEL = "cx"

# A group from the backend: (name, member count). Bare names are accepted
# and treated as zero members, so plain-list callers keep working.
GroupEntry = "tuple[str, int] | str"


@dataclass
class PickerState:
    groups: list[tuple[str, int]]
    selected: set[str] = field(default_factory=set)
    page: int = 0

    @classmethod
    def create(
        cls, groups: list[GroupEntry], preselected: list[str] | None = None
    ) -> PickerState:
        ordered: list[tuple[str, int]] = []
        seen: set[str] = set()
        for group in groups:
            name, members = group if isinstance(group, tuple) else (group, 0)
            if name in seen:
                continue
            seen.add(name)
            ordered.append((name, members))
        return cls(groups=ordered, selected={g for g in (preselected or []) if g in seen})

    @property
    def total_pages(self) -> int:
        return max(1, -(-len(self.groups) // PAGE_SIZE))

    def page_groups(self) -> list[tuple[int, str, int]]:
        start = self.page * PAGE_SIZE
        chunk = self.groups[start : start + PAGE_SIZE]
        return [(start + offset, name, members) for offset, (name, members) in enumerate(chunk)]

    def page_by(self, delta: int) -> None:
        self.page = (self.page + delta) % self.total_pages

    def go_to_page_with(self, index: int) -> None:
        self.page = min(index // PAGE_SIZE, self.total_pages - 1)

    def toggle(self, index: int) -> bool:
        if not 0 <= index < len(self.groups):
            return False
        name = self.groups[index][0]
        if name in self.selected:
            self.selected.discard(name)
        else:
            self.selected.add(name)
        return True

    @property
    def can_confirm(self) -> bool:
        return bool(self.selected)

    def summary_line(self) -> str:
        if not self.selected:
            return "—"
        return ", ".join(sorted(self.selected))


def build_keyboard(state: PickerState) -> InlineKeyboardMarkup:
    # One group per row: full-width buttons are easier to hit.
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅' if name in state.selected else '⬜'} {name} · {members}",
                callback_data=f"g:{index}",
            )
        ]
        for index, name, members in state.page_groups()
    ]
    nav = []
    if state.total_pages > 1:
        nav.append(InlineKeyboardButton(text="◀️", callback_data="pg:-"))
        nav.append(
            InlineKeyboardButton(
                text=f"{state.page + 1}/{state.total_pages}", callback_data="noop"
            )
        )
        nav.append(InlineKeyboardButton(text="▶️", callback_data="pg:+"))
    if nav:
        rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(text="✅ Confirm", callback_data=_CB_CONFIRM),
            InlineKeyboardButton(text="✖️ Cancel", callback_data=_CB_CANCEL),
        ]
    )
    return InlineKeyboardMarkup(rows)


def picker_text(state: PickerState) -> str:
    return (
        "Select the groups for the new registration code, then confirm.\n\n"
        f"Selected: {state.summary_line()}"
    )


def parse_callback(data: str | None) -> tuple[str, str] | None:
    """Returns (kind, value) with kind in {toggle, page, confirm, cancel}."""
    if not data:
        return None
    if data == _CB_CONFIRM:
        return ("confirm", "")
    if data == _CB_CANCEL:
        return ("cancel", "")
    if match := _CB_TOGGLE_RE.match(data):
        return ("toggle", match.group(1))
    if match := _CB_PAGE_RE.match(data):
        return ("page", match.group(1))
    return None


def apply_callback(state: PickerState, parsed: tuple[str, str]) -> str:
    """Mutate the state according to a parsed callback; returns the action."""
    kind, value = parsed
    if kind == "toggle":
        state.toggle(int(value))
        return "updated"
    if kind == "page":
        state.page_by(1 if value == "+" else -1)
        return "updated"
    return kind  # confirm / cancel
