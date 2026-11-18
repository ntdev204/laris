//! Tokens and rounding, as generation 1 does them.

/// Lower-cased runs of letters and digits (`[^\W_]+` in Unicode mode): `_` and punctuation separate words.
pub fn tokens(text: &str) -> Vec<String> {
    text.split(|c: char| !c.is_alphanumeric())
        .filter(|w| !w.is_empty())
        .map(str::to_lowercase)
        .collect()
}

/// `round(value, digits)` as Python does it: the exact decimal value of the float rounded half to even.
/// Rust formats with the same exactness, so formatting and parsing back gives the same number.
pub fn round_to(value: f64, digits: usize) -> f64 {
    if !value.is_finite() {
        return value;
    }
    format!("{value:.digits$}").parse().unwrap_or(value)
}
