"""The ephemeral-world forge: nightly golden template builder.

It restores the newest backup into a throwaway local MySQL, scrubs it, builds
the `lean` or `full` class and packages the datadir as an image. It reads the
backup share only and never connects to a live realm.
"""
