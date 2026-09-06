"""Input validation rules."""

from __future__ import annotations

import pytest

from app.validation import (
    password_entropy_bits,
    split_full_name,
    validate_email,
    validate_name,
    validate_password,
    validate_password_confirm,
    validate_username,
)


class TestUsername:
    @pytest.mark.parametrize(
        "value",
        ["alice", "bob123", "a.b", "x_y-z", "u" * 3, "u" * 32, "0.0", "jean.dupont"],
    )
    def test_valid(self, value):
        assert validate_username(value) is None

    @pytest.mark.parametrize(
        ("value", "code"),
        [
            ("", "invalid_format"),
            ("ab", "invalid_format"),  # too short
            ("u" * 33, "invalid_format"),  # too long
            ("Alice", "invalid_format"),  # uppercase
            ("alice doe", "invalid_format"),  # space
            ("alice@x", "invalid_format"),
            ("alicé", "invalid_format"),
            ("admin", "reserved"),
            ("root", "reserved"),
            ("ADMIN", "invalid_format"),  # uppercase fails the regex first
            ("webmaster", "reserved"),
            (None, "invalid_type"),
            (123, "invalid_type"),
            ("alice\n", "invalid_format"),
            ("ali\x00ce", "invalid_format"),
        ],
    )
    def test_invalid(self, value, code):
        assert validate_username(value) == code


class TestName:
    @pytest.mark.parametrize(
        "value",
        ["Alice", "Jean Dupont", "O'Brien", "Marie-Claire", "Élodie", "Ñuñoz", "Zoë", "   Alice  "],
    )
    def test_valid(self, value):
        assert validate_name(value) is None

    @pytest.mark.parametrize(
        ("value", "code"),
        [
            ("", "invalid_length"),
            ("   ", "invalid_length"),
            ("x" * 65, "invalid_length"),
            ("Alice123", "invalid_format"),
            ("Alice<b>", "invalid_format"),
            ("😀", "invalid_format"),
            ("-", "invalid_format"),  # no letters at all
            (None, "invalid_type"),
            ("Ali\x00ce", "invalid_format"),
        ],
    )
    def test_invalid(self, value, code):
        assert validate_name(value) == code


class TestEmail:
    @pytest.mark.parametrize(
        "value",
        [
            "alice@example.com",
            "first.last+tag@sub.example.co.uk",
            "a@b.cd",
            " o'connor@example.com ",
            "x_123@example-domain.com",
        ],
    )
    def test_valid(self, value):
        assert validate_email(value) is None

    @pytest.mark.parametrize(
        ("value", "code"),
        [
            ("", "invalid_length"),
            ("not-an-email", "invalid_format"),
            ("a@b", "invalid_format"),  # no TLD
            ("a b@example.com", "invalid_format"),
            ("@example.com", "invalid_format"),
            ("a@", "invalid_format"),
            (".a@example.com", "invalid_format"),
            ("a.@example.com", "invalid_format"),
            ("a..b@example.com", "invalid_format"),
            ("a@-example.com", "invalid_format"),
            ("a" * 250 + "@example.com", "invalid_length"),
            (None, "invalid_type"),
        ],
    )
    def test_invalid(self, value, code):
        assert validate_email(value) == code


class TestPassword:
    def test_valid_strong(self):
        assert validate_password("Phrase-Harbor7-Velvet") is None
        assert validate_password("correct horse battery staple 42") is None

    def test_natural_words_and_phrases_score_fairly(self):
        # Real language repeats characters; length must still count.
        assert validate_password("anticonstitutionnellement") is None  # 25 letters, 11 unique
        assert validate_password("MonChatDortBienLeSoir") is None
        assert validate_password("phrase-cheval-batterie") is None

    @pytest.mark.parametrize(
        ("value", "code"),
        [
            ("", "too_short"),
            ("short1!A", "too_short"),  # < 12 chars
            ("aaaaaaaaaaaa", "too_weak"),  # single repeated character collapses
            ("abcabcabcabc", "too_weak"),  # 3-character pattern collapses
            ("coucoucoucou1", "too_weak"),  # 4 unique characters across 13
            ("password12345", "too_common"),
            ("passwordpassword", "too_common"),
            ("PASSWORDPASSWORD", "too_common"),  # denylist is case-insensitive
            ("123456789012", "too_common"),  # denylist checked before entropy
            (None, "invalid_type"),
            ("Phrase-Harbor\n", "invalid_format"),
        ],
    )
    def test_invalid(self, value, code):
        assert validate_password(value) == code

    def test_entropy_ladder(self):
        repetitive = password_entropy_bits("a" * 12)
        pattern = password_entropy_bits("abcabcabcabc")
        natural = password_entropy_bits("anticonstitutionnellement")
        assert repetitive < pattern < natural
        assert natural > 60  # a real 25-letter word is a valid password
        assert pattern < 60  # a repeating 3-character pattern is not


class TestSplitFullName:
    def test_two_words(self):
        assert split_full_name("Jean Dupont") == ("Jean", "Dupont")

    def test_extra_words_join_surname(self):
        assert split_full_name("Jean Pierre Dupont") == ("Jean", "Pierre Dupont")

    def test_single_word_used_for_both(self):
        assert split_full_name("Madonna") == ("Madonna", "Madonna")

    def test_collapses_whitespace(self):
        assert split_full_name("  Jean   Dupont  ") == ("Jean", "Dupont")

    def test_empty(self):
        assert split_full_name("   ") == ("", "")


class TestPasswordConfirm:
    def test_match(self):
        assert validate_password_confirm("s3cret-value", "s3cret-value") is None

    def test_mismatch(self):
        assert validate_password_confirm("s3cret-value", "other-value") == "mismatch"

    def test_non_string(self):
        assert validate_password_confirm("x", None) == "invalid_type"
