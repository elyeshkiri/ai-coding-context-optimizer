"""Regressions for the code map."""

import textwrap

from acco.skeleton import line_is_signature, skeletonize, skeletonize_text


def _py(src: str) -> str:
    return skeletonize(textwrap.dedent(src), ".py")


def test_multiline_signature_is_kept_whole():
    """Regression: `def f(` was emitted with its parameters omitted."""
    out = _py(
        '''
        def long_signature(
            alpha: int,
            beta: str = "x",
        ) -> dict:
            return {}
        '''
    )
    assert "def long_signature(alpha: int, beta: str='x') -> dict:" in out


def test_python_comments_are_not_treated_as_headings():
    """Regression: the markdown-heading pattern matched every `# ` comment."""
    out = _py(
        """
        def f():
            # an internal comment nobody needs during navigation
            return 1
        """
    )
    assert "internal comment" not in out


def test_async_def_and_decorators():
    out = _py(
        """
        @app.route("/x")
        async def handler(req, *, timeout: float = 1.0) -> bytes:
            return b""
        """
    )
    assert "@app.route('/x')" in out
    assert "async def handler(req, *, timeout: float=1.0) -> bytes:" in out


def test_class_bases_methods_and_fields():
    out = _py(
        """
        class Repo(Base, metaclass=Meta):
            table: str = "orders"
            def save(self, row: dict) -> int:
                return 0
        """
    )
    assert "class Repo(Base, metaclass=Meta):" in out
    assert "table: str = 'orders'" in out
    assert "def save(self, row: dict) -> int:" in out


def test_large_collection_is_summarised_not_left_dangling():
    """Regression: `NAMES = {` was emitted with the members omitted."""
    src = "NAMES = {\n" + "".join(f'    "n{i}",\n' for i in range(20)) + "}\n"
    out = skeletonize(src, ".py")
    assert "NAMES = {…20 items}" in out
    assert not out.strip().endswith("{")


def test_local_variables_are_dropped_but_constants_kept():
    out = _py(
        """
        MAX = 10
        counter = 0
        def f():
            pass
        """
    )
    assert "MAX = 10" in out
    assert "counter" not in out


def test_main_guard_is_kept():
    out = _py(
        """
        def main():
            pass
        if __name__ == "__main__":
            raise SystemExit(main())
        """
    )
    assert "if __name__ == '__main__':" in out


def test_docstrings_off_by_default_and_on_by_request():
    src = '''
    def f():
        """Summary line.

        More detail.
        """
    '''
    assert "Summary line" not in skeletonize(textwrap.dedent(src), ".py")
    with_doc = skeletonize(textwrap.dedent(src), ".py", docstrings=True)
    assert "Summary line" in with_doc
    assert "More detail" not in with_doc


def test_syntax_error_falls_back_to_patterns():
    out = skeletonize("def f(:\nimport os\n", ".py")
    assert "import os" in out


def test_python_map_is_smaller_than_source():
    src = "\n".join(f"def f{i}(a, b):\n    return a + b + {i}\n" for i in range(50))
    assert len(skeletonize(src, ".py")) < len(src)


# ------------------------------------------------------------- other langs


def test_typescript_declarations_are_matched():
    """Regression: `export async function` and arrow consts were both missed."""
    src = textwrap.dedent(
        """
        export async function fetchUser(id: string): Promise<User> {
          const r = await fetch(url);
          return r.json();
        }
        export const helper = (x: number) => x + 1;
        const inner = async (y) => y;
        export default class Widget extends Base {
          render(): Node {
            return null;
          }
        }
        """
    )
    out = skeletonize_text(src, ".ts")
    assert "export async function fetchUser(id: string): Promise<User> {" in out
    assert "export const helper = (x: number) => x + 1;" in out
    assert "const inner = async (y) => y;" in out
    assert "export default class Widget extends Base {" in out
    assert "render(): Node {" in out


def test_single_line_method_body_is_kept():
    out = skeletonize_text("class A {\n  render() { return null; }\n}\n", ".ts")
    assert "render()" in out


def test_calls_are_not_mistaken_for_declarations():
    for line in (
        'expect(foo).toBe(bar);',
        'describe("x", () => {',
        'arr.map(x => {',
        'doThing(a, b);',
    ):
        assert not line_is_signature(line, ".ts"), line


def test_control_flow_is_not_mistaken_for_a_method():
    src = "class A {\n  if (x) {\n    y();\n  }\n}\n"
    out = skeletonize_text(src, ".ts")
    assert "if (x)" not in out


def test_rust_and_go_declarations():
    assert line_is_signature("pub async fn go() -> Result<()> {", ".rs")
    assert line_is_signature("pub struct Config {", ".rs")
    assert line_is_signature("impl<T> Handler for Server<T> {", ".rs")
    assert line_is_signature("func (s *Server) Handle(w http.ResponseWriter) {", ".go")
    assert line_is_signature("#[derive(Debug)]", ".rs")


def test_markdown_keeps_headings_only():
    src = "# Title\n\nsome prose here\n\n```bash\nrun me\n```\n\n## Section\n"
    out = skeletonize_text(src, ".md")
    assert "# Title" in out
    assert "## Section" in out
    assert "some prose" not in out
    assert "```" not in out, "empty code fences are pure noise in a map"


def test_markdown_heading_rule_does_not_leak_into_code():
    assert not line_is_signature("# a shell comment", ".sh")
    assert line_is_signature("# a heading", ".md")


def test_markdown_ignores_comments_inside_code_fences():
    """Regression: `# run this` in a bash block was promoted to a heading."""
    src = "## Commands\n\n```bash\n# Compact map of the repo\nacco map .\n```\n"
    out = skeletonize_text(src, ".md")
    assert "## Commands" in out
    assert "Compact map of the repo" not in out


# ------------------------------------------------------------ gitignore


def _git_repo(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True,
                   capture_output=True)
    return tmp_path


def test_gitignored_files_stay_out_of_the_map(tmp_path):
    """Regression: a hardcoded skip list drifts from every real project."""
    from acco.skeleton import walk_repo

    repo = _git_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "generated").mkdir()
    (repo / "src" / "real.py").write_text("def real(): pass\n")
    (repo / "generated" / "machine.py").write_text("def generated(): pass\n")
    (repo / "artifact.py").write_text("def artifact(): pass\n")
    (repo / ".gitignore").write_text("generated/\nartifact.py\n")

    tracked = {p.name for p in walk_repo(repo)}
    naive = {p.name for p in walk_repo(repo, use_gitignore=False)}
    assert tracked == {"real.py"}
    assert {"machine.py", "artifact.py"} <= naive


def test_a_non_git_directory_still_walks(tmp_path):
    from acco.skeleton import walk_repo

    (tmp_path / "a.py").write_text("def f(): pass\n")
    assert [p.name for p in walk_repo(tmp_path)] == ["a.py"]


def test_gitignore_can_be_switched_off(tmp_path):
    from acco.skeleton import build_map

    repo = _git_repo(tmp_path)
    (repo / "keep.py").write_text("def keep(): pass\n")
    (repo / "skip.py").write_text("def skip(): pass\n")
    (repo / ".gitignore").write_text("skip.py\n")
    assert "skip.py" not in build_map(repo)
    assert "skip.py" in build_map(repo, use_gitignore=False)


# ------------------------------------------------- line-number gutter

PY_SRC = """import os


CONST = 1


class Thing:
    def method(self, a):
        x = 1
        return x


def top(b):
    return b
"""


def _gutter(text):
    """(line number, code) for every numbered row of an outline."""
    rows = []
    for line in text.splitlines():
        num, _, code = line.partition("|")
        if num.strip():
            rows.append((int(num), code))
    return rows


def test_gutter_points_at_real_source_lines():
    """Ranges have to be right or the outline sends you to the wrong place."""
    src = PY_SRC.splitlines()
    for num, code in _gutter(skeletonize(PY_SRC, ".py", line_numbers=True)):
        assert code.strip().rstrip(":") in src[num - 1], f"line {num} mismatch"


def test_gutter_is_off_by_default():
    """map output must not change: it pays for every character it prints."""
    assert "|" not in skeletonize(PY_SRC, ".py").splitlines()[0]


def test_gutter_works_on_the_regex_path():
    js = "const a = 1;\nexport function go(x) {\n  return x;\n}\n"
    rows = _gutter(skeletonize(js, ".js", line_numbers=True))
    assert any(n == 2 and c.startswith("export function go(x)") for n, c in rows)


def test_omission_markers_keep_the_gutter_aligned():
    out = skeletonize(PY_SRC, ".py", line_numbers=True)
    widths = {len(ln.partition("|")[0]) for ln in out.splitlines() if ln.strip()}
    assert len(widths) == 1, "every row shares one gutter width"


def test_gutter_survives_a_file_the_parser_rejects():
    """Falls back to the regex path, and still numbers what it emits."""
    broken = "def ok(:\nclass Half(\ndef later(x):\n    pass\n"
    rows = _gutter(skeletonize(broken, ".py", line_numbers=True))
    assert rows, "fallback still produced numbered rows"
    assert all(1 <= n <= 4 for n, _ in rows)
