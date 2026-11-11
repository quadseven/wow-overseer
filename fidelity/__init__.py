"""The fidelity suite (#2281): replay captured realm truth offline.

A scenario fixture holds an ordered slice of recorded realm reads plus the
outputs the credited record says the overseer must give for them. `replay`
runs the real read path over the recorded reads, with no realm, database or
network, and compares. It is the offline complement of liveproof/ (#2125),
which proves live. See docs/FIDELITY.md.
"""
