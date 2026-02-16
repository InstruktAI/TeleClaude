#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

# Bootstrap: re-exec under the project venv when system Python is resolved.
_VENV_PYTHON = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python3"
if _VENV_PYTHON.is_file() and Path(sys.executable).resolve() != _VENV_PYTHON.resolve():
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), *sys.argv])

import gc  # noqa: E402
import types  # noqa: E402

from teleclaude.entrypoints import mcp_wrapper as _impl  # noqa: E402

main = _impl.main


class _ProxyModule(types.ModuleType):
    def __getattr__(self, name: str):  # type: ignore[override]
        return getattr(_impl, name)

    def __setattr__(self, name: str, value) -> None:  # type: ignore[override]
        if name == "_impl":
            return super().__setattr__(name, value)
        setattr(_impl, name, value)

    def __dir__(self) -> list[str]:  # type: ignore[override]
        return sorted(set(super().__dir__()) | set(dir(_impl)))


def _install_proxy_module() -> None:
    module = sys.modules.get(__name__)
    if module is None:
        for obj in gc.get_referrers(globals()):
            if isinstance(obj, types.ModuleType):
                module = obj
                break
    if module is not None:
        module.__class__ = _ProxyModule


_install_proxy_module()

if __name__ == "__main__":
    raise SystemExit(main())
