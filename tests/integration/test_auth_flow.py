import pytest
from flask import session


class TestAuthenticationIntegration:
    """Integration tests for Login, Logout, Session lifecycle and Protected Routes."""

    def test_unauthenticated_user_redirected_to_login(self, client):
        """Unauthenticated requests to protected endpoints must redirect to login."""
        response = client.get('/issues', follow_redirects=False)
        assert response.status_code == 302
        assert '/login' in response.headers['Location']

        response = client.get('/stock', follow_redirects=False)
        assert response.status_code == 302
        assert '/login' in response.headers['Location']

    def test_login_invalid_credentials_rejected(self, client):
        """Submitting non-existent user credentials fails without setting session."""
        response = client.post('/login', data={
            'username': 'non_existent_user_9999',
            'password': 'wrong_password'
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'Invalid username or password' in response.data

        with client.session_transaction() as sess:
            assert 'user' not in sess

    def test_login_success_and_logout_lifecycle(self, client, db_conn):
        """Create a test user, verify login sets session, and verify logout clears session."""
        c = db_conn.cursor()
        c.execute("""
            INSERT INTO users (username, password, role, full_name, department)
            VALUES ('test_integration_user', 'ValidPass123', 'Safety Officer', 'Test Integration User', 'Safety')
            ON CONFLICT (username) DO NOTHING
            RETURNING id;
        """)
        db_conn.commit()

        # 1. Login with valid credentials
        response = client.post('/login', data={
            'username': 'test_integration_user',
            'password': 'ValidPass123'
        }, follow_redirects=False)

        assert response.status_code == 302
        assert response.headers['Location'] == '/' or '/dashboard' in response.headers['Location']

        with client.session_transaction() as sess:
            assert sess.get('user') == 'test_integration_user'
            assert sess.get('role') == 'Safety Officer'
            assert sess.get('department') == 'Safety'

        # 2. Access protected route with active session
        response = client.get('/issues')
        assert response.status_code == 200

        # 3. Logout
        logout_resp = client.get('/logout', follow_redirects=False)
        assert logout_resp.status_code == 302
        assert '/login' in logout_resp.headers['Location']

        with client.session_transaction() as sess:
            assert 'user' not in sess

