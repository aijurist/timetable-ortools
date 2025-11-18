"""Theory constraint bundle.

Expected modules cover group scheduling, teacher presence, room capacity,
daily load limits, and slot adjacency controls. Each constraint implementation
should derive from :class:`~src.constraints.base.Constraint` and register itself
via :mod:`src.constraints.registry`.
"""
