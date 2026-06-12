"""Adapters that mount darwin-memo inside other agent frameworks.

Each module here is thin by design: it implements the host framework's
own interface by duck typing, adds zero dependencies, and keeps the
darwin-memo contract intact (deltas are measurements the host supplies,
never something an adapter invents).
"""
