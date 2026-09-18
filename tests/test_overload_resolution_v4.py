import textwrap

from token_saver.pack import build_context_pack, rank_files
from token_saver.repo_index import build_index


def _line(source: str, fragment: str) -> int:
    return next(
        number for number, value in enumerate(source.splitlines(), start=1)
        if fragment in value
    )


def _dapper_async_fixture() -> str:
    return textwrap.dedent("""
        using System;
        using System.Collections.Generic;
        using System.Data;
        using System.Threading.Tasks;

        public readonly struct CommandDefinition {}

        public static partial class SqlMapper {
            public static Task<IEnumerable<dynamic>> QueryAsync(
                this IDbConnection cnn, string sql, object param = null) => Work();

            public static Task<IEnumerable<dynamic>> QueryAsync(
                this IDbConnection cnn, CommandDefinition command) => Work();

            public static Task<IEnumerable<T>> QueryAsync<T>(
                this IDbConnection cnn, string sql, object param = null) => Work<T>();

            public static Task<T> QuerySingleAsync<T>(
                this IDbConnection cnn, string sql, object param = null) => One<T>();

            public static Task<int> ExecuteAsync(
                this IDbConnection cnn, string sql, object param = null) => Count();

            public static Task<int> ExecuteAsync(
                this IDbConnection cnn, CommandDefinition command) => Count();

            public static Task<IEnumerable<TReturn>> QueryAsync<TFirst, TSecond, TReturn>(
                this IDbConnection cnn, string sql,
                Func<TFirst, TSecond, TReturn> map, object param = null) => Work<TReturn>();

            public static Task<IEnumerable<TReturn>> QueryAsync<TReturn>(
                this IDbConnection cnn, string sql, Type[] types,
                Func<object[], TReturn> map, object param = null) => Work<TReturn>();
        }
    """)


def test_partial_class_exact_definition_beats_length_normalization(tmp_path):
    dapper = tmp_path / "Dapper"
    dapper.mkdir()
    filler = "\\n".join(
        f"        public static object Helper{i}(object value) => value;"
        for i in range(350)
    )
    sync = "public static partial class SqlMapper {\\n" + filler + textwrap.dedent("""
            public static int Execute(IDbConnection cnn, string sql, object param = null) => 1;
            public static IEnumerable<dynamic> Query(IDbConnection cnn, string sql, object param = null) => null;
            public static T QueryFirst<T>(IDbConnection cnn, string sql, object param = null) => default;
            public static object QuerySingle(IDbConnection cnn, Type type, string sql, object param = null) => null;
        }
    """)
    (dapper / "SqlMapper.cs").write_text(sync)
    (dapper / "SqlMapper.Async.cs").write_text(_dapper_async_fixture())
    (dapper / "CommandExecutor.cs").write_text(textwrap.dedent("""
        public class CommandExecutor {
            public int ExecuteSqlStringWithOptionalParameters(string sql, object parameters) => 1;
            public object QueryFirstSqlString(string sql) => null;
        }
    """))

    index = build_index(tmp_path, persist=False)
    cases = [
        "which SqlMapper Execute overload executes a SQL string with optional parameters",
        "where does SqlMapper Query return dynamic rows from a SQL string",
        "which generic SqlMapper QueryFirst<T> overload reads the first row from a SQL string",
        "which SqlMapper QuerySingle overload accepts a runtime Type plus SQL string",
    ]
    for query in cases:
        ranked = rank_files(
            tmp_path, query, index=index, changed_boost=False,
            feedback_boost=False, graph_hops=0,
        )
        assert ranked[0].rel == "Dapper/SqlMapper.cs"
        assert any(reason.startswith("structural-symbol:") for reason in ranked[0].reasons)


def test_explicit_generic_arity_selects_one_type_parameter_overload(tmp_path):
    source = _dapper_async_fixture()
    path = tmp_path / "SqlMapper.Async.cs"
    path.write_text(source)

    pack = build_context_pack(
        tmp_path,
        "which generic SqlMapper QueryAsync<T> overload asynchronously queries a SQL string into typed rows",
        max_tokens=1400,
        changed_boost=False,
    )

    expected = _line(source, "public static Task<IEnumerable<T>> QueryAsync<T>(")
    assert f"SqlMapper.Async.cs:SqlMapper.QueryAsync@{expected}" in pack.selected_symbol_identities


def test_command_definition_disambiguates_async_overload(tmp_path):
    source = _dapper_async_fixture()
    (tmp_path / "SqlMapper.Async.cs").write_text(source)

    pack = build_context_pack(
        tmp_path,
        "where does SqlMapper ExecuteAsync accept a CommandDefinition and execute it asynchronously",
        max_tokens=1400,
        changed_boost=False,
    )

    expected = _line(source, "this IDbConnection cnn, CommandDefinition command) => Count();") - 1
    assert f"SqlMapper.Async.cs:SqlMapper.ExecuteAsync@{expected}" in pack.selected_symbol_identities


def test_natural_language_input_count_disambiguates_multimap_generic_arity(tmp_path):
    source = _dapper_async_fixture()
    (tmp_path / "SqlMapper.Async.cs").write_text(source)

    pack = build_context_pack(
        tmp_path,
        "which SqlMapper QueryAsync overload asynchronously multi maps two input types into a return type from a SQL string",
        max_tokens=1600,
        changed_boost=False,
    )

    expected = _line(source, "public static Task<IEnumerable<TReturn>> QueryAsync<TFirst, TSecond, TReturn>(")
    assert f"SqlMapper.Async.cs:SqlMapper.QueryAsync@{expected}" in pack.selected_symbol_identities


def test_array_signature_features_select_runtime_type_array_overload(tmp_path):
    source = _dapper_async_fixture()
    (tmp_path / "SqlMapper.Async.cs").write_text(source)

    pack = build_context_pack(
        tmp_path,
        "which SqlMapper QueryAsync overload asynchronously multi maps a runtime Type array using an object array mapping function",
        max_tokens=1600,
        changed_boost=False,
    )

    expected = _line(source, "public static Task<IEnumerable<TReturn>> QueryAsync<TReturn>(")
    assert f"SqlMapper.Async.cs:SqlMapper.QueryAsync@{expected}" in pack.selected_symbol_identities


def test_csharp_partial_parse_recovery_keeps_valid_methods():
    from token_saver.repo_index import record_for_text

    source = textwrap.dedent("""
        public static partial class SqlMapper {
            public static int Execute(string sql) => 1;
            public static T QueryFirst<T>(string sql) => default;
        }

        ??? unsupported_future_syntax
    """)
    record = record_for_text("SqlMapper.cs", source)
    qualified = {item.qualified for item in record.definitions or []}
    assert "SqlMapper.Execute" in qualified
    assert "SqlMapper.QueryFirst" in qualified


def test_explicit_generic_syntax_in_query_sets_requested_arity():
    # Regression: the explicit `Name<T>` branch used `\\b`/`\\s` inside an
    # rf-string, i.e. a literal backslash, so it could never match and only the
    # "two input types ... return type" wording path ever produced an arity.
    from token_saver.pack import _query_generic_arity

    assert _query_generic_arity("use QueryAsync<T> to map rows", "QueryAsync") == 1
    assert _query_generic_arity("call Query<A, B> for two types", "Query") == 2
    assert _query_generic_arity("QueryAsync<TFirst, TSecond, TReturn> joins", "QueryAsync") == 3
    assert _query_generic_arity("Query<T> ignores an unrelated name", "Execute") is None
    assert _query_generic_arity("no generic syntax here", "Query") is None
    # The wording path must keep working alongside the explicit one.
    assert _query_generic_arity(
        "overload with two input types and a return type", "Query"
    ) == 3


def test_explicit_generic_query_prefers_generic_overload_over_nongeneric(tmp_path):
    source = _dapper_async_fixture()
    (tmp_path / "SqlMapper.Async.cs").write_text(source)

    pack = build_context_pack(
        tmp_path, "QueryAsync<T> rows", max_tokens=3000,
        changed_boost=False, persist_index=False,
    )

    generic_lines = {
        _line(source, "QueryAsync<T>("),
        _line(source, "QuerySingleAsync<T>("),
        _line(source, "QueryAsync<TReturn>("),
    }
    # identities[0] is the container; [1] is the best-ranked member after it.
    best_member_line = int(pack.selected_symbol_identities[1].rsplit("@", 1)[1])
    assert best_member_line in generic_lines
