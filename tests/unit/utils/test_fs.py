"""Tests for utils/fs.py"""


class TestParamParsing:
    def test_param_with_base64_value_does_not_crash(self):
        """base64 secrets with = should not crash"""
        p = "SECRET=aGVsbG8="
        key, value = p.split("=", 1)
        assert key == "SECRET"
        assert value == "aGVsbG8="

    def test_param_with_password_containing_equals(self):
        """passwords with = should not crash"""
        p = "DB_PASSWORD=pass=word123"
        key, value = p.split("=", 1)
        assert key == "DB_PASSWORD"
        assert value == "pass=word123"

    def test_normal_param_still_works(self):
        """normal params without = still work"""
        p = "KEY=value"
        key, value = p.split("=", 1)
        assert key == "KEY"
        assert value == "value"

    def test_param_without_equals_sign(self):
        """param without = should assign empty string as value"""
        p = "JUST_A_KEY"
        if "=" in p:
            key, value = p.split("=", 1)
        else:
            key, value = p, ""
        assert key == "JUST_A_KEY"
        assert value == ""
