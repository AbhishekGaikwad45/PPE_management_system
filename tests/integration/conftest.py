import os
import pytest
import psycopg2
from unittest.mock import patch, MagicMock

# Environment override for integration tests
TEST_DB_NAME = os.environ.get('TEST_PG_DATABASE', 'ppe_test_db')
PROD_DB_NAME = 'ppe_db'


@pytest.fixture(scope='session')
def test_db_config():
    """Returns database configuration targeting only the dedicated test database."""
    config = {
        'host': os.environ.get('PG_HOST', 'localhost'),
        'port': os.environ.get('PG_PORT', '5432'),
        'database': TEST_DB_NAME,
        'user': os.environ.get('PG_USER', 'postgres'),
        'password': os.environ.get('PG_PASSWORD', ''),
    }

    # Strict Production Guard: abort immediately if targeting production
    if config['database'].lower() == PROD_DB_NAME.lower():
        raise RuntimeError(
            f"FATAL SAFETY ABORT: Integration tests cannot run against production database '{PROD_DB_NAME}'!"
        )

    return config


@pytest.fixture(scope='session')
def integration_app(test_db_config):
    """Initializes the Flask app patched to point strictly to the dedicated test database."""
    with patch('database.db.DB_CONFIG', test_db_config):
        from app import app
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'integration-test-secret-key'
        app.config['WTF_CSRF_ENABLED'] = False
        yield app


@pytest.fixture
def client(integration_app, test_db_config):
    """Provides a test client with automatic DB_CONFIG patch and mocked SMTP mailer."""
    with patch('database.db.DB_CONFIG', test_db_config), \
         patch('modules.mailer.smtplib.SMTP') as mock_smtp, \
         patch('modules.mailer.smtplib.SMTP_SSL') as mock_smtp_ssl:

        # Configure mock SMTP to succeed by default
        instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = instance
        mock_smtp_ssl.return_value.__enter__.return_value = instance

        with integration_app.test_client() as client:
            yield client


@pytest.fixture
def db_conn(test_db_config):
    """Provides a direct connection to the test database for test assertions and fixture setup."""
    conn = psycopg2.connect(**test_db_config)
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()

