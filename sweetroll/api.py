"""Editor API: stable extension surface for buffer, cursor, viewport, events, and shared data."""

import curses

from pathlib import Path
from typing import Any

# Rect is (y, x, height, width)
LayoutRect = tuple[int, int, int, int]


class EditorAPI:
    """
    Extension-facing API. Created by the core once per run and passed in every hook payload as payload["api"].
    Core owns the main loop, buffer, and main text rendering; extensions use this API and hooks only.
    """

    def __init__(self, editor: Any):
        self._editor = editor
        self._color_pairs: dict[tuple[int, int], int] = {}
        self._next_pair: int = 1
        self._data: dict[str, Any] = {}

    # --- Buffer / content ---

    def get_lines(self) -> list[str]:
        """Return a copy of all buffer lines."""
        return list(self._editor.buffer.lines)

    def get_line(self, row: int) -> str:
        """Return the line at row (0-based)."""
        buf = self._editor.buffer
        if 0 <= row < len(buf.lines):
            return buf.lines[row]
        return ""

    def set_line(self, row: int, text: str) -> None:
        """Set the line at row (0-based). Clamps row. Marks buffer dirty."""
        buf = self._editor.buffer
        if row < 0:
            return
        while len(buf.lines) <= row:
            buf.lines.append("")
        buf.lines[row] = text
        buf.dirty = True
        buf.clamp_cursor()

    def get_path(self) -> Path | None:
        """Return the buffer file path, or None if unsaved."""
        return self._editor.buffer.path

    def set_path(self, path: Path | str | None) -> None:
        """Set the buffer file path without loading. path None for unsaved/unnamed."""
        self._editor.buffer.path = Path(path).resolve() if path is not None else None

    def is_dirty(self) -> bool:
        """Return whether the buffer has unsaved changes."""
        return self._editor.buffer.dirty

    def save(self) -> bool:
        """Save buffer to path. Returns False if no path."""
        return self._editor.buffer.save()

    def load_file(self, path: Path | str) -> None:
        """Load file into buffer (replacing current content), update path/cursor/scroll/dirty.
        Unsaved changes to the current buffer are discarded unless the caller saves first."""
        self._editor.buffer.load(Path(path).resolve())
        self._editor.scroll_y = 0

    def replace_lines(self, lines: list[str], dirty: bool = True) -> None:
        """Replace entire buffer content. Clamps cursor. Does not change path."""
        buf = self._editor.buffer
        buf.lines = list(lines) if lines else [""]
        buf.dirty = dirty
        buf.clamp_cursor()

    # --- Cursor ---

    def get_cursor(self) -> tuple[int, int]:
        """Return (row, col) 0-based."""
        buf = self._editor.buffer
        return (buf.row, buf.col)

    def set_cursor(self, row: int, col: int) -> None:
        """Set cursor position (0-based). Clamped to buffer bounds."""
        buf = self._editor.buffer
        buf.row = row
        buf.col = col
        buf.clamp_cursor()

    # --- Viewport ---

    def get_size(self) -> tuple[int, int]:
        """Return (height, width) of the window."""
        return self._editor.win.getmaxyx()

    def get_scroll_y(self) -> int:
        """Return current scroll offset (top line index)."""
        return self._editor.scroll_y

    def set_scroll_y(self, y: int) -> None:
        """Set scroll offset (top line index). Clamped to >= 0."""
        self._editor.scroll_y = max(0, y)

    def get_scroll_x(self) -> int:
        """Return current horizontal scroll offset (leftmost visible column)."""
        return self._editor.scroll_x

    def set_scroll_x(self, x: int) -> None:
        """Set horizontal scroll offset. Clamped to >= 0."""
        self._editor.scroll_x = max(0, x)

    # --- Layout regions (call request_* during "layout" hook) ---

    def request_header_rows(self, n: int) -> None:
        """Request n rows for the header area. Call during the layout hook. Max of all requests is used."""
        self._editor.layout_request["header"] = max(self._editor.layout_request["header"], n)

    def request_footer_rows(self, n: int) -> None:
        """Request n rows for the footer area. Call during the layout hook. Max of all requests is used."""
        self._editor.layout_request["footer"] = max(self._editor.layout_request["footer"], n)

    def request_left_columns(self, n: int) -> None:
        """Request n columns for the left sidebar. Call during the layout hook. Max of all requests is used."""
        self._editor.layout_request["left"] = max(self._editor.layout_request["left"], n)

    def request_right_columns(self, n: int) -> None:
        """Request n columns for the right sidebar. Call during the layout hook. Max of all requests is used."""
        self._editor.layout_request["right"] = max(self._editor.layout_request["right"], n)

    def get_content_rect(self) -> LayoutRect | None:
        """Return (y, x, height, width) of the main text area, or None."""
        return self._editor.layout_rects.get("content_rect")

    def get_header_rect(self) -> LayoutRect | None:
        """Return (y, x, height, width) of the header region, or None if zero size."""
        return self._editor.layout_rects.get("header_rect")

    def get_footer_rect(self) -> LayoutRect | None:
        """Return (y, x, height, width) of the footer region, or None if zero size."""
        return self._editor.layout_rects.get("footer_rect")

    def get_left_rect(self) -> LayoutRect | None:
        """Return (y, x, height, width) of the left sidebar region, or None if zero size."""
        return self._editor.layout_rects.get("left_rect")

    def get_right_rect(self) -> LayoutRect | None:
        """Return (y, x, height, width) of the right sidebar region, or None if zero size."""
        return self._editor.layout_rects.get("right_rect")

    # --- Status ---

    def get_message(self) -> str:
        """Return the current message."""
        return self._editor.message

    def set_message(self, msg: str) -> None:
        """Set the message."""
        self._editor.message = msg

    # --- Colors ---

    def color_pair(self, fg: int, bg: int) -> int:
        """Return a curses color attr for fg/bg. Registers the pair on first use.
        Use -1 for fg or bg to mean the terminal's default color."""
        key = (fg, bg)
        if key not in self._color_pairs:
            curses.init_pair(self._next_pair, fg, bg)
            self._color_pairs[key] = self._next_pair
            self._next_pair += 1
        return curses.color_pair(self._color_pairs[key])

    # --- Shared extension data store ---

    def set_data(self, key: str, value: Any) -> None:
        """Store a value under key. Extensions use this to share state."""
        self._data[key] = value

    def get_data(self, key: str, default: Any = None) -> Any:
        """Retrieve a value previously set by set_data. Returns default if not found."""
        return self._data.get(key, default)

    # --- Low-level for overlays ---

    def get_win(self) -> Any:
        """Return the curses window for drawing overlays."""
        return self._editor.win
