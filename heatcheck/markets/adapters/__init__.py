"""Read-only public venue adapters (Experience). See docs/tasks/EXPERIENCE.md E-001.

``polymarket`` / ``kalshi``: pure parsers, raw bytes + capture metadata -> records.
``replay``: re-derive records from a bundle directory offline.
``live``: allowlisted GET-only client; not invoked by any test or default path.
"""
