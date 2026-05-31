## Python Standards

### Style
- Follow PEP 8, use `ruff` for linting, `black` for formatting
- Type hints on all public functions (`def foo(x: int) -> str:`)
- Docstrings: Google style for public APIs
- Max line length: 100 characters

### Project Structure
- `src/package_name/` layout, not flat scripts
- `pyproject.toml` for project metadata
- `tests/` mirroring `src/` structure
- `uv` or `poetry` for dependency management

### Testing
- `pytest` with `pytest-cov`
- Fixtures in `conftest.py`
- Property-based testing with `hypothesis` for data transformations

### Data
- Prefer `polars` over `pandas` for performance
- Use `pydantic` for data validation at boundaries
- SQL via SQLAlchemy 2.0 async, not raw strings
