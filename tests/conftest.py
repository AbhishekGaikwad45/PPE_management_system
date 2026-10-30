import pytest
from unittest.mock import MagicMock
from flask import Flask


@pytest.fixture
def test_app():
    """Provides a lightweight Flask application for request/session context tests."""
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'test-secret-key-12345'
    app.config['TESTING'] = True
    return app


@pytest.fixture
def mock_cursor():
    """Returns a mock database cursor with helper configurations."""
    cursor = MagicMock()
    cursor.description = None
    return cursor


@pytest.fixture
def mock_db_conn(mock_cursor):
    """Returns a mock database connection returning the mock cursor."""
    conn = MagicMock()
    conn.cursor.return_value = mock_cursor
    return conn

