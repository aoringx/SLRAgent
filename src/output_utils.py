from pathlib import Path


DEFAULT_OUTPUT_DIR = Path("outputs")


def resolve_output_path(path: str | Path, output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> Path:
    output_dir = Path(output_dir)
    path = Path(path)

    if path.is_absolute():
        return path

    try:
        path.relative_to(output_dir)
        return path
    except ValueError:
        pass

    return output_dir / path


def ensure_parent_dir(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
