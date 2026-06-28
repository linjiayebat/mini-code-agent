from mini_code_agent import __version__


def test_package_exports_release_version() -> None:
    assert __version__ == "0.1.0a0"
