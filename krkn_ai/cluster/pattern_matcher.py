"""
PatternMatcher - Flexible pattern matching for Kubernetes resources.

Supports:
- Inclusion patterns (default, regex)
- Exclusion patterns (prefix with !)
- Match all (*) and match none semantics
- Comma-separated multiple patterns
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set, Union

from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


class PatternValidationError(ValueError):
    """Raised when a pattern string contains invalid regex."""

    pass


@dataclass
class PatternMatcher:
    """
    Handles pattern matching with support for inclusion/exclusion patterns.

    Attributes:
        include_patterns: Compiled regex patterns for inclusion
        exclude_patterns: Compiled regex patterns for exclusion
        match_all: If True, matches everything (before exclusions)
    """

    include_patterns: List[re.Pattern] = field(default_factory=list)
    exclude_patterns: List[re.Pattern] = field(default_factory=list)
    match_all: bool = False

    @classmethod
    def from_string(
        cls,
        pattern_string: Optional[Union[str, List[str]]] = None,
        default_match_all: bool = False,
    ) -> "PatternMatcher":
        """
        Parse pattern string into a PatternMatcher.

        Args:
            pattern_string: Pattern specification. Examples:
                - None or '': Uses default_match_all behavior
                - '*': Match all
                - 'pattern1,pattern2': Include multiple patterns
                - '!pattern': Exclude pattern
                - '*,!kube-system': Match all except kube-system
                - 'openshift-.*,!openshift-operators': Include with exclusion

            default_match_all: Behavior when pattern is None/empty.
                - False (default): Match nothing (explicit selection required)
                - True: Match everything

        Returns:
            Configured PatternMatcher instance

        Raises:
            PatternValidationError: If any pattern contains invalid regex
        """
        # Handle list input (pass through)
        if isinstance(pattern_string, list):
            list_include: List[re.Pattern] = []
            list_exclude: List[re.Pattern] = []
            for pat in pattern_string:
                if pat.startswith("!"):
                    actual = pat[1:]
                    if actual:
                        list_exclude.append(cls._compile_pattern(actual))
                else:
                    list_include.append(cls._compile_pattern(pat))
            list_match_all = len(list_include) == 0 and len(list_exclude) > 0
            return cls(list_include, list_exclude, match_all=list_match_all)

        # Handle None or empty string
        if pattern_string is None or pattern_string.strip() == "":
            if default_match_all:
                return cls([], [], match_all=True)
            return cls([], [], match_all=False)

        stripped = pattern_string.strip()

        # Handle wildcard for "match all"
        if stripped == "*":
            return cls([], [], match_all=True)

        include: List[re.Pattern] = []
        exclude: List[re.Pattern] = []

        # Split by comma and process each part
        parts = [p.strip() for p in stripped.split(",") if p.strip()]

        for part in parts:
            if part == "*":
                # Wildcard in comma list means match all (before exclusions)
                include.clear()  # Clear any previous includes
                # Set match_all flag instead
                return cls._process_with_match_all(parts)

            if part.startswith("!"):
                # Exclusion pattern
                actual_pattern = part[1:]
                if actual_pattern:
                    exclude.append(cls._compile_pattern(actual_pattern))
            else:
                include.append(cls._compile_pattern(part))

        # If only exclusions provided, implicitly match all first
        match_all = len(include) == 0 and len(exclude) > 0

        return cls(include, exclude, match_all=match_all)

    @classmethod
    def _process_with_match_all(cls, parts: List[str]) -> "PatternMatcher":
        """Process pattern parts when * is present."""
        exclude: List[re.Pattern] = []
        for part in parts:
            if part == "*":
                continue
            if part.startswith("!"):
                actual_pattern = part[1:]
                if actual_pattern:
                    exclude.append(cls._compile_pattern(actual_pattern))
            # Ignore non-exclusion patterns when * is present
        return cls([], exclude, match_all=True)

    @staticmethod
    def _compile_pattern(pattern: str) -> re.Pattern:
        """
        Compile a pattern string into a regex Pattern.

        The pattern is anchored for full-string matching (^ and $).
        If the pattern doesn't contain regex metacharacters, it's treated
        as a literal string match.

        Args:
            pattern: The pattern string to compile

        Returns:
            Compiled regex Pattern

        Raises:
            PatternValidationError: If the pattern is invalid regex
        """
        # Check if pattern contains regex metacharacters
        regex_metacharacters = set(r".*+?^${}[]|\()")
        has_regex = any(c in pattern for c in regex_metacharacters)

        if not has_regex:
            # Treat as literal - escape special regex characters
            pattern = re.escape(pattern)

        # Anchor pattern for full-string matching if not already anchored
        if not pattern.startswith("^"):
            pattern = "^" + pattern
        if not pattern.endswith("$"):
            pattern = pattern + "$"

        try:
            return re.compile(pattern)
        except re.error as e:
            raise PatternValidationError(f"Invalid regex pattern '{pattern}': {e}")

    def matches(self, value: str) -> bool:
        """
        Check if a value matches the pattern criteria.

        Matching logic:
        1. Check exclusions first - if value matches any exclusion, return False
        2. If match_all is True, return True
        3. Otherwise, return True if value matches any inclusion pattern

        Args:
            value: The string value to check

        Returns:
            True if value matches, False otherwise
        """
        # Check exclusions first - they take priority
        for exc in self.exclude_patterns:
            if exc.match(value):
                return False

        # If match_all mode, everything passes (that wasn't excluded)
        if self.match_all:
            return True

        # Check inclusion patterns
        for inc in self.include_patterns:
            if inc.match(value):
                return True

        return False

    def filter(self, values: List[str]) -> Set[str]:
        """
        Filter a list of values, returning those that match.

        Args:
            values: List of string values to filter

        Returns:
            Set of values that match the pattern
        """
        return {v for v in values if self.matches(v)}

    def is_empty(self) -> bool:
        """
        Check if this matcher will match nothing.

        Returns:
            True if no patterns defined and match_all is False
        """
        return not self.match_all and len(self.include_patterns) == 0

    @classmethod
    def validate(cls, pattern_string: str) -> List[str]:
        """
        Validate a pattern string without creating a matcher.

        Args:
            pattern_string: The pattern string to validate

        Returns:
            List of error messages (empty if valid)
        """
        errors: List[str] = []
        if not pattern_string or pattern_string.strip() in ("", "*"):
            return errors

        parts = [p.strip() for p in pattern_string.split(",") if p.strip()]
        for part in parts:
            if part == "*":
                continue
            actual_pattern = part[1:] if part.startswith("!") else part
            if actual_pattern:
                try:
                    cls._compile_pattern(actual_pattern)
                except PatternValidationError as e:
                    errors.append(str(e))

        return errors

    def __repr__(self) -> str:
        include_strs = [p.pattern for p in self.include_patterns]
        exclude_strs = [f"!{p.pattern}" for p in self.exclude_patterns]
        if self.match_all and not include_strs:
            include_strs = ["*"]
        return f"PatternMatcher({', '.join(include_strs + exclude_strs)})"
