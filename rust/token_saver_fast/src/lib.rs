use std::collections::{HashMap, HashSet};

use pyo3::prelude::*;

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
    let mut out: HashSet<String> = HashSet::new();
    let mut current = String::new();

    for ch in text.chars().chain(std::iter::once(' ')) {
        let continuation = ch.is_alphanumeric() || ch == '_' || ch == '
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
        return Err(pyo3::exceptions::PyValueError::new_err("n must be positive"));
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

#[pymodule]
fn _token_saver_fast(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(estimate_tokens, m)?)?;
    m.add_function(wrap_pyfunction!(identifier_tokens, m)?)?;
    m.add_function(wrap_pyfunction!(jaccard_similarity, m)?)?;
    m.add_function(wrap_pyfunction!(bm25_score, m)?)?;
    m.add_function(wrap_pyfunction!(char_ngrams, m)?)?;
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
        let values = identifier_tokens("Foo foo $bar baz_2 if 2wrong abc$def").unwrap();
        assert_eq!(values, vec!["abc$def", "baz_2", "foo"]);
    }

    #[test]
    fn bm25_matches_positive_reference_case() {
        let counts = HashMap::from([("auth".into(), 3_usize)]);
        let df = HashMap::from([("auth".into(), 2_usize)]);
        let (score, matched) =
            bm25_score(counts, vec!["auth".into()], df, 10, 12.0, 5).unwrap();
        assert!(score > 0.0);
        assert_eq!(matched, 3);
    }

    #[test]
    fn jaccard_handles_overlap() {
        let score = jaccard_similarity(
            vec!["a".into(), "b".into()],
            vec!["b".into(), "c".into()],
        )
        .unwrap();
        assert!((score - (1.0 / 3.0)).abs() < 1e-9);
    }
}
;
        if continuation {
            current.push(ch);
            continue;
        }
        if !current.is_empty() {
            let first = current.chars().next().unwrap();
            let valid_start = first.is_ascii_alphabetic() || first == '_';
            if valid_start && current.chars().count() > 2 {
                out.insert(current.to_lowercase());
            }
            current.clear();
        }
    }

    let mut values: Vec<String> = out.into_iter().collect();
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
        return Err(pyo3::exceptions::PyValueError::new_err("n must be positive"));
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

#[pymodule]
fn _token_saver_fast(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(estimate_tokens, m)?)?;
    m.add_function(wrap_pyfunction!(identifier_tokens, m)?)?;
    m.add_function(wrap_pyfunction!(jaccard_similarity, m)?)?;
    m.add_function(wrap_pyfunction!(bm25_score, m)?)?;
    m.add_function(wrap_pyfunction!(char_ngrams, m)?)?;
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
        let values = identifier_tokens("Foo foo $bar baz_2 if").unwrap();
        assert_eq!(values, vec!["$bar", "baz_2", "foo"]);
    }

    #[test]
    fn bm25_matches_positive_reference_case() {
        let counts = HashMap::from([("auth".into(), 3_usize)]);
        let df = HashMap::from([("auth".into(), 2_usize)]);
        let (score, matched) =
            bm25_score(counts, vec!["auth".into()], df, 10, 12.0, 5).unwrap();
        assert!(score > 0.0);
        assert_eq!(matched, 3);
    }

    #[test]
    fn jaccard_handles_overlap() {
        let score = jaccard_similarity(
            vec!["a".into(), "b".into()],
            vec!["b".into(), "c".into()],
        )
        .unwrap();
        assert!((score - (1.0 / 3.0)).abs() < 1e-9);
    }
}
