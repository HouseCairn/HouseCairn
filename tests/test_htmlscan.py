import pytest

from tests.htmlscan import inline_code_problems, script_tags


@pytest.mark.parametrize(
    "html",
    [
        "<SCRIPT>alert(1)</SCRIPT>",
        "<Script>alert(1)</Script>",
        "<Style>p{color:red}</Style>",
        '<p STYLE="color:red">x</p>',
        '<button ONCLICK="alert(1)">x</button>',
    ],
)
def test_mixed_case_inline_code_is_detected(html: str) -> None:
    assert inline_code_problems(html)


def test_all_three_kinds_are_reported_together() -> None:
    html = "<SCRIPT>alert(1)</SCRIPT><Style>a{}</Style><a ONCLICK=x>y</a>"
    problems = inline_code_problems(html)
    assert any(p.startswith("inline script") for p in problems)
    assert "style tag" in problems
    assert "event handler: onclick" in problems


def test_external_script_and_json_block_are_accepted() -> None:
    html = '<SCRIPT SRC="/a.js"></SCRIPT><script type="application/json">{}</script>'
    assert inline_code_problems(html) == []
    assert len(script_tags(html)) == 2
