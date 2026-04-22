from __future__ import annotations

from pathlib import Path


def load_dotenv_value(key: str, *, start_dir: Path | None = None) -> str | None:
    """Read a single key from a local .env file without mutating os.environ."""

    search_root = (start_dir or Path.cwd()).resolve()
    for candidate_dir in [search_root, *search_root.parents]:
        env_path = candidate_dir / ".env"
        if not env_path.exists() or not env_path.is_file():
            continue
        value = _read_env_file(env_path).get(key)
        if value:
            return value
    return None


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, raw_value = line.split("=", 1)
        key = name.strip()
        value = raw_value.strip()
        if not key:
            continue
        if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
            value = value[1:-1]
        values[key] = value
    return values
