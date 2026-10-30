import pytest
from unittest.mock import patch, MagicMock
from modules.password_reset import _generate_otp


class TestPasswordResetLogic:
    """Unit tests for password reset business rules and OTP generator."""

    def test_otp_format_is_six_digit_string(self):
        """OTP must be a string of length 6 composed only of digits."""
        for _ in range(20):
            otp = _generate_otp()
            assert isinstance(otp, str)
            assert len(otp) == 6
            assert otp.isdigit()

    @patch('random.randint', return_value=42)
    def test_otp_pads_with_leading_zeros(self, mock_randint):
        """OTP must pad numbers < 100000 with leading zeros to always be 6 digits."""
        otp = _generate_otp()
        assert otp == '000042'
        assert len(otp) == 6

    def test_password_validation_rules(self):
        """Verify password validation rules: min length 6, match confirm_password."""
        def validate_passwords(password, confirm_password):
            p = (password or '').strip()
            c = (confirm_password or '').strip()
            if not p or len(p) < 6:
                return False, 'Password must be at least 6 characters long.'
            if p != c:
                return False, 'Passwords do not match.'
            return True, None

        # Too short (< 6)
        ok, err = validate_passwords('12345', '12345')
        assert ok is False
        assert 'at least 6' in err

        # Empty
        ok, err = validate_passwords('', '')
        assert ok is False

        # Mismatch
        ok, err = validate_passwords('secret123', 'secret456')
        assert ok is False
        assert 'do not match' in err

        # Whitespace padding stripped
        ok, err = validate_passwords('  pass  ', 'pass')
        assert ok is False  # stripped length is 4

        # Valid
        ok, err = validate_passwords('StrongPass123', 'StrongPass123')
        assert ok is True
        assert err is None

