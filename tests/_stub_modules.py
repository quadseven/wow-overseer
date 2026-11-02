"""Stand-in modules for an import, put back afterwards (#1648).

The parallel runner (#1290) loads several test modules in one process, so a
stub one module leaves in sys.modules reaches every module in its batch, and
a `mock.patch.dict(sys.modules)` around an import drops every module that
import pulled in, so the next module imports a second copy of each.

`stub_modules` sets only the entries it is given and restores exactly those:

    with stub_modules(pymysql=PYMYSQL):
        import realmread

`fresh_import` makes a private copy of one module (bridge, whose module state
a test may change) under stubs, and leaves sys.modules[name] as it found it.
The modules the copy imports stay registered, so every test shares one copy
of each. tests/test_sys_modules_hygiene.py holds every test module to this.
"""

from __future__ import annotations

import builtins
import contextlib
import importlib
import sys
import types

_ABSENT = object()


def _pymysql_stub() -> types.ModuleType:
    """A driver stand-in with the real library's exception tree, so an
    `except pymysql.err.X` clause is a working clause, not an AttributeError.
    It has no `connect`: a test that reaches the database fails loudly."""
    module = types.ModuleType("pymysql")
    err = types.ModuleType("pymysql.err")

    class MySQLError(Exception):
        pass

    class Warning(builtins.Warning, MySQLError):  # noqa: A001 - the driver's own name
        pass

    class Error(MySQLError):
        pass

    class InterfaceError(Error):
        pass

    class DatabaseError(Error):
        pass

    class DataError(DatabaseError):
        pass

    class OperationalError(DatabaseError):
        pass

    class IntegrityError(DatabaseError):
        pass

    class InternalError(DatabaseError):
        pass

    class ProgrammingError(DatabaseError):
        pass

    class NotSupportedError(DatabaseError):
        pass

    for cls in (
        MySQLError,
        Warning,
        Error,
        InterfaceError,
        DatabaseError,
        DataError,
        OperationalError,
        IntegrityError,
        InternalError,
        ProgrammingError,
        NotSupportedError,
    ):
        cls.__module__ = "pymysql.err"
        setattr(err, cls.__name__, cls)
        setattr(module, cls.__name__, cls)
    module.err = err
    return module


# One stand-in for the whole process: a module imported under it by one test
# module and reused by another sees the same object either way.
PYMYSQL = _pymysql_stub()

# The private copies fresh_import made, which the hygiene test allows.
FRESH_COPIES: list[types.ModuleType] = []


def _share_pymysql() -> None:
    """While some test modules still install their own bare `pymysql` stub,
    every module must share one driver object, as the setdefault stubs did:
    the stand-in is left in sys.modules, and a bare stub an earlier module
    left is kept and given the stand-in's exception tree. A later change
    (#1648) restores sys.modules once no module installs a stub of its own."""
    current = sys.modules.setdefault("pymysql", PYMYSQL)
    if current is PYMYSQL or hasattr(current, "connect"):
        return
    for name in vars(PYMYSQL.err):
        if not name.startswith("_") and not hasattr(current, name):
            setattr(current, name, getattr(PYMYSQL, name))
    if not hasattr(current, "err"):
        current.err = PYMYSQL.err


@contextlib.contextmanager
def stub_modules(**stubs: types.ModuleType):
    """Put `stubs` in sys.modules for the block, then restore each of those
    entries, and only those, to what it was (or to absent). The driver
    stand-in is shared instead (_share_pymysql) until every module uses it."""
    if stubs.get("pymysql") is PYMYSQL:
        stubs = {k: v for k, v in stubs.items() if k != "pymysql"}
        _share_pymysql()
    saved = {name: sys.modules.get(name, _ABSENT) for name in stubs}
    sys.modules.update(stubs)
    try:
        yield
    finally:
        for name, prior in saved.items():
            if prior is _ABSENT:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior


def fresh_import(name: str, **stubs: types.ModuleType) -> types.ModuleType:
    """A new copy of module `name`, imported under `stubs`; sys.modules[name]
    is left as it was."""
    prior = sys.modules.pop(name, _ABSENT)
    try:
        with stub_modules(**stubs):
            module = importlib.import_module(name)
    finally:
        if prior is _ABSENT:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = prior
    FRESH_COPIES.append(module)
    return module
