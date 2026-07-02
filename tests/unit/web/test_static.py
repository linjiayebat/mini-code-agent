from importlib import resources


def static_text(name: str) -> str:
    return (
        resources.files("mini_code_agent.web").joinpath("static", name).read_text(encoding="utf-8")
    )


def test_frontend_resources_are_packaged_without_remote_dependencies() -> None:
    html = static_text("index.html")
    css = static_text("styles.css")
    javascript = static_text("app.js")
    combined = "\n".join((html, css, javascript))

    assert "https://" not in combined
    assert "http://" not in combined
    assert "cdn" not in combined.lower()


def test_frontend_contains_workbench_landmarks_and_controls() -> None:
    html = static_text("index.html")

    for marker in (
        'id="session-rail"',
        'id="transcript"',
        'id="prompt-input"',
        'id="run-button"',
        'id="cancel-button"',
        'id="inspector"',
        'id="activity-list"',
        'id="approval-panel"',
        'id="changes-panel"',
    ):
        assert marker in html
    assert 'type="password"' not in html
    assert "api key" not in html.lower()


def test_frontend_renders_untrusted_values_without_dynamic_html() -> None:
    javascript = static_text("app.js")

    assert ".textContent" in javascript
    assert "innerHTML" not in javascript
    assert "insertAdjacentHTML" not in javascript


def test_styles_define_desktop_and_mobile_workbench_tracks() -> None:
    css = static_text("styles.css")

    assert "--topbar-height" in css
    assert "grid-template-columns" in css
    assert "@media (max-width: 720px)" in css
