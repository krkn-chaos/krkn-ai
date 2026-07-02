from krkn_ai.utils.output import fmt_to_glob, fmt_to_id_regex


class TestFmtToGlob:
    def test_default_result_fmt(self):
        assert fmt_to_glob("scenario_%s.yaml") == "scenario_*.yaml"

    def test_default_log_fmt(self):
        assert fmt_to_glob("scenario_%s.log") == "scenario_*.log"

    def test_custom_fmt_with_all_placeholders(self):
        assert fmt_to_glob("gen_%g_%c_%s.json") == "gen_*_*_*.json"

    def test_fmt_with_glob_special_chars_is_escaped(self):
        # literal "[v1]" in the filename must not be treated as a glob character class
        assert fmt_to_glob("scenario_%s_[v1].log") == "scenario_*_[[]v1].log"


class TestFmtToIdRegex:
    def test_default_log_fmt_matches_and_captures_id(self):
        regex = fmt_to_id_regex("scenario_%s.log")
        match = regex.match("scenario_42.log")
        assert match is not None
        assert match.group(1) == "42"

    def test_custom_fmt_with_generation_and_scenario_name(self):
        regex = fmt_to_id_regex("gen_%g_%c_%s.log")
        match = regex.match("gen_3_pod_scenarios_17.log")
        assert match is not None
        assert match.group(1) == "17"

    def test_non_matching_filename_returns_none(self):
        regex = fmt_to_id_regex("scenario_%s.log")
        assert regex.match("other_file.log") is None

    def test_literal_dot_is_not_a_wildcard(self):
        regex = fmt_to_id_regex("scenario_%s.log")
        # the "." before "log" is literal; it must not match an arbitrary character
        assert regex.match("scenario_1Xlog") is None
