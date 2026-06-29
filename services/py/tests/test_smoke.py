import reimb


def test_version_present():
    assert isinstance(reimb.__version__, str) and reimb.__version__
