"""`python -m <package>.migrations init` -- lay down a migrations directory.

`alembic init` writes a ~90 line env.py that then has to be edited into shape,
and re-edited whenever alembic's template moves. This writes the version that
already delegates to `run_migrations`, so the only thing left to change is the
module holding the models.
"""

import argparse
from pathlib import Path

__all__ = ["init"]

_TEMPLATES = Path(__file__).parent / "templates"
_CONFIG_STYLES = ("ini", "pyproject")


def init(
    directory: str | Path = "migrations",
    *,
    models: str = "models",
    config: str = "ini",
    root: str | Path = ".",
    force: bool = False,
) -> None:
    """Scaffold a migrations directory.

    Args:
        directory: where env.py, script.py.mako and versions/ go, under `root`.
        models: the module importing every table model. env.py imports it, and
            autogenerate only sees tables registered by then.
        config: "ini" for a single alembic.ini, or "pyproject" to put alembic's
            settings in pyproject.toml (needs alembic >= 1.16) and leave
            alembic.ini holding only the logging config.
        root: the project root, where alembic.ini and pyproject.toml live.
        force: overwrite files that already exist.
    """
    _reject_unknown_config_style(config)
    scaffold = _Scaffold(Path(root), Path(directory), force)
    scaffold.write_migrations_directory(models)
    scaffold.write_alembic_config(config)
    _announce_next_steps(scaffold.env, models)


def _reject_unknown_config_style(config: str) -> None:
    if config not in _CONFIG_STYLES:
        raise ValueError(f"config must be one of {_CONFIG_STYLES}, not {config!r}")


class _Scaffold:
    """The files `init` writes, and the tokens the templates are rendered with."""

    def __init__(self, root: Path, directory: Path, force: bool) -> None:
        self.root: Path = root
        self.target: Path = root / directory
        self.force: bool = force
        self.tokens: dict[str, str] = {
            "PACKAGE": _vendored_package(),
            "SCRIPT_LOCATION": directory.as_posix(),
        }

    @property
    def env(self) -> Path:
        return self.target / "env.py"

    def write_migrations_directory(self, models: str) -> None:
        self._write(self.env, self._render("env.py.template", MODELS=models))
        self._write(self.target / "script.py.mako", _read("script.py.mako"))
        self._write(self.target / "README", self._render("README.template"))
        self._keep_versions_directory()

    def write_alembic_config(self, config: str) -> None:
        if config == "ini":
            self._write(self.root / "alembic.ini", self._render("alembic.ini.template"))
            return
        self._write(
            self.root / "alembic.ini", self._render("alembic.ini.logging.template")
        )
        self._append_to_pyproject(self._render("pyproject.toml.template"))

    def _keep_versions_directory(self) -> None:
        """Alembic makes versions/ on the first revision, but git drops it empty.

        Its absence is a confusing first error, so commit a placeholder.
        """
        self._write(self.target / "versions" / ".gitkeep", "")

    def _append_to_pyproject(self, block: str) -> None:
        """Add `[tool.alembic]` to pyproject.toml, leaving the rest of it alone."""
        path = self.root / "pyproject.toml"
        existing = path.read_text() if path.exists() else ""
        if "[tool.alembic]" in existing:
            _skipped(path, "already has [tool.alembic]")
            return
        separator = "" if not existing or existing.endswith("\n\n") else "\n"
        _ = path.write_text(f"{existing}{separator}{block}")
        _written(path)

    def _render(self, template: str, **extra: str) -> str:
        text = _read(template)
        for name, value in {**self.tokens, **extra}.items():
            text = text.replace(f"__{name}__", value)
        return text

    def _write(self, path: Path, content: str) -> None:
        if path.exists() and not self.force:
            _skipped(path, "exists; --force to overwrite")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(content)
        _written(path)


def _written(path: Path) -> None:
    print(f"  write   {path}")


def _skipped(path: Path, why: str) -> None:
    print(f"  skip    {path} ({why})")


def _read(template: str) -> str:
    return (_TEMPLATES / template).read_text()


def _vendored_package() -> str:
    """The directory this library was vendored into, which consumers may rename."""
    return __package__.split(".")[0] if __package__ else "release"


def _announce_next_steps(env: Path, models: str) -> None:
    print(f"\nEdit {env} so `import {models}` reaches your models,")
    print("then: alembic revision --autogenerate -m 'initial'")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog=f"python -m {_vendored_package()}.migrations",
        description="Set up alembic migrations wired to this library.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="scaffold a migrations directory")
    _ = init_parser.add_argument("directory", nargs="?", default="migrations")
    _ = init_parser.add_argument(
        "--models", default="models", help="module importing every table model"
    )
    _ = init_parser.add_argument("--config", choices=_CONFIG_STYLES, default="ini")
    _ = init_parser.add_argument("--force", action="store_true")

    args = parser.parse_args()
    init(args.directory, models=args.models, config=args.config, force=args.force)
