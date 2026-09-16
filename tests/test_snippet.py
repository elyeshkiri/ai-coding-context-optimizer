import textwrap

from token_saver.snippet import extract_symbol


def test_python_function():
    src = textwrap.dedent(
        """
        import os

        def handler(req):
            x = 1
            return x

        def other():
            return 2
        """
    )
    hit = extract_symbol(src, ".py", "handler")
    assert hit is not None
    text, start, end = hit
    assert "def handler" in text
    assert "def other" not in text
    assert start < end


def test_missing_symbol():
    assert extract_symbol("def foo():\n    pass\n", ".py", "bar") is None


def test_js_function():
    src = "export function load(id) {\n  return id;\n}\n\nexport function save() {}\n"
    hit = extract_symbol(src, ".js", "load")
    assert hit is not None
    assert "function load" in hit[0]
    assert "function save" not in hit[0]
