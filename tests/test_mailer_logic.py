import os
import pytest
from unittest.mock import patch, MagicMock
from modules.mailer import get_settings


class TestMailerSettingsLogic:
    """Unit tests for SMTP configuration loader and fallback rules."""

    @patch('database.db.get_db')
    @patch.dict(os.environ, {
        'SMTP_HOST': 'smtp.test.com',
        'SMTP_PORT': '587',
        'SMTP_USER': 'test@test.com',
        'SMTP_PASSWORD': 'test_password',
        'SMTP_FROM_NAME': 'Test System',
    })
    def test_get_settings_falls_back_to_env_when_no_db_row(self, mock_get_db):
        """When smtp_config table has no row, settings must fall back to .env values."""
        mock_cursor = MagicMock()
        mock_cursor.description = [('id',)]
        mock_cursor.fetchone.return_value = None

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        settings = get_settings()
        assert settings['host'] == 'smtp.test.com'
        assert settings['port'] == 587
        assert settings['username'] == 'test@test.com'
        assert settings['password'] == 'test_password'
        assert settings['from_name'] == 'Test System'
        assert settings['use_tls'] is True

    @patch('database.db.get_db')
    def test_get_settings_uses_db_row_when_present(self, mock_get_db):
        """When smtp_config row id=1 exists, its configuration takes precedence."""
        mock_cursor = MagicMock()
        mock_cursor.description = [
            ('id',), ('host',), ('port',), ('username',), ('password',),
            ('from_name',), ('from_email',), ('use_tls',), ('enabled',)
        ]
        mock_cursor.fetchone.return_value = (
            1, 'smtp.company.internal', 465, 'admin@company.internal', 'secure_pass',
            'Company PPE Mailer', 'no-reply@company.internal', False, True
        )

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        settings = get_settings()
        assert settings['host'] == 'smtp.company.internal'
        assert settings['port'] == 465
        assert settings['username'] == 'admin@company.internal'
        assert settings['from_name'] == 'Company PPE Mailer'
        assert settings['from_email'] == 'no-reply@company.internal'
        assert settings['use_tls'] is False
        assert settings['enabled'] is True

