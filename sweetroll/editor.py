"""Editor: the core of sweetroll.

Contains the Buffer (document model), the hook system (how extensions plug in),
and the Editor (main loop, rendering, and keyboard handling).

"curses" is a Python library for building text-based terminal interfaces.
It lets you draw text at specific positions on the screen, read keypresses,
and use colors — everything you need for a terminal text editor.
"""

import curses
import sys
from pathlib import Path

from sweetroll.api import EditorAPI

# Key codes for built-in shortcuts
KEY_QUIT = 17          # Ctrl+Q
KEY_SAVE = 19          # Ctrl+S
KEY_TAB = 9

# Some keys can produce different codes depending on the terminal,
# so we check against a set of possible values.
KEY_ENTER_CODES = {curses.KEY_ENTER, 10, 13}
BACKSPACE_CODES = {curses.KEY_BACKSPACE, 127}


# ---------------------------------------------------------------------------
# Buffer – represents a single open document
# ---------------------------------------------------------------------------

class Buffer:
    """A single document: a list of text lines plus a cursor position.

    Lines are stored as a plain Python list of strings (one per line).
    Row and column are 0-based (row 0 is the first line, col 0 is the first
    character).
    """

    def __init__(self, path=None):
        self.path = path
        self.row = 0
        self.col = 0
        self.dirty = False

        # Load the file from disk, or start with one empty line
        if path and path.exists():
            text = path.read_text()
            self.lines = text.splitlines()
            # If the file was completely empty, start with one blank line
            if not self.lines:
                self.lines = [""]
        else:
            self.lines = [""]

    def clamp_cursor(self):
        """Make sure the cursor is inside the buffer bounds.

        If the cursor row is past the last line, move it back.
        If the cursor column is past the end of the current line, move it back.
        """
        last_row = len(self.lines) - 1
        self.row = max(0, min(self.row, last_row))

        last_col = len(self.lines[self.row])
        self.col = max(0, min(self.col, last_col))

    def insert_char(self, char):
        """Insert a character (or short string like 4 spaces for Tab) at the cursor."""
        line = self.lines[self.row]
        before = line[:self.col]
        after = line[self.col:]
        self.lines[self.row] = before + char + after
        self.col += len(char)
        self.dirty = True

    def backspace(self):
        """Delete the character before the cursor (like pressing Backspace)."""
        if self.col > 0:
            # Remove one character to the left of the cursor
            line = self.lines[self.row]
            before = line[:self.col - 1]
            after = line[self.col:]
            self.lines[self.row] = before + after
            self.col -= 1
            self.dirty = True
        elif self.row > 0:
            # At the start of a line: merge this line onto the end of the previous one
            self.col = len(self.lines[self.row - 1])
            self.lines[self.row - 1] += self.lines[self.row]
            self.lines.pop(self.row)
            self.row -= 1
            self.dirty = True

    def delete_char(self):
        """Delete the character at the cursor (like pressing Delete)."""
        line = self.lines[self.row]
        if self.col < len(line):
            # Remove the character right at the cursor
            before = line[:self.col]
            after = line[self.col + 1:]
            self.lines[self.row] = before + after
            self.dirty = True
        elif self.row < len(self.lines) - 1:
            # At the end of a line: pull the next line up onto this one
            self.lines[self.row] += self.lines[self.row + 1]
            self.lines.pop(self.row + 1)
            self.dirty = True

    def enter(self):
        """Split the current line at the cursor (like pressing Enter)."""
        line = self.lines[self.row]
        # Everything after the cursor becomes a new line below
        before = line[:self.col]
        after = line[self.col:]
        self.lines[self.row] = before
        self.lines.insert(self.row + 1, after)
        self.row += 1
        self.col = 0
        self.dirty = True

    def save(self):
        """Write the buffer to disk. Returns False if there is no file path."""
        if not self.path:
            return False
        text = "\n".join(self.lines) + "\n"
        self.path.write_text(text)
        self.dirty = False
        return True

    def load(self, path):
        """Replace the buffer contents with a file from disk."""
        self.path = path
        text = path.read_text()
        self.lines = text.splitlines()
        if not self.lines:
            self.lines = [""]
        self.row = 0
        self.col = 0
        self.dirty = False


# ---------------------------------------------------------------------------
# Hook system – how extensions plug into the editor
# ---------------------------------------------------------------------------
#
# Hooks let extensions react to editor events (like "a key was pressed" or
# "the screen is about to be drawn"). Each hook is a Python function that
# gets called with (event_name, payload). Extensions register hooks via
# register_hook(), and the editor calls _dispatch() to run them.

# Global list of registered hooks. Each entry is (priority, callback, event).
_hooks = []


def register_hook(priority, callback, event=None):
    """Register a hook function.

    priority  – lower numbers run first (0 before 10 before 50, etc.)
    callback  – function(event_name, payload) to call
    event     – if given, only call this hook for that specific event name;
                if None, the hook is called for every event
    """
    _hooks.append((priority, callback, event))
    # Keep the list sorted so lower-priority hooks always run first
    _hooks.sort(key=lambda entry: entry[0])


def _dispatch(event, payload):
    """Run all hooks registered for the given event in priority order.

    If any hook returns True, we stop early and return True (meaning
    "this event was handled, don't do the default behavior").
    """
    for _priority, callback, hook_event in _hooks:
        # Skip hooks that are registered for a different event
        if hook_event is not None and hook_event != event:
            continue

        # Call the hook inside a try/except so one broken extension
        # doesn't crash the entire editor
        try:
            result = callback(event, payload)
            if result is True:
                return True
        except Exception as err:
            print(f"sweetroll: warning: hook error on '{event}': {err}",
                  file=sys.stderr)

    return False


# ---------------------------------------------------------------------------
# Editor – main loop, rendering, and keyboard handling
# ---------------------------------------------------------------------------

class Editor:
    """The main editor object. Owns the buffer, the curses window, and the
    event loop that reads keys and redraws the screen."""

    def __init__(self, path):
        self.buffer = Buffer(path)
        self.scroll_y = 0        # which line is at the top of the screen
        self.scroll_x = 0        # horizontal scroll offset
        self.message = ""        # one-line message (shown by status-bar extension)

        # Layout: extensions can request header/footer rows and left/right
        # columns. These dicts are recalculated every frame.
        self.layout_request = {"header": 0, "footer": 0, "left": 0, "right": 0}
        self.layout_rects = {}

        self.win = None          # the curses window (set in _init_curses)
        self.api = None          # the EditorAPI wrapper (set in run)

    # -- Curses setup --

    def _init_curses(self, win):
        """Configure curses for the editor."""
        curses.raw()               # pass all keys through (no signal handling)
        curses.curs_set(1)         # show the cursor
        curses.use_default_colors()
        curses.start_color()
        curses.set_escdelay(25)    # don't wait long after Escape key
        win.keypad(True)           # let curses decode arrow keys etc.
        self.win = win

    # -- Layout computation --

    def _compute_layout(self, screen_height, screen_width):
        """Divide the screen into regions: header, footer, left sidebar,
        right sidebar, and the main content area in the middle.

        Extensions request space during the "layout" hook (e.g. a status bar
        requests 1 footer row, line numbers request 5 left columns).  We then
        do the math to figure out where each region lands on screen.
        """
        # Reset requests so extensions can re-request each frame
        self.layout_request = {"header": 0, "footer": 0, "left": 0, "right": 0}
        _dispatch("layout", {"api": self.api})

        # Cap each region so the content area always gets at least 1 row
        header_rows = min(self.layout_request["header"], screen_height - 2)
        footer_rows = min(self.layout_request["footer"],
                          screen_height - header_rows - 1)
        content_height = screen_height - header_rows - footer_rows

        # Cap each region so the content area always gets at least 1 column
        left_cols = min(self.layout_request["left"], screen_width - 2)
        right_cols = min(self.layout_request["right"],
                         screen_width - left_cols - 1)
        content_width = screen_width - left_cols - right_cols

        # Safety: if the terminal is tiny, force at least 1 row/col for content
        if content_height < 1:
            content_height = 1
            footer_rows = screen_height - header_rows - 1
        if content_width < 1:
            content_width = 1
            right_cols = screen_width - left_cols - 1

        # Store each region as (y, x, height, width) — or None if empty
        self.layout_rects["content_rect"] = (
            header_rows, left_cols, content_height, content_width
        )

        if header_rows:
            self.layout_rects["header_rect"] = (
                0, 0, header_rows, screen_width
            )
        else:
            self.layout_rects["header_rect"] = None

        if footer_rows:
            self.layout_rects["footer_rect"] = (
                screen_height - footer_rows, 0, footer_rows, screen_width
            )
        else:
            self.layout_rects["footer_rect"] = None

        if left_cols:
            self.layout_rects["left_rect"] = (
                header_rows, 0, content_height, left_cols
            )
        else:
            self.layout_rects["left_rect"] = None

        if right_cols:
            self.layout_rects["right_rect"] = (
                header_rows, screen_width - right_cols, content_height, right_cols
            )
        else:
            self.layout_rects["right_rect"] = None

    # -- Scrolling --

    def _clamp_scroll(self, content_height, content_width):
        """Adjust scroll so the cursor is always visible on screen.

        If the cursor is above the visible area, scroll up.
        If the cursor is below the visible area, scroll down.
        Same idea horizontally.
        """
        # Vertical: keep cursor row inside [scroll_y, scroll_y + content_height)
        if self.buffer.row < self.scroll_y:
            self.scroll_y = self.buffer.row
        if self.buffer.row >= self.scroll_y + content_height:
            self.scroll_y = self.buffer.row - content_height + 1
        self.scroll_y = max(0, self.scroll_y)

        # Horizontal: keep cursor column inside [scroll_x, scroll_x + content_width)
        if self.buffer.col < self.scroll_x:
            self.scroll_x = self.buffer.col
        if self.buffer.col >= self.scroll_x + content_width:
            self.scroll_x = self.buffer.col - content_width + 1
        self.scroll_x = max(0, self.scroll_x)

    # -- Drawing --

    def _draw_text(self):
        """Draw the visible portion of the buffer into the content area."""
        content_y, content_x, content_height, content_width = (
            self.layout_rects["content_rect"]
        )

        for screen_row in range(content_height):
            line_index = self.scroll_y + screen_row

            # Only draw if this line exists in the buffer
            if line_index >= len(self.buffer.lines):
                continue

            # Slice the line to only the horizontally visible portion
            full_line = self.buffer.lines[line_index]
            visible_text = full_line[self.scroll_x:self.scroll_x + content_width]

            # curses can throw an error if we try to write past the edge
            # of the screen, so we wrap it in try/except
            try:
                self.win.addstr(content_y + screen_row, content_x, visible_text)
            except curses.error:
                pass

    def _position_cursor(self):
        """Move the terminal cursor to match the buffer cursor position."""
        content_y, content_x, _, _ = self.layout_rects["content_rect"]
        cursor_y = content_y + (self.buffer.row - self.scroll_y)
        cursor_x = content_x + (self.buffer.col - self.scroll_x)
        try:
            self.win.move(cursor_y, cursor_x)
        except curses.error:
            pass

    # -- Render pipeline --

    def redraw(self):
        """One frame of the render pipeline: layout -> scroll -> draw -> refresh."""
        screen_height, screen_width = self.win.getmaxyx()
        self.buffer.clamp_cursor()

        # Step 1: figure out where everything goes on screen
        self._compute_layout(screen_height, screen_width)
        _, _, content_height, content_width = self.layout_rects["content_rect"]

        # Step 2: adjust scroll so the cursor stays visible
        self._clamp_scroll(content_height, content_width)

        # Step 3: let extensions cancel the render if they want
        payload = {"api": self.api}
        if _dispatch("before_render", payload):
            return

        # Step 4: clear screen, draw text, let extensions draw overlays, refresh
        self.win.erase()
        self._draw_text()
        _dispatch("render_overlay", payload)
        self._position_cursor()
        self.win.refresh()
        _dispatch("after_render", payload)

    # -- Keyboard handling --

    def on_key(self, key):
        """Handle a single keypress. Returns "quit" to exit, True if handled."""
        # Let extensions handle the key first
        handled_by_extension = _dispatch("key", {"api": self.api, "key": key})

        # --- Quit and Save (always checked, even if an extension handled the key) ---

        if key == KEY_QUIT:
            if _dispatch("before_quit", {"api": self.api}):
                return True   # an extension cancelled the quit
            return "quit"

        if key == KEY_SAVE:
            save_payload = {"api": self.api}
            if not _dispatch("before_save", save_payload):
                if self.buffer.save():
                    _dispatch("saved", save_payload)
            return True

        # If an extension already handled this key, we're done
        if handled_by_extension:
            return True

        # --- Cursor movement ---

        if key == curses.KEY_UP:
            if self.buffer.row > 0:
                self.buffer.row -= 1
                self.buffer.clamp_cursor()
            return True

        if key == curses.KEY_DOWN:
            if self.buffer.row < len(self.buffer.lines) - 1:
                self.buffer.row += 1
                self.buffer.clamp_cursor()
            return True

        if key == curses.KEY_LEFT:
            if self.buffer.col > 0:
                self.buffer.col -= 1
            return True

        if key == curses.KEY_RIGHT:
            if self.buffer.col < len(self.buffer.lines[self.buffer.row]):
                self.buffer.col += 1
            return True

        if key == curses.KEY_HOME:
            self.buffer.col = 0
            return True

        if key == curses.KEY_END:
            self.buffer.col = len(self.buffer.lines[self.buffer.row])
            return True

        # --- Editing ---

        if key in BACKSPACE_CODES:
            self.buffer.backspace()
            return True

        if key == curses.KEY_DC:
            self.buffer.delete_char()
            return True

        if key in KEY_ENTER_CODES:
            self.buffer.enter()
            return True

        if key == KEY_TAB:
            self.buffer.insert_char("    ")
            return True

        # --- Printable characters ---

        if 32 <= key <= 126:
            self.buffer.insert_char(chr(key))
            return True

        return False

    def dispatch_key(self, key):
        """Fire a key event. Called by api.dispatch_key() — see that method."""
        _dispatch("key", {"api": self.api, "key": key})

    # -- Main loop --

    def _curses_main(self, win):
        """The function passed to curses.wrapper. Sets up the editor, then
        loops: draw the screen, wait for a key, handle it, repeat."""
        self._init_curses(win)
        self.api = EditorAPI(editor=self)
        _dispatch("init", {"api": self.api})

        while True:
            self.redraw()
            # getch() blocks until the user presses a key, then returns
            # an integer key code
            key = win.getch()
            result = self.on_key(key)
            if result == "quit":
                break

        _dispatch("shutdown", {"api": self.api})

    def run(self):
        """Start the editor inside curses and loop until the user quits."""
        try:
            # curses.wrapper handles setting up and tearing down the terminal
            curses.wrapper(self._curses_main)
        except KeyboardInterrupt:
            pass


def run(path=None):
    """Run the editor. `path` is an optional file to open."""
    if path:
        resolved = Path(path).resolve()
    else:
        resolved = None
    Editor(resolved).run()
