import pytest
from datetime import datetime, timedelta
from unittest.mock import patch


class TestPasswordResetFlowIntegration:
    """Integration tests for forgot password, OTP generation, mock email notification, and password update."""

    def test_forgot_password_generates_otp_and_dispatches_email(self, client, db_conn):
        """User with email requests reset -> creates OTP row and triggers mock email sender."""
        c = db_conn.cursor()

        # Insert user with email
        c.execute("""
            INSERT INTO users (username, password, role, full_name, email)
            VALUES ('reset_user_101', 'OldPassword1', 'Viewer', 'Reset Test User', 'reset_user_101@test.com')
            ON CONFLICT (username) DO NOTHING
            RETURNING id;
        """)
        row = c.fetchone()
        if not row:
            c.execute("SELECT id FROM users WHERE username='reset_user_101'")
            user_id = c.fetchone()[0]
        else:
            user_id = row[0]
        db_conn.commit()

        with patch('modules.password_reset.send_otp_email', return_value=(True, None)) as mock_send:
            response = client.post('/forgot-password', data={
                'identifier': 'reset_user_101'
            }, follow_redirects=False)

            # Redirects to OTP verification
            assert response.status_code == 302
            assert '/verify-otp' in response.headers['Location']

            # Verify OTP record in database
            c.execute("""
                SELECT otp_code, used, expires_at FROM password_reset_otp
                WHERE user_id = %s
                ORDER BY id DESC LIMIT 1
            """, (user_id,))
            otp_row = c.fetchone()
            assert otp_row is not None
            otp_code = otp_row[0]
            assert len(otp_code) == 6
            assert otp_row[1] is False  # Not used yet

            # Verify send_otp_email was called with the exact generated OTP
            mock_send.assert_called_once_with('reset_user_101@test.com', otp_code, 'Reset Test User')

    def test_verify_otp_and_reset_password(self, client, db_conn):
        """Complete reset flow: valid OTP verification sets session, new password updates user record."""
        c = db_conn.cursor()

        c.execute("""
            INSERT INTO users (username, password, role, full_name, email)
            VALUES ('reset_user_202', 'OldPassword2', 'Viewer', 'Reset Test User 2', 'reset_user_202@test.com')
            ON CONFLICT (username) DO NOTHING
            RETURNING id;
        """)
        row = c.fetchone()
        user_id = row[0] if row else c.execute("SELECT id FROM users WHERE username='reset_user_202'") or c.fetchone()[0]

        # Insert unexpired OTP
        c.execute("""
            INSERT INTO password_reset_otp (user_id, otp_code, expires_at, used)
            VALUES (%s, '889900', %s, FALSE)
            RETURNING id;
        """, (user_id, datetime.now() + timedelta(minutes=10)))
        db_conn.commit()

        # Set session as if forgot_password was submitted
        with client.session_transaction() as sess:
            sess['reset_user_id'] = user_id

        # 1. Verify valid OTP
        verify_resp = client.post('/verify-otp', data={'otp': '889900'}, follow_redirects=False)
        assert verify_resp.status_code == 302
        assert '/reset-password' in verify_resp.headers['Location']

        # 2. Reset password to 'BrandNewPass123'
        reset_resp = client.post('/reset-password', data={
            'password': 'BrandNewPass123',
            'confirm_password': 'BrandNewPass123'
        }, follow_redirects=False)

        assert reset_resp.status_code == 302
        assert '/login' in reset_resp.headers['Location']

        # Verify password in database was updated
        c.execute("SELECT password FROM users WHERE id=%s", (user_id,))
        updated_password = c.fetchone()[0]
        assert updated_password == 'BrandNewPass123'

        # Verify OTP was marked as used
        c.execute("SELECT used FROM password_reset_otp WHERE user_id=%s AND otp_code='889900'", (user_id,))
        assert c.fetchone()[0] is True

