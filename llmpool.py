"""The threads a model call runs on, apart from the threads every pass reads on.

WHY (#795). Every blocking call the bridge makes goes through
asyncio.to_thread, which runs on the event loop's one default executor: twelve
threads on the bridge's pod (min(32, cpu + 4)). A model call holds its thread
for as long as the model takes, up to LLM_TIMEOUT_SECONDS (120 s), and a call
the caller has stopped waiting for still holds it until the request ends
(jev.Client says so and counts it). Jev and its shadow client may hold eight
at once, the vision model one per head, and the bridge's own _ask_llm has no
limit at all. So a slow model could take every thread the realm reads go
through, and then every pass waited on a database read that had nowhere to
run.

WHAT. Model calls run here, on their own threads, and only model calls. The
default executor is left to the realm reads and writes, so no pass waits on a
thread a model call holds. A slow model can only make other model calls wait,
and each of those already has its own deadline and its own answer for a
model that does not reply in time.

WORKERS is the most model calls that can be in flight at once: Jev's slots and
its shadow's (jev.CONCURRENCY each), a look per head, and the bridge's own
asks, with room over. It costs nothing while idle: a thread is started only
when a call needs one and none is free.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import functools

WORKERS = 16
PREFIX = "llm"

_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=WORKERS, thread_name_prefix=PREFIX
)


async def call(fn, /, *args, **kwargs):
    """`await asyncio.to_thread(fn, ...)`, on the model threads instead."""
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    return await loop.run_in_executor(
        _POOL, functools.partial(ctx.run, fn, *args, **kwargs)
    )
