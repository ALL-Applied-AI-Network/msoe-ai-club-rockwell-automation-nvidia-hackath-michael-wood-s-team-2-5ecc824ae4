"""Every command-line script must at least compile; nothing else imports them."""

import py_compile
from pathlib import Path

import pytest

SCRIPTS = sorted((Path(__file__).resolve().parents[1] / "scripts").glob("*.py"))


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_compiles(script, tmp_path):
    py_compile.compile(str(script), cfile=str(tmp_path / "compiled.pyc"), doraise=True)
