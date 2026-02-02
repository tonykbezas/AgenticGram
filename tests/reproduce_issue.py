
import re
import sys
import unittest

# Copying the class structure minimally for testing
class PTYHandler:
    def __init__(self):
        # The ORIGINAL regex for reproduction
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    def strip_ansi(self, text: str) -> str:
        return self.ansi_escape.sub('', text)

class TestANSIStripping(unittest.TestCase):
    def test_standard_colors(self):
        handler = PTYHandler()
        text = "\x1b[31mRed\x1b[0m"
        self.assertEqual(handler.strip_ansi(text), "Red")

    def test_osc_sequence_failure(self):
        """This test is EXPECTED TO FAIL with the old regex"""
        handler = PTYHandler()
        # OSC sequence: ESC ] 9;4;0 ST (where ST is usually ESC \ or BEL)
        # 9;4;1 and 9;4;0 are often used for Taskbar progress state in terminals like iTerm2 or Windows Terminal
        text = "Prefix\x1b]9;4;1;20\x07Suffix" 
        stripped = handler.strip_ansi(text)
        print(f"Original: {repr(text)}")
        print(f"Stripped: {repr(stripped)}")
        
        # With the bug, we expect specific garbage, or at least not clean text
        if "9;4;1;20" in stripped:
             print("Reproduction SUCCESS: Garbage remains in output.")
        else:
             print("Reproduction FAILED: Output was clean (unexpected for old regex).")

if __name__ == "__main__":
    unittest.main()
