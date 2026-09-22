use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

use pyo3::prelude::*;
use regex::Regex;

#[pyfunction]
fn estimate_tokens(text: &str, ratio: f64) -> PyResult<usize> {
    if text.is_empty() {
        return Ok(0);
    }
    if !ratio.is_finite() || ratio <= 0.0 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "ratio must be a positive finite number",
        ));
    }
    let chars = text.chars().count() as f64;
    Ok(((chars / ratio) as usize).max(1))
}

#[pyfunction]
fn identifier_tokens(text: &str) -> PyResult<Vec<String>> {
    static IDENT: OnceLock<Regex> = OnceLock::new();
    let pattern =
        IDENT.get_or_init(|| Regex::new(r"\b[A-Za-z_$][\w$]*\b").expect("static identifier regex"));
    let mut out: HashSet<String> = pattern
        .find_iter(text)
        .map(|matched| matched.as_str())
        .filter(|value| value.chars().count() > 2)
        .map(str::to_lowercase)
        .collect();
    let mut values: Vec<String> = out.drain().collect();
    values.sort();
    Ok(values)
}

#[pyfunction]
fn bm25_score(
    counts: HashMap<String, usize>,
    q_terms: Vec<String>,
    doc_freq: HashMap<String, usize>,
    length: usize,
    avg_len: f64,
    n_docs: usize,
) -> PyResult<(f64, usize)> {
    if !avg_len.is_finite() || avg_len <= 0.0 || n_docs == 0 {
        return Ok((0.0, 0));
    }
    let mut score = 0.0_f64;
    let mut matched = 0_usize;
    let k1 = 1.5_f64;
    let b = 0.75_f64;
    for term in q_terms {
        let tf = *counts.get(&term).unwrap_or(&0);
        if tf == 0 {
            continue;
        }
        matched += tf;
        let df = *doc_freq.get(&term).unwrap_or(&0) as f64;
        let idf = (1.0 + (n_docs as f64 - df + 0.5) / (df + 0.5)).ln();
        let tf_f = tf as f64;
        let denom = tf_f + k1 * (1.0 - b + b * length as f64 / avg_len);
        score += idf * (tf_f * (k1 + 1.0) / denom);
    }
    Ok((score, matched))
}

#[pyfunction]
fn jaccard_similarity(left: Vec<String>, right: Vec<String>) -> PyResult<f64> {
    let a: HashSet<String> = left.into_iter().collect();
    let b: HashSet<String> = right.into_iter().collect();
    if a.is_empty() || b.is_empty() {
        return Ok(0.0);
    }
    let intersection = a.intersection(&b).count() as f64;
    let union = a.union(&b).count() as f64;
    Ok(intersection / union)
}

#[pyfunction]
#[pyo3(signature = (token, n=3))]
fn char_ngrams(token: &str, n: usize) -> PyResult<Vec<String>> {
    if n == 0 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "n must be positive",
        ));
    }
    let padded = format!("^{}$", token);
    let chars: Vec<char> = padded.chars().collect();
    if chars.len() < n {
        return Ok(vec![padded]);
    }
    Ok((0..=(chars.len() - n))
        .map(|i| chars[i..i + n].iter().collect())
        .collect())
}

#[pyfunction]
fn strip_ansi(text: &str) -> PyResult<String> {
    static ANSI: OnceLock<Regex> = OnceLock::new();
    let pattern =
        ANSI.get_or_init(|| Regex::new(r"\x1b\[[0-9;?]*[ -/]*[@-~]").expect("static ansi regex"));
    Ok(pattern.replace_all(text, "").into_owned())
}

#[pyfunction]
#[pyo3(signature = (text, minimum=3))]
fn collapse_repeated_lines(text: &str, minimum: usize) -> PyResult<String> {
    if minimum == 0 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "minimum must be positive",
        ));
    }
    let lines: Vec<&str> = text.lines().collect();
    if lines.len() < minimum {
        return Ok(text.to_string());
    }
    let mut out: Vec<String> = Vec::new();
    let mut i = 0usize;
    while i < lines.len() {
        let line = lines[i];
        let mut j = i + 1;
        while j < lines.len() && lines[j] == line {
            j += 1;
        }
        let count = j - i;
        if !line.trim().is_empty() && count >= minimum {
            out.push(line.to_string());
            out.push(format!(
                "[token-saver: previous line repeated {} more times]",
                count - 1
            ));
        } else {
            out.extend(lines[i..j].iter().map(|value| (*value).to_string()));
        }
        i = j;
    }
    let mut candidate = out.join("\n");
    if text.ends_with('\n') {
        candidate.push('\n');
    }
    if candidate.len() < text.len() {
        Ok(candidate)
    } else {
        Ok(text.to_string())
    }
}

#[pyfunction]
#[pyo3(signature = (text, max_lines=20))]
fn critical_lines(text: &str, max_lines: usize) -> PyResult<Vec<String>> {
    if max_lines == 0 {
        return Ok(Vec::new());
    }
    static CRITICAL: OnceLock<Regex> = OnceLock::new();
    let pattern = CRITICAL.get_or_init(|| {
        Regex::new(
            r"(?i)(Traceback|AssertionError|\b(?:ERROR|FAILED|FATAL|PANIC)\b|Caused by:|(?:^|\s)[\w./\\-]+\.(?:py|pyi|ts|tsx|js|jsx|go|rs|java|cs|rb|php):\d+)"
        ).expect("static critical-line regex")
    });
    let stripped = strip_ansi(text)?;
    let mut seen: HashSet<String> = HashSet::new();
    let mut out = Vec::new();
    for line in stripped.lines() {
        let key = line.trim();
        if key.is_empty() || seen.contains(key) || !pattern.is_match(line) {
            continue;
        }
        seen.insert(key.to_string());
        out.push(line.to_string());
        if out.len() >= max_lines {
            break;
        }
    }
    Ok(out)
}

#[pymodule]
fn _token_saver_fast(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(estimate_tokens, m)?)?;
    m.add_function(wrap_pyfunction!(identifier_tokens, m)?)?;
    m.add_function(wrap_pyfunction!(jaccard_similarity, m)?)?;
    m.add_function(wrap_pyfunction!(bm25_score, m)?)?;
    m.add_function(wrap_pyfunction!(char_ngrams, m)?)?;
    m.add_function(wrap_pyfunction!(strip_ansi, m)?)?;
    m.add_function(wrap_pyfunction!(collapse_repeated_lines, m)?)?;
    m.add_function(wrap_pyfunction!(critical_lines, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn estimate_matches_character_ratio_rule() {
        assert_eq!(estimate_tokens("abcdef", 3.0).unwrap(), 2);
        assert_eq!(estimate_tokens("", 3.0).unwrap(), 0);
    }

    #[test]
    fn identifiers_are_sorted_and_unique() {
        let values = identifier_tokens("Foo foo $bar baz_2 if 2wrong abc$def caféValue").unwrap();
        assert_eq!(values, vec!["abc$def", "bar", "baz_2", "cafévalue", "foo"]);
    }

    #[test]
    fn bm25_matches_positive_reference_case() {
        let counts = HashMap::from([("auth".into(), 3_usize)]);
        let df = HashMap::from([("auth".into(), 2_usize)]);
        let (score, matched) = bm25_score(counts, vec!["auth".into()], df, 10, 12.0, 5).unwrap();
        assert!(score > 0.0);
        assert_eq!(matched, 3);
    }

    #[test]
    fn jaccard_handles_overlap() {
        let score =
            jaccard_similarity(vec!["a".into(), "b".into()], vec!["b".into(), "c".into()]).unwrap();
        assert!((score - (1.0 / 3.0)).abs() < 1e-9);
    }

    #[test]
    fn ansi_and_repetition_match_reference_behavior() {
        assert_eq!(strip_ansi("\x1b[31merror\x1b[0m").unwrap(), "error");
        assert_eq!(
            collapse_repeated_lines("x\nx\nx\ny\n", 3).unwrap(),
            "x\n[token-saver: previous line repeated 2 more times]\ny\n"
        );
    }

    #[test]
    fn critical_diagnostics_are_unique_and_bounded() {
        let values = critical_lines(
            "INFO ok\nERROR boom\nERROR boom\nsrc/main.rs:12 failed\n",
            20,
        )
        .unwrap();
        assert_eq!(values, vec!["ERROR boom", "src/main.rs:12 failed"]);
    }

    #[test]
    fn ngrams_are_padded_and_ordered() {
        assert_eq!(
            char_ngrams("token", 3).unwrap(),
            vec!["^to", "tok", "oke", "ken", "en$"]
        );
    }
}
