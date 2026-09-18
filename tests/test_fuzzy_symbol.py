import textwrap

from token_saver.context_browser import browse_context
from token_saver.pack import build_context_pack, rank_files


def test_repo_scope_typo_normalization_can_surface_symbol_file(tmp_path):
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'views.py').write_text(textwrap.dedent('''
        def renderTemplate(template, context):
            return template.format(**context)
    '''))
    (src / 'template_notes.py').write_text(textwrap.dedent('''
        def describe_template(template):
            # template template template documentation helper
            return template
    '''))

    ranked = rank_files(
        tmp_path,
        'rendr template',
        changed_boost=False,
    )

    assert 'src/views.py' in {item.rel for item in ranked[:2]}


def test_within_file_fuzzy_fallback_prefers_typo_matched_identifier(tmp_path):
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'views.py').write_text(textwrap.dedent('''
        def templateReader(template):
            return template

        def renderTemplate(template, context):
            return template.format(**context)
    '''))

    pack = build_context_pack(
        tmp_path,
        'rendr template output',
        max_tokens=700,
        changed_boost=False,
    )

    assert any(
        label.startswith('src/views.py:renderTemplate@')
        for label in pack.selected_symbols
    )


def test_context_browser_reuses_real_ranker_and_reports_fuzzy_correction(tmp_path):
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'session.py').write_text(textwrap.dedent('''
        def refreshSession(token):
            return rotate_token(token)
    '''))

    report = browse_context(
        tmp_path,
        'refresh sesion token',
        max_files=3,
        changed_boost=False,
    )

    assert report['files'][0]['path'] == 'src/session.py'
    assert any('refreshSession@' in label for label in report['files'][0]['symbols'])
    assert report['files'][0]['fuzzy_corrections']['sesion']['term'] == 'session'
    assert 'rotate_token' in report['files'][0]['preview']
