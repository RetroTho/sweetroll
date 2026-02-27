"""Sweetroll: a minimal, extensible terminal text editor."""

__all__ = ["run", "register_hook", "EditorAPI"]

from sweetroll.api import EditorAPI
from sweetroll.editor import register_hook
from sweetroll.editor import run
