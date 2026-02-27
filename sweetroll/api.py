"""Editor API: the interface that extensions use to interact with the editor.

Extensions never touch the Editor or Buffer directly.  Instead, every hook
receives an EditorAPI object (as payload["api"]) which provides safe methods
for reading/changing the buffer, moving the cursor, controlling the viewport,
requesting screen regions, managing colors, and sharing data between extensions.
"""

import curses
from pathlib import Path


class EditorAPI:
    """Extension-facing API.

    Created once per editor session and passed in every hook payload as
    payload["api"].  The core owns the main loop, buffer, and text rendering;
    extensions use this API and hooks only.
    """

    def __init__(self, editor):
        self._editor = editor
        self._color_pairs = {}   # maps (fg, bg) tuples to curses pair numbers
        self._next_pair = 1      # next available curses color pair number
        self._data = {}           # shared key-value store for inter-extension data

    # --- Buffer / content ---

    def get_lines(self):
        """Return a copy of all buffer lines."""
        return list(self._editor.buffer.lines)

    def get_line(self, row):
        """Return the line at *row* (0-based).  Returns "" if out of range."""
        buf = self._editor.buffer
        if 0 <= row < len(buf.lines):
            return buf.lines[row]
        return ""

    def set_line(self, row, text):
        """Replace the line at *row* with *text*.  Marks buffer dirty."""
        buf = self._editor.buffer
        if row < 0:
            return
        # Extend the buffer if needed so that row exists
        while len(buf.lines) <= row:
            buf.lines.append("")
        buf.lines[row] = text
        buf.dirty = True
        buf.clamp_cursor()

    def get_path(self):
        """Return the buffer's file path, or None if the file has never been saved."""
        return self._editor.buffer.path

    def set_path(self, path):
        """Set the buffer's file path without loading anything from disk.

        Pass None to mark the buffer as untitled/unsaved.
        """
        self._editor.buffer.path = Path(path).resolve() if path is not None else None

    def is_dirty(self):
        """Return True if the buffer has unsaved changes."""
        return self._editor.buffer.dirty

    def save(self):
        """Save the buffer to its file path.  Returns False if no path is set."""
        return self._editor.buffer.save()

    def load_file(self, path):
        """Load a file into the buffer, replacing the current contents.

        Resets the cursor and scroll position.  Any unsaved changes to the
        previous buffer are lost unless the caller saves first.
        """
        self._editor.buffer.load(Path(path).resolve())
        self._editor.scroll_y = 0

    def replace_lines(self, lines, dirty=True):
        """Replace the entire buffer with *lines*.  Does not change the file path."""
        buf = self._editor.buffer
        buf.lines = list(lines) if lines else [""]
        buf.dirty = dirty
        buf.clamp_cursor()

    # --- Cursor ---

    def get_cursor(self):
        """Return (row, col), both 0-based."""
        buf = self._editor.buffer
        return (buf.row, buf.col)

    def set_cursor(self, row, col):
        """Move the cursor to (row, col).  Automatically clamped to buffer bounds."""
        buf = self._editor.buffer
        buf.row = row
        buf.col = col
        buf.clamp_cursor()

    # --- Viewport ---

    def get_size(self):
        """Return (height, width) of the terminal window."""
        return self._editor.win.getmaxyx()

    def get_scroll_y(self):
        """Return the vertical scroll offset (which line is at the top of the screen)."""
        return self._editor.scroll_y

    def set_scroll_y(self, y):
        """Set the vertical scroll offset.  Clamped to >= 0."""
        self._editor.scroll_y = max(0, y)

    def get_scroll_x(self):
        """Return the horizontal scroll offset (which column is at the left edge)."""
        return self._editor.scroll_x

    def set_scroll_x(self, x):
        """Set the horizontal scroll offset.  Clamped to >= 0."""
        self._editor.scroll_x = max(0, x)

    # --- Layout regions ---
    #
    # Extensions call the request_* methods during the "layout" hook to
    # reserve screen space (e.g. a status bar requests 1 footer row).
    # After layout, the get_*_rect methods return the computed position of
    # each region as a (y, x, height, width) tuple, or None if empty.

    def request_header_rows(self, n):
        """Request *n* rows for the header area (top of screen)."""
        self._editor.layout_request["header"] = max(self._editor.layout_request["header"], n)

    def request_footer_rows(self, n):
        """Request *n* rows for the footer area (bottom of screen)."""
        self._editor.layout_request["footer"] = max(self._editor.layout_request["footer"], n)

    def request_left_columns(self, n):
        """Request *n* columns for the left sidebar."""
        self._editor.layout_request["left"] = max(self._editor.layout_request["left"], n)

    def request_right_columns(self, n):
        """Request *n* columns for the right sidebar."""
        self._editor.layout_request["right"] = max(self._editor.layout_request["right"], n)

    def get_content_rect(self):
        """Return (y, x, height, width) of the main text editing area."""
        return self._editor.layout_rects.get("content_rect")

    def get_header_rect(self):
        """Return (y, x, height, width) of the header, or None if no header."""
        return self._editor.layout_rects.get("header_rect")

    def get_footer_rect(self):
        """Return (y, x, height, width) of the footer, or None if no footer."""
        return self._editor.layout_rects.get("footer_rect")

    def get_left_rect(self):
        """Return (y, x, height, width) of the left sidebar, or None if no sidebar."""
        return self._editor.layout_rects.get("left_rect")

    def get_right_rect(self):
        """Return (y, x, height, width) of the right sidebar, or None if no sidebar."""
        return self._editor.layout_rects.get("right_rect")

    # --- Status message ---

    def get_message(self):
        """Return the current status message."""
        return self._editor.message

    def set_message(self, msg):
        """Set the status message (shown by a status bar extension, if installed)."""
        self._editor.message = msg

    # --- Colors ---

    def color_pair(self, fg, bg):
        """Return a curses color attribute for the given foreground/background.

        Registers the color pair with curses on first use and caches it.
        Use -1 for fg or bg to mean the terminal's default color.
        """
        key = (fg, bg)
        if key not in self._color_pairs:
            curses.init_pair(self._next_pair, fg, bg)
            self._color_pairs[key] = self._next_pair
            self._next_pair += 1
        return curses.color_pair(self._color_pairs[key])

    # --- Shared data store ---
    #
    # Extensions can store and retrieve arbitrary data here so they can
    # communicate with each other (e.g. the selection extension stores
    # "selection.anchor" so the clipboard extension can read it).

    def set_data(self, key, value):
        """Store a value under *key* for other extensions to read."""
        self._data[key] = value

    def get_data(self, key, default=None):
        """Retrieve a value set by set_data.  Returns *default* if not found."""
        return self._data.get(key, default)

    # --- Low-level access ---

    def get_win(self):
        """Return the raw curses window (for extensions that draw overlays)."""
        return self._editor.win
