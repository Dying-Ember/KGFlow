"""Shared test fixtures for KGFlow test suite."""

import pytest


@pytest.fixture
def sample_module_source():
    return '"""Module docstring."""\n\nimport os\nimport sys\n\ndef foo():\n    return 42\n'


@pytest.fixture
def sample_class_source():
    return (
        'class MyClass:\n'
        '    """A sample class."""\n\n'
        '    def __init__(self):\n'
        '        self.value = 0\n\n'
        '    def get_value(self):\n'
        '        return self.value\n'
    )


@pytest.fixture
def sample_function_source():
    return 'def greet(name: str) -> str:\n    return f"Hello, {name}"\n'


@pytest.fixture
def empty_source():
    return ""
