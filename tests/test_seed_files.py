import pytest

from messageboardbench.task import validate_seed_files


@pytest.mark.parametrize("name", ["../escape.py", "/tmp/file", "a/b", ".", "..", "", "a\\b"])
def test_seeds_cannot_escape_scratch(name):
    with pytest.raises(ValueError):
        validate_seed_files({name: "content"})


def test_seed_is_copied_without_changing_content():
    files = {"reference.py": "# agent-written\ndef f(): return 3\n"}
    assert validate_seed_files(files) == files
    assert validate_seed_files(files) is not files


def test_byte_limit_handles_multibyte_text():
    with pytest.raises(ValueError):
        validate_seed_files({"reference.py": "é" * 40000})
