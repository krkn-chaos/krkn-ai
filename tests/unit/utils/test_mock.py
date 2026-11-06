"""
Mock switch tests
"""

import os
from unittest.mock import patch

from krkn_ai.utils.mock import MockType, enable_dry_run, is_dry_run, is_mock_enabled


class TestDryRunSwitch:
    def test_dry_run_is_off_without_the_environment_flag(self):
        with patch.dict(os.environ, {}, clear=True):
            assert is_dry_run() is False
            assert is_mock_enabled(MockType.RUN) is False

    def test_enable_dry_run_turns_on_every_mock(self):
        with patch.dict(os.environ, {}, clear=True):
            enable_dry_run()

            assert is_dry_run() is True
            assert all(is_mock_enabled(mock_type) for mock_type in MockType)

    def test_mock_alone_is_not_a_dry_run(self):
        with patch.dict(os.environ, {"MOCK": "true"}, clear=True):
            assert is_mock_enabled(MockType.FITNESS) is True
            assert is_dry_run() is False
