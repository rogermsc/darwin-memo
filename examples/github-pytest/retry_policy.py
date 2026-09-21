"""A deliberately defective retry policy for the adoption example."""


def should_retry(status: int) -> bool:
    return status >= 400
