"""Editor: buffer, hook system, curses main loop, layout, rendering, key handling."""

import curses
import sys
from pathlib import Path

from sweetroll.api import EditorAPI

_KEY_QUIT = 17  # Ctrl+Q
_KEY_SAVE = 19  # Ctrl+S


# --- Buffer ---

class Buffer:
    """Single buffer: list of lines, 0-based row/col."""

    def __init__(self, path: Path | None = None):
        self.path = path
        if path and path.exists():
            self.lines = path.read_text().splitlines() or [""]
        else:
            self.lines = [""]
        self.row = 0
        self.col = 0
        self.dirty = False

    def clamp_cursor(self):
        self.row = max(0, min(self.row, len(self.lines) - 1))
        self.col = max(0, min(self.col, len(self.lines[self.row])))

    def insert_char(self, ch: str):
        self.lines[self.row] = self.lines[self.row][: self.col] + ch + self.lines[self.row][self.col :]
        self.col += len(ch)
        self.dirty = True

    def backspace(self):
        if self.col > 0:
            self.lines[self.row] = self.lines[self.row][: self.col - 1] + self.lines[self.row][self.col :]
            self.col -= 1
            self.dirty = True
        elif self.row > 0:
            self.col = len(self.lines[self.row - 1])
            self.lines[self.row - 1] += self.lines[self.row]
            self.lines.pop(self.row)
            self.row -= 1
            self.dirty = True

    def delete_char(self):
        if self.col < len(self.lines[self.row]):
            self.lines[self.row] = self.lines[self.row][: self.col] + self.lines[self.row][self.col + 1 :]
            self.dirty = True
        elif self.row < len(self.lines) - 1:
            self.lines[self.row] += self.lines[self.row + 1]
            self.lines.pop(self.row + 1)
            self.dirty = True

    def enter(self):
        tail = self.lines[self.row][self.col :]
        self.lines[self.row] = self.lines[self.row][: self.col]
        self.lines.insert(self.row + 1, tail)
        self.row += 1
        self.col = 0
        self.dirty = True

    def save(self) -> bool:
        if not self.path:
            return False
        self.path.write_text("\n".join(self.lines) + "\n")
        self.dirty = False
        return True

    def load(self, path: Path):
        self.path = path
        self.lines = path.read_text().splitlines() or [""]
        self.row = 0
        self.col = 0
        self.dirty = False


# --- Hook system ---

# List of (priority, callback, event). Callbacks can return True to mean "handled, stop".
_hooks = []


def register_hook(priority: int, callback, event: str | None = None):
    """Register a hook. Lower priority runs first. Callback receives (event_name, payload).
    If event is given, the hook is only called for that event."""
    _hooks.append((priority, callback, event))
    _hooks.sort(key=lambda x: x[0])


def _dispatch(event: str, payload: dict) -> bool:
    """Run hooks in priority order. Returns True if any hook returned True (handled)."""
    for _, cb, ev in _hooks:
        if ev is not None and ev != event:
            continue
        try:
            if cb(event, payload) is True:
                return True
        except Exception as e:
            print(f"sweetroll: warning: hook error on '{event}': {e}", file=sys.stderr)
    return False


# --- Editor ---

class Editor:
    def __init__(self, path: Path | None):
        self.buffer = Buffer(path)
        self.scroll_y = 0
        self.scroll_x = 0
        self.message = ""
        self.layout_request = {"header": 0, "footer": 0, "left": 0, "right": 0}
        self.layout_rects = {}
        self.win = None
        self.api: EditorAPI | None = None

    def _init_curses(self, win):
        curses.raw()
        curses.curs_set(1)
        curses.use_default_colors()
        curses.start_color()
        curses.set_escdelay(25)
        win.keypad(True)
        self.win = win

    def _compute_layout(self, h: int, w: int):
        self.layout_request = {"header": 0, "footer": 0, "left": 0, "right": 0}
        _dispatch("layout", {"api": self.api})

        header_rows = min(self.layout_request["header"], h - 2)
        footer_rows = min(self.layout_request["footer"], h - header_rows - 1)
        content_height = h - header_rows - footer_rows
        left_cols = min(self.layout_request["left"], w - 2)
        right_cols = min(self.layout_request["right"], w - left_cols - 1)
        content_width = w - left_cols - right_cols
        if content_height < 1:
            content_height = 1
            footer_rows = h - header_rows - 1
        if content_width < 1:
            content_width = 1
            right_cols = w - left_cols - 1

        self.layout_rects["content_rect"] = (header_rows, left_cols, content_height, content_width)
        self.layout_rects["header_rect"] = (0, 0, header_rows, w) if header_rows else None
        self.layout_rects["footer_rect"] = (h - footer_rows, 0, footer_rows, w) if footer_rows else None
        self.layout_rects["left_rect"] = (header_rows, 0, content_height, left_cols) if left_cols else None
        self.layout_rects["right_rect"] = (header_rows, w - right_cols, content_height, right_cols) if right_cols else None

    def _clamp_scroll(self, ch: int, cw: int):
        if self.buffer.row < self.scroll_y:
            self.scroll_y = self.buffer.row
        if self.buffer.row >= self.scroll_y + ch:
            self.scroll_y = self.buffer.row - ch + 1
        self.scroll_y = max(0, self.scroll_y)

        if self.buffer.col < self.scroll_x:
            self.scroll_x = self.buffer.col
        if self.buffer.col >= self.scroll_x + cw:
            self.scroll_x = self.buffer.col - cw + 1
        self.scroll_x = max(0, self.scroll_x)

    def _draw_text(self):
        cy, cx, ch, cw = self.layout_rects["content_rect"]
        for i in range(ch):
            line_idx = self.scroll_y + i
            if line_idx < len(self.buffer.lines):
                line = self.buffer.lines[line_idx][self.scroll_x : self.scroll_x + cw]
                try:
                    self.win.addstr(cy + i, cx, line)
                except curses.error:
                    pass

    def _position_cursor(self):
        cy, cx, _, _ = self.layout_rects["content_rect"]
        try:
            self.win.move(cy + (self.buffer.row - self.scroll_y), cx + (self.buffer.col - self.scroll_x))
        except curses.error:
            pass

    def redraw(self):
        h, w = self.win.getmaxyx()
        self.buffer.clamp_cursor()
        self._compute_layout(h, w)
        _, _, ch, cw = self.layout_rects["content_rect"]
        self._clamp_scroll(ch, cw)

        payload = {"api": self.api}
        if _dispatch("before_render", payload):
            return

        self.win.erase()
        self._draw_text()
        _dispatch("render_overlay", payload)
        self._position_cursor()
        self.win.refresh()
        _dispatch("after_render", payload)

    def on_key(self, key: int):
        hook_handled = _dispatch("key", {"api": self.api, "key": key})

        if key == _KEY_QUIT:
            if _dispatch("before_quit", {"api": self.api}):
                return True  # A hook cancelled quit
            return "quit"
        if key == _KEY_SAVE:
            save_payload = {"api": self.api}
            if not _dispatch("before_save", save_payload):
                if self.buffer.save():
                    _dispatch("saved", save_payload)
            return True

        if hook_handled:
            return True
        if key == curses.KEY_UP and self.buffer.row > 0:
            self.buffer.row -= 1
            self.buffer.clamp_cursor()
            return True
        if key == curses.KEY_DOWN and self.buffer.row < len(self.buffer.lines) - 1:
            self.buffer.row += 1
            self.buffer.clamp_cursor()
            return True
        if key == curses.KEY_LEFT and self.buffer.col > 0:
            self.buffer.col -= 1
            return True
        if key == curses.KEY_RIGHT and self.buffer.col < len(self.buffer.lines[self.buffer.row]):
            self.buffer.col += 1
            return True
        if key in (curses.KEY_BACKSPACE, 127):
            self.buffer.backspace()
            return True
        if key == curses.KEY_DC:
            self.buffer.delete_char()
            return True
        if key in (curses.KEY_ENTER, 10, 13):
            self.buffer.enter()
            return True
        if key == curses.KEY_HOME:
            self.buffer.col = 0
            return True
        if key == curses.KEY_END:
            self.buffer.col = len(self.buffer.lines[self.buffer.row])
            return True
        if 32 <= key <= 126:
            self.buffer.insert_char(chr(key))
            return True
        if key == 9:  # Tab
            self.buffer.insert_char("    ")
            return True
        return False

    def run(self):
        def main(win):
            self._init_curses(win)
            self.api = EditorAPI(editor=self)
            _dispatch("init", {"api": self.api})
            while True:
                self.redraw()
                key = win.getch()
                result = self.on_key(key)
                if result == "quit":
                    break
            _dispatch("shutdown", {"api": self.api})

        try:
            curses.wrapper(main)
        except KeyboardInterrupt:
            pass


def run(path: str | Path | None = None):
    """Run the editor. path is optional file to open."""
    Editor(Path(path).resolve() if path else None).run()
