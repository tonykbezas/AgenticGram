
import re
import unittest

class PTYHandler:
    def __init__(self):
        self.ansi_escape = re.compile(
            r'(?:\x1B\]|\x9D).*?(?:\x1B\\|\x07)'  # OSC
            r'|(?:\x1B\[|\x9B)[0-?]*[ -/]*[@-~]'  # CSI
            r'|(?:\x1B[PX^_].*?\x1B\\)'           # DCS/PM/APC
            r'|(?:\x1B[@-Z\\^_]|[\x80-\x9A\x9C-\x9F])', # Generic (excluding [ and ])
            re.VERBOSE | re.DOTALL
        )

    def strip_ansi(self, text: str) -> str:
        return self.ansi_escape.sub('', text)

class TestANSIStripping(unittest.TestCase):
    def test_standard_colors(self):
        handler = PTYHandler()
        text = "\x1b[31mRed\x1b[0m"
        self.assertEqual(handler.strip_ansi(text), "Red")

    def test_osc_sequence_stripping(self):
        """This test checks if OSC sequences are stripped"""
        handler = PTYHandler()
        # OSC sequence: ESC ] 9;4;1;20 BEL
        text = "Prefix\x1b]9;4;1;20\x07Suffix" 
        stripped = handler.strip_ansi(text)
        print(f"Original: {repr(text)}")
        print(f"Stripped: {repr(stripped)}")
        
        self.assertEqual(stripped, "PrefixSuffix")
        print("Verification SUCCESS: OSC sequence completely removed.")

    def test_complex_mixed(self):
        handler = PTYHandler()
        # Mix of color and OSC
        text = "\x1b[1mTitle:\x1b[0m \x1b]0;Window Title\x07Content"
        stripped = handler.strip_ansi(text)
        self.assertEqual(stripped, "Title: Content")

if __name__ == "__main__":
    unittest.main()
