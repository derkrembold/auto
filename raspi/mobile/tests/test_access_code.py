import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from access_code import derive_key, generate_code, ALPHABET


def test_short_code_compatible_vector():
    assert derive_key('abcd-2345') == derive_key('ABCD2345')
    assert derive_key('ABCD2345').hex() == 'd82b612e9353915b09090d57cf69bf16'


def test_generated_codes_are_eight_unambiguous_characters():
    code = generate_code()
    assert len(code) == 8 and all(char in ALPHABET for char in code)
