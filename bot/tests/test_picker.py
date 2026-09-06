"""Group picker state machine and keyboard building."""

from __future__ import annotations

from bot.picker import (
    PAGE_SIZE,
    PickerState,
    apply_callback,
    build_keyboard,
    parse_callback,
    picker_text,
)


def make_state(n=20, preselected=()):
    return PickerState.create([f"g{i:02d}" for i in range(n)], list(preselected))


def test_create_preserves_server_order_and_dedupes():
    state = PickerState.create([("zeta", 9), ("alpha", 1), ("zeta", 9)])
    assert state.groups == [("zeta", 9), ("alpha", 1)]


def test_plain_names_default_to_zero_members():
    state = PickerState.create(["b", "a"])
    assert state.groups == [("b", 0), ("a", 0)]


def test_preselected_filtered_to_available():
    state = PickerState.create(["a", "b"], ["a", "nope"])
    assert state.selected == {"a"}


class TestPaging:
    def test_single_page(self):
        state = make_state(3)
        assert state.total_pages == 1

    def test_total_pages_rounds_up(self):
        state = make_state(PAGE_SIZE + 1)
        assert state.total_pages == 2

    def test_page_groups_slice(self):
        state = make_state(20)
        assert [name for _, name, _ in state.page_groups()] == [f"g{i:02d}" for i in range(8)]
        state.page_by(1)
        assert [name for _, name, _ in state.page_groups()] == [f"g{i:02d}" for i in range(8, 16)]

    def test_page_wraps(self):
        state = make_state(10)  # 2 pages
        state.page_by(1)
        state.page_by(1)  # wraps to 0
        assert state.page == 0
        state.page_by(-1)  # wraps to last
        assert state.page == 1


class TestToggle:
    def test_toggle_adds_removes(self):
        state = make_state(5)
        assert state.toggle(0) is True
        assert state.selected == {"g00"}
        assert state.toggle(0) is True
        assert state.selected == set()

    def test_toggle_out_of_range(self):
        state = make_state(5)
        assert state.toggle(99) is False
        assert state.toggle(-1) is False

    def test_can_confirm(self):
        state = make_state(5)
        assert state.can_confirm is False
        state.toggle(1)
        assert state.can_confirm is True


class TestKeyboard:
    def test_structure(self):
        state = make_state(10)  # 2 pages, 8 group rows on page 0
        kb = build_keyboard(state)
        rows = kb.inline_keyboard
        assert len(rows) == PAGE_SIZE + 2  # group rows + nav + confirm/cancel
        assert all(len(r) == 1 for r in rows[:PAGE_SIZE])  # big touch targets
        nav_row = rows[PAGE_SIZE]
        assert [b.callback_data for b in nav_row] == ["pg:-", "noop", "pg:+"]
        assert rows[-1][0].callback_data == "ok"
        assert rows[-1][1].callback_data == "cx"

    def test_checkbox_reflects_selection(self):
        state = make_state(10)
        state.toggle(0)
        kb = build_keyboard(state)
        assert kb.inline_keyboard[0][0].text.startswith("✅")
        assert kb.inline_keyboard[1][0].text.startswith("⬜")

    def test_buttons_show_member_counts(self):
        state = PickerState.create([("family", 12), ("admin", 1)])
        kb = build_keyboard(state)
        assert kb.inline_keyboard[0][0].text.endswith("family · 12")
        assert kb.inline_keyboard[1][0].text.endswith("admin · 1")

    def test_no_nav_row_when_one_page(self):
        kb = build_keyboard(make_state(3))
        assert len(kb.inline_keyboard) == 4  # 3 group rows + confirm/cancel


class TestCallbacks:
    def test_parse(self):
        assert parse_callback("g:5") == ("toggle", "5")
        assert parse_callback("pg:+") == ("page", "+")
        assert parse_callback("pg:-") == ("page", "-")
        assert parse_callback("ok") == ("confirm", "")
        assert parse_callback("cx") == ("cancel", "")
        assert parse_callback("noop") is None
        assert parse_callback("g:abc") is None
        assert parse_callback("garbage") is None
        assert parse_callback(None) is None

    def test_apply_toggle(self):
        state = make_state(5)
        assert apply_callback(state, ("toggle", "2")) == "updated"
        assert state.selected == {"g02"}

    def test_apply_page(self):
        state = make_state(10)
        apply_callback(state, ("page", "+"))
        assert state.page == 1

    def test_apply_passthrough(self):
        state = make_state(5)
        assert apply_callback(state, ("confirm", "")) == "confirm"
        assert apply_callback(state, ("cancel", "")) == "cancel"


def test_picker_text_lists_selection():
    state = make_state(5, preselected=["g01"])
    text = picker_text(state)
    assert "g01" in text
    state2 = make_state(5)
    assert "—" in picker_text(state2)
