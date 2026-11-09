"""Resolve test source through imports instead of repository layout."""

import importlib
import inspect
from collections.abc import Callable
from pathlib import Path
from types import ModuleType


def function_source(
    module_name: str | ModuleType | Callable[..., object],
    function_name: str | None = None,
) -> str:
    if function_name is None:
        function_name = module_name.__qualname__
        module = importlib.import_module(module_name.__module__)
    else:
        module = (
            importlib.import_module(module_name)
            if isinstance(module_name, str)
            else module_name
        )
    function = module
    for part in function_name.split("."):
        function = getattr(function, part)
    return inspect.getsource(function)


def source_path(module_name: str | ModuleType) -> Path:
    module = (
        importlib.import_module(module_name)
        if isinstance(module_name, str)
        else module_name
    )
    filename = inspect.getsourcefile(module)
    if filename is None:
        raise ValueError(f"Module {module_name!r} has no inspectable source file")
    return Path(filename)
