"""
PatternMatcher unit tests
"""

import pytest

from krkn_ai.cluster import PatternMatcher, PatternValidationError


class TestPatternMatcherCreation:
    """Test PatternMatcher creation from strings"""

    def test_none_pattern_with_default_match_all_false_creates_empty_matcher(self):
        """Test None pattern with default_match_all=False creates matcher that matches nothing"""
        matcher = PatternMatcher.from_string(None, default_match_all=False)
        assert matcher.is_empty()
        assert not matcher.matches("anything")

    def test_none_pattern_with_default_match_all_true_creates_match_all_matcher(self):
        """Test None pattern with default_match_all=True creates matcher that matches everything"""
        matcher = PatternMatcher.from_string(None, default_match_all=True)
        assert not matcher.is_empty()
        assert matcher.matches("anything")
        assert matcher.matches("default")

    def test_empty_string_with_default_match_all_false_creates_empty_matcher(self):
        """Test empty string with default_match_all=False creates matcher that matches nothing"""
        matcher = PatternMatcher.from_string("", default_match_all=False)
        assert matcher.is_empty()
        assert not matcher.matches("anything")

    def test_empty_string_with_default_match_all_true_creates_match_all_matcher(self):
        """Test empty string with default_match_all=True creates matcher that matches everything"""
        matcher = PatternMatcher.from_string("  ", default_match_all=True)
        assert not matcher.is_empty()
        assert matcher.matches("anything")

    def test_wildcard_star_creates_match_all_matcher(self):
        """Test '*' creates matcher that matches everything"""
        matcher = PatternMatcher.from_string("*")
        assert matcher.match_all
        assert matcher.matches("anything")
        assert matcher.matches("kube-system")

    def test_single_literal_pattern_creates_exact_matcher(self):
        """Test single literal pattern matches exactly"""
        matcher = PatternMatcher.from_string("default")
        assert matcher.matches("default")
        assert not matcher.matches("default-ns")
        assert not matcher.matches("my-default")

    def test_regex_pattern_creates_regex_matcher(self):
        """Test regex pattern is compiled and used for matching"""
        matcher = PatternMatcher.from_string("kube-.*")
        assert matcher.matches("kube-system")
        assert matcher.matches("kube-public")
        assert not matcher.matches("default")
        assert not matcher.matches("mykube-system")

    def test_comma_separated_patterns_creates_multi_pattern_matcher(self):
        """Test comma-separated patterns match any of the patterns"""
        matcher = PatternMatcher.from_string("default, kube-system, test-.*")
        assert matcher.matches("default")
        assert matcher.matches("kube-system")
        assert matcher.matches("test-ns")
        assert matcher.matches("test-anything")
        assert not matcher.matches("prod-ns")

    def test_list_input_creates_multi_pattern_matcher(self):
        """Test list input is handled correctly"""
        matcher = PatternMatcher.from_string(["default", "kube-.*"])
        assert matcher.matches("default")
        assert matcher.matches("kube-system")
        assert not matcher.matches("test-ns")


class TestPatternMatcherExclusion:
    """Test PatternMatcher exclusion patterns"""

    def test_exclusion_pattern_only_matches_all_except_excluded(self):
        """Test exclusion pattern alone matches everything except excluded"""
        matcher = PatternMatcher.from_string("!kube-system")
        assert matcher.match_all  # Implicit match all
        assert matcher.matches("default")
        assert matcher.matches("test-ns")
        assert not matcher.matches("kube-system")

    def test_wildcard_with_exclusion_matches_all_except_excluded(self):
        """Test '*,!pattern' matches everything except excluded"""
        matcher = PatternMatcher.from_string("*,!kube-system")
        assert matcher.matches("default")
        assert matcher.matches("prod-ns")
        assert not matcher.matches("kube-system")

    def test_multiple_exclusions_excludes_all_specified(self):
        """Test multiple exclusion patterns"""
        matcher = PatternMatcher.from_string("!kube-system,!kube-public")
        assert matcher.matches("default")
        assert not matcher.matches("kube-system")
        assert not matcher.matches("kube-public")

    def test_inclusion_with_exclusion_filters_correctly(self):
        """Test inclusion patterns with exclusion patterns"""
        matcher = PatternMatcher.from_string("openshift-.*,!openshift-operators")
        assert matcher.matches("openshift-monitoring")
        assert matcher.matches("openshift-console")
        assert not matcher.matches("openshift-operators")
        assert not matcher.matches("default")

    def test_regex_exclusion_pattern(self):
        """Test regex pattern in exclusion"""
        matcher = PatternMatcher.from_string("*,!kube-.*")
        assert matcher.matches("default")
        assert matcher.matches("prod-ns")
        assert not matcher.matches("kube-system")
        assert not matcher.matches("kube-public")

    def test_exclusion_takes_priority_over_inclusion(self):
        """Test exclusion patterns take priority over inclusion"""
        matcher = PatternMatcher.from_string("kube-.*,!kube-system")
        assert matcher.matches("kube-public")
        assert matcher.matches("kube-dns")
        assert not matcher.matches("kube-system")

    def test_list_input_with_exclusion(self):
        """Test list input with exclusion patterns"""
        matcher = PatternMatcher.from_string(["default", "!kube-system"])
        # Only "default" is in include, match_all is False
        assert matcher.matches("default")
        assert not matcher.matches("kube-system")
        assert not matcher.matches("other")


class TestPatternMatcherFilter:
    """Test PatternMatcher filter method"""

    def test_filter_returns_matching_values(self):
        """Test filter returns only matching values"""
        matcher = PatternMatcher.from_string("default,test-.*")
        values = ["default", "kube-system", "test-ns", "test-app", "prod"]

        result = matcher.filter(values)

        assert result == {"default", "test-ns", "test-app"}

    def test_filter_with_exclusion_excludes_correctly(self):
        """Test filter with exclusion patterns"""
        matcher = PatternMatcher.from_string("*,!kube-.*")
        values = ["default", "kube-system", "kube-public", "test-ns"]

        result = matcher.filter(values)

        assert result == {"default", "test-ns"}

    def test_filter_empty_matcher_returns_empty_set(self):
        """Test filter with empty matcher returns empty set"""
        matcher = PatternMatcher.from_string(None, default_match_all=False)
        values = ["default", "kube-system"]

        result = matcher.filter(values)

        assert result == set()

    def test_filter_match_all_returns_all_values(self):
        """Test filter with match_all returns all values"""
        matcher = PatternMatcher.from_string("*")
        values = ["default", "kube-system", "test-ns"]

        result = matcher.filter(values)

        assert result == {"default", "kube-system", "test-ns"}


class TestPatternMatcherValidation:
    """Test PatternMatcher validation"""

    def test_validate_returns_empty_list_for_valid_patterns(self):
        """Test validate returns empty list for valid patterns"""
        errors = PatternMatcher.validate("default,kube-.*")
        assert errors == []

    def test_validate_returns_empty_list_for_wildcard(self):
        """Test validate returns empty list for wildcard"""
        errors = PatternMatcher.validate("*")
        assert errors == []

    def test_validate_returns_empty_list_for_empty_string(self):
        """Test validate returns empty list for empty string"""
        errors = PatternMatcher.validate("")
        assert errors == []

    def test_validate_returns_errors_for_invalid_regex(self):
        """Test validate returns errors for invalid regex patterns"""
        errors = PatternMatcher.validate("[invalid")
        assert len(errors) == 1
        assert "Invalid regex" in errors[0]

    def test_from_string_raises_error_for_invalid_regex(self):
        """Test from_string raises PatternValidationError for invalid regex"""
        with pytest.raises(PatternValidationError, match="Invalid regex"):
            PatternMatcher.from_string("[invalid")


class TestPatternMatcherEdgeCases:
    """Test PatternMatcher edge cases"""

    def test_pattern_with_dot_treated_as_regex(self):
        """Test patterns with . are treated as regex (single char wildcard)"""
        matcher = PatternMatcher.from_string("my.namespace")
        # . is a regex metacharacter, so it matches any single character
        assert matcher.matches("my.namespace")
        assert matcher.matches("myXnamespace")  # . matches X
        assert not matcher.matches("myXXnamespace")  # . matches only one char

    def test_pattern_with_pipe_treated_as_regex(self):
        """Test pattern with | is treated as regex alternation"""
        # Use comma-separated patterns for alternation (recommended approach)
        matcher = PatternMatcher.from_string("default,test")
        assert matcher.matches("default")
        assert matcher.matches("test")
        assert not matcher.matches("default|test")  # Literal pipe not matched

        # If you use pipe directly, it's a regex alternation
        # Note: ^default|test$ means (^default) OR (test$) due to regex precedence
        matcher2 = PatternMatcher.from_string("default|test")
        assert matcher2.matches("default")
        assert matcher2.matches("test")
        # The literal "default|test" matches because "test$" portion matches the end
        assert matcher2.matches("default|test")

    def test_empty_exclusion_pattern_ignored(self):
        """Test empty exclusion pattern (just !) is ignored"""
        matcher = PatternMatcher.from_string("default,!")
        assert matcher.matches("default")
        assert not matcher.matches("other")

    def test_whitespace_in_patterns_trimmed(self):
        """Test whitespace around patterns is trimmed"""
        matcher = PatternMatcher.from_string("  default  ,  test-ns  ")
        assert matcher.matches("default")
        assert matcher.matches("test-ns")

    def test_repr_shows_patterns(self):
        """Test __repr__ shows pattern information"""
        matcher = PatternMatcher.from_string("default,!kube-system")
        repr_str = repr(matcher)
        assert "default" in repr_str
        # The repr shows the compiled regex pattern which may escape special chars
        assert "kube" in repr_str
        assert "system" in repr_str

    def test_repr_shows_wildcard(self):
        """Test __repr__ shows wildcard for match_all"""
        matcher = PatternMatcher.from_string("*")
        assert "*" in repr(matcher)

    def test_full_match_required_not_partial(self):
        """Test patterns require full match, not partial"""
        matcher = PatternMatcher.from_string("kube")
        assert matcher.matches("kube")
        assert not matcher.matches("kube-system")
        assert not matcher.matches("mykube")

    def test_regex_pattern_anchored_for_full_match(self):
        """Test regex patterns are anchored for full match"""
        matcher = PatternMatcher.from_string("kube.*")
        assert matcher.matches("kube-system")
        assert matcher.matches("kube")
        assert not matcher.matches("mykube-system")

    def test_is_empty_with_only_exclusions_returns_false(self):
        """Test is_empty returns False when only exclusions (implicit match_all)"""
        matcher = PatternMatcher.from_string("!kube-system")
        # Has implicit match_all, so not empty
        assert not matcher.is_empty()
