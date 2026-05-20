"""Tests for utils/fs.py"""

import os
import stat
from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError

from krkn_ai.utils.fs import atomic_write_text, read_config_from_file


class TestAtomicWriteText:
    def test_preserves_existing_output_on_write_failure(self, tmp_path):
        """Failed atomic writes should leave the destination file untouched"""
        output_file = tmp_path / "krkn-ai.yaml"
        output_file.write_text("previous_config", encoding="utf-8")

        real_fdopen = os.fdopen

        class FailingWriter:
            def __init__(self, fd, mode, *args, **kwargs):
                self.file = real_fdopen(fd, mode, *args, **kwargs)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                self.file.close()
                return False

            def write(self, data):
                self.file.write(data[:7])
                self.file.flush()
                raise OSError("simulated write failure")

        def failing_fdopen(fd, mode="r", *args, **kwargs):
            return FailingWriter(fd, mode, *args, **kwargs)

        with patch("krkn_ai.utils.fs.os.fdopen", side_effect=failing_fdopen):
            with pytest.raises(OSError, match="simulated write failure"):
                atomic_write_text(str(output_file), "generated_template_content")

        assert output_file.read_text(encoding="utf-8") == "previous_config"
        assert list(tmp_path.glob(".krkn-ai.yaml.*.tmp")) == []

    def test_cleans_up_temp_file_on_keyboard_interrupt(self, tmp_path):
        """Interrupted atomic writes should not leave temporary files behind"""
        output_file = tmp_path / "krkn-ai.yaml"
        output_file.write_text("previous_config", encoding="utf-8")

        real_fdopen = os.fdopen

        class InterruptingWriter:
            def __init__(self, fd, mode, *args, **kwargs):
                self.file = real_fdopen(fd, mode, *args, **kwargs)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                self.file.close()
                return False

            def write(self, data):
                self.file.write(data[:7])
                self.file.flush()
                raise KeyboardInterrupt

        def interrupting_fdopen(fd, mode="r", *args, **kwargs):
            return InterruptingWriter(fd, mode, *args, **kwargs)

        with patch("krkn_ai.utils.fs.os.fdopen", side_effect=interrupting_fdopen):
            with pytest.raises(KeyboardInterrupt):
                atomic_write_text(str(output_file), "generated_template_content")

        assert output_file.read_text(encoding="utf-8") == "previous_config"
        assert list(tmp_path.glob(".krkn-ai.yaml.*.tmp")) == []

    def test_does_not_remove_unowned_temp_file_when_open_fails(self, tmp_path):
        """Cleanup should only remove a temp file created by the current write"""
        output_file = tmp_path / "krkn-ai.yaml"
        output_file.write_text("previous_config", encoding="utf-8")
        existing_temp_file = tmp_path / ".krkn-ai.yaml.collision.tmp"
        existing_temp_file.write_text("other_process", encoding="utf-8")

        with patch("krkn_ai.utils.fs.uuid.uuid4") as mock_uuid:
            with patch("krkn_ai.utils.fs.os.open", side_effect=FileExistsError):
                mock_uuid.return_value.hex = "collision"

                with pytest.raises(FileExistsError):
                    atomic_write_text(str(output_file), "generated_template_content")

        assert existing_temp_file.read_text(encoding="utf-8") == "other_process"
        assert output_file.read_text(encoding="utf-8") == "previous_config"

    def test_preserves_existing_file_mode(self, tmp_path):
        """Replacing an existing file should preserve its permission mode"""
        output_file = tmp_path / "krkn-ai.yaml"
        output_file.write_text("previous_config", encoding="utf-8")
        os.chmod(output_file, 0o600)

        atomic_write_text(str(output_file), "generated_template_content")

        assert output_file.read_text(encoding="utf-8") == "generated_template_content"
        assert stat.S_IMODE(os.stat(output_file).st_mode) == 0o600

    def test_chmod_failure_does_not_widen_existing_file_mode(self, tmp_path):
        """Mode preservation failures should not make existing files more permissive"""
        output_file = tmp_path / "krkn-ai.yaml"
        output_file.write_text("previous_config", encoding="utf-8")
        os.chmod(output_file, 0o600)

        with patch("krkn_ai.utils.fs.os.chmod", side_effect=OSError):
            atomic_write_text(str(output_file), "generated_template_content")

        assert output_file.read_text(encoding="utf-8") == "generated_template_content"
        assert stat.S_IMODE(os.stat(output_file).st_mode) == 0o600

    def test_follows_output_symlink(self, tmp_path):
        """Atomic writes should follow symlinks like open(..., "w")"""
        target_file = tmp_path / "target.yaml"
        target_file.write_text("previous_config", encoding="utf-8")
        output_file = tmp_path / "krkn-ai.yaml"
        output_file.symlink_to(target_file)

        atomic_write_text(str(output_file), "generated_template_content")

        assert output_file.is_symlink()
        assert target_file.read_text(encoding="utf-8") == "generated_template_content"

    def test_preserves_existing_extended_attributes(self, tmp_path):
        """Replacing an existing file should preserve extended attributes"""
        if not all(hasattr(os, attr) for attr in ("setxattr", "getxattr", "listxattr")):
            pytest.skip("extended attributes are not available on this platform")

        output_file = tmp_path / "krkn-ai.yaml"
        output_file.write_text("previous_config", encoding="utf-8")

        xattr_name = None
        for name in ("user.krkn_test", "krkn_test"):
            try:
                os.setxattr(output_file, name, b"previous")
                xattr_name = name
                break
            except OSError:
                pass

        if xattr_name is None:
            pytest.skip("extended attributes are not supported by this filesystem")

        atomic_write_text(str(output_file), "generated_template_content")

        assert os.getxattr(output_file, xattr_name) == b"previous"


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


class TestReadConfigFromFileHeaders:
    def _write_config(self, path):
        config = {
            "kubeconfig_file_path": "/tmp/kubeconfig",
            "fitness_function": {"query": "up"},
            "cluster_components": {"namespaces": [], "nodes": []},
            "health_checks": {
                "headers": {"Authorization": "Bearer $GLOBAL_TOKEN"},
                "applications": [
                    {
                        "name": "api",
                        "url": "http://localhost/health",
                        "headers": {"X-Tenant": "$TENANT_ID"},
                    }
                ],
            },
        }
        with open(path, "w") as f:
            yaml.dump(config, f)

    def test_headers_stay_as_templates_at_load_time(self, tmp_path):
        """Header values are not substituted at load — resolution happens at request time"""
        config_file = str(tmp_path / "config.yaml")
        self._write_config(config_file)
        config = read_config_from_file(
            config_file, param=["GLOBAL_TOKEN=mytoken", "TENANT_ID=acme"]
        )
        assert config.health_checks.headers["Authorization"] == "Bearer $GLOBAL_TOKEN"

    def test_endpoint_headers_stay_as_templates_at_load_time(self, tmp_path):
        """Per-endpoint header values are not substituted at load"""
        config_file = str(tmp_path / "config.yaml")
        self._write_config(config_file)
        config = read_config_from_file(
            config_file, param=["GLOBAL_TOKEN=mytoken", "TENANT_ID=acme"]
        )
        assert config.health_checks.applications[0].headers["X-Tenant"] == "$TENANT_ID"

    def test_url_param_substitution_applied_at_load_time(self, tmp_path):
        """URL $PARAM substitution happens at load time via -p flag"""
        config = {
            "kubeconfig_file_path": "/tmp/kubeconfig",
            "fitness_function": {"query": "up"},
            "cluster_components": {"namespaces": [], "nodes": []},
            "health_checks": {
                "applications": [{"name": "api", "url": "http://$HOST/health"}]
            },
        }
        config_file = str(tmp_path / "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config, f)
        result = read_config_from_file(config_file, param=["HOST=myhost.com"])
        assert result.health_checks.applications[0].url == "http://myhost.com/health"

    def test_no_crash_when_headers_absent(self, tmp_path):
        """Test config without headers loads fine — guards on absent keys don't raise"""
        config = {
            "kubeconfig_file_path": "/tmp/kubeconfig",
            "fitness_function": {"query": "up"},
            "cluster_components": {"namespaces": [], "nodes": []},
            "health_checks": {
                "applications": [{"name": "api", "url": "http://localhost/health"}]
            },
        }
        config_file = str(tmp_path / "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config, f)
        result = read_config_from_file(config_file, param=["KEY=value"])
        assert result.health_checks.headers is None
        assert result.health_checks.applications[0].headers is None


class TestReadConfigValidation:
    def test_read_config_empty_file(self, tmp_path):
        """Empty YAML file should raise ValidationError from Pydantic (missing required fields)"""
        config_file = str(tmp_path / "empty.yaml")
        with open(config_file, "w") as f:
            f.write("")
        with pytest.raises(ValidationError):
            read_config_from_file(config_file)

    def test_read_config_non_dict_root(self, tmp_path):
        """YAML with non-dict root (e.g. list) should raise ValueError"""
        config_file = str(tmp_path / "list.yaml")
        with open(config_file, "w") as f:
            f.write("- item1\n- item2")
        with pytest.raises(ValueError, match="must be a mapping"):
            read_config_from_file(config_file)

    def test_read_config_string_root(self, tmp_path):
        """YAML with string root should raise ValueError"""
        config_file = str(tmp_path / "string.yaml")
        with open(config_file, "w") as f:
            f.write("just a string")
        with pytest.raises(ValueError, match="must be a mapping"):
            read_config_from_file(config_file)
