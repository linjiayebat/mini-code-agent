import shutil
import subprocess

from mini_code_agent import __version__
from mini_code_agent.testing import PytestRunner
from mini_code_agent.tools import RunTestsTool


def verify_installed_package() -> None:
    assert PytestRunner.__name__ == "PytestRunner"
    assert RunTestsTool.__name__ == "RunTestsTool"
    executable = shutil.which("mini-code-agent")
    assert executable is not None
    result = subprocess.run(
        [executable, "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == __version__


def test_installed_package_starts() -> None:
    verify_installed_package()


if __name__ == "__main__":
    verify_installed_package()
