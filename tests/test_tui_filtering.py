
import re
import unittest

class PTYHandler:
    def __init__(self):
        # Using the same ANSI regex we fixed earlier
        self.ansi_escape = re.compile(
            r'(?:\x1B\]|\x9D).*?(?:\x1B\\|\x07)'
            r'|(?:\x1B\[|\x9B)[0-?]*[ -/]*[@-~]'
            r'|(?:\x1B[PX^_].*?\x1B\\)'
            r'|(?:\x1B[@-Z\\^_]|[\x80-\x9A\x9C-\x9F])',
            re.VERBOSE | re.DOTALL
        )

    def strip_ansi(self, text: str) -> str:
        text = self.ansi_escape.sub('', text)
        return self._clean_tui_artifacts(text)
    
    def _clean_tui_artifacts(self, text: str) -> str:
        if not text:
            return ""
        # The logic we just added
        text = re.sub(r'╭─── Claude Code.*?─╮', '', text, flags=re.DOTALL)
        text = re.sub(r'^\s*│\s*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'\[\d+B blob data\]', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text

class TestTUIFiltering(unittest.TestCase):
    def test_claude_header_removal(self):
        handler = PTYHandler()
        # Simulated header
        text = "╭─── Claude Code v2.1.29 ──────────────────────────────────────────────────────╮\n│\nActual Content"
        cleaned = handler._clean_tui_artifacts(text)
        print(f"Original: {repr(text)}")
        print(f"Cleaned: {repr(cleaned)}")
        self.assertNotIn("Claude Code v2.1.29", cleaned)
        self.assertIn("Actual Content", cleaned)

    def test_vertical_bars(self):
        handler = PTYHandler()
        text = "Content\n│\n│\nMore Content"
        cleaned = handler._clean_tui_artifacts(text)
        # Should collapse empty border lines
        self.assertIn("Content", cleaned)
        self.assertIn("More Content", cleaned)
        # Check excessive newlines are gone
        self.assertTrue(cleaned.count('\n') < 4) 

if __name__ == "__main__":
    unittest.main()
