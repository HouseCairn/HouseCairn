import json
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from housecairn.core import design


def test_generated_css_is_up_to_date() -> None:
    assert design.CSS_PATH.read_text(encoding="utf-8") == design.expected_css()


def test_check_command_passes() -> None:
    call_command("build_design_tokens", "--check")


def test_logo_palette_is_present() -> None:
    colors = design.load_tokens()["color"]
    assert colors["slate"] == "#1F3A3D"
    assert colors["sand"] == "#C8A27C"
    assert colors["sage"] == "#8FA39A"
    assert colors["stone"] == "#5F726E"
    assert {"font", "space", "radius"} <= set(design.load_tokens())


def test_css_variables() -> None:
    css = design.render_css({"color": {"slate": "#1F3A3D"}})
    assert "  --hc-color-slate: #1F3A3D;\n" in css


def test_command_writes_and_detects_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "css" / "tokens.css"
    monkeypatch.setattr(design, "CSS_PATH", target)
    with pytest.raises(CommandError):
        call_command("build_design_tokens", "--check")
    call_command("build_design_tokens")
    assert target.read_text(encoding="utf-8") == design.expected_css()
    target.write_text("/* edited */", encoding="utf-8")
    with pytest.raises(CommandError):
        call_command("build_design_tokens", "--check")


@pytest.mark.parametrize(
    "data",
    [{"Bad Group": {"a": "1"}}, {"color": {"a": 1}}, {"color": "red"}, {"color": {"A B": "1"}}],
)
def test_invalid_tokens_are_rejected(tmp_path: Path, data: dict[str, object]) -> None:
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid token"):
        design.load_tokens(path)
