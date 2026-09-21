"""The fixed evaluation: keep these cases unchanged across both commits."""

from retry_policy import should_retry


def test_authentication_errors_do_not_retry():
    assert not should_retry(401)


def test_transient_server_errors_retry():
    assert should_retry(503)


def test_success_does_not_retry():
    assert not should_retry(200)
