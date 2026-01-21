#!/usr/bin/env python3
from __future__ import annotations

import gc
import sys
import types

from teleclaude.entrypoints import mcp_wrapper as _impl

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
