"""Focused page tests bypass onboarding; test_onboarding covers real startup."""
from app.tui.ui import Terminal
from pathlib import Path

class ReadyTerminal(Terminal):
    CSS_PATH = Path(__file__).resolve().parents[1] / "app/tui/tui.tcss"
    def initialize_startup(self):
        pass
