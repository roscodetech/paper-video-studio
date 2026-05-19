import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "skills" / "paper-cli" / "paper_video.py"


def test_edit_subcommand_help_lists_work_flag():
    result = subprocess.run(
        [sys.executable, str(CLI), "edit", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--work" in result.stdout


def test_edit_subcommand_errors_without_work_dir():
    result = subprocess.run(
        [sys.executable, str(CLI), "edit"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "--work" in (result.stderr + result.stdout).lower()
