import inspect
from collections.abc import Callable


def function_source(function: Callable[..., object]) -> str:
    return inspect.getsource(function)
