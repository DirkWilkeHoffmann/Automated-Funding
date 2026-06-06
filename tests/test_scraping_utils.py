"""Unit tests for scraping utility functions."""
import pytest
from unittest.mock import patch, MagicMock
from utils.scraping import _is_junk_url, _word_count


def test_junk_share_twitter():
    assert _is_junk_url("https://example.com/page?share=twitter") is True


def test_junk_share_facebook():
    assert _is_junk_url("https://example.com/page?share=facebook") is True


def test_junk_replytocom():
    assert _is_junk_url("https://example.com/comment-page-1?replytocom=2949") is True


def test_junk_comment_page():
    assert _is_junk_url("https://example.com/comment-page-2") is True


def test_junk_utm():
    assert _is_junk_url("https://example.com/grants?utm_source=newsletter") is True


def test_not_junk_normal_url():
    assert _is_junk_url("https://example.com/grants/apply") is False


def test_not_junk_root():
    assert _is_junk_url("https://example.com") is False


def test_word_count_empty():
    assert _word_count("") == 0


def test_word_count_basic():
    assert _word_count("hello world foo") == 3


def test_word_count_extra_spaces():
    assert _word_count("  hello   world  ") == 2
