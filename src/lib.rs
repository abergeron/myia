extern crate pyo3;

use pyo3::prelude::*;

#[pymodule]
fn _core(_py: Python, m: &PyModule) -> PyResult<()> {
    Ok(())
}
