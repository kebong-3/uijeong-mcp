import pytest

from scripts.verify_recovery import condition_value


EXCERPT_CONDITION = {
    'path': 'articles.0.excerpt_location.excerpt_only',
    'equals': False,
    'missing_value': False,
}


def test_complete_article_without_optional_marker_is_accepted():
    data = {'articles': [{'label': '제5조의2', 'text': 'complete source article'}]}
    assert condition_value(data, EXCERPT_CONDITION) is False


def test_partial_article_is_not_promoted_to_complete():
    data = {'articles': [{'excerpt_location': {'excerpt_only': True}}]}
    assert condition_value(data, EXCERPT_CONDITION) is True


def test_missing_article_is_not_invented_from_optional_marker_default():
    with pytest.raises(IndexError):
        condition_value({'articles': []}, EXCERPT_CONDITION)


def test_explicit_null_and_malformed_marker_are_not_treated_as_complete():
    data = {'articles': [{'excerpt_location': {'excerpt_only': None}}]}
    assert condition_value(data, EXCERPT_CONDITION) is None
    with pytest.raises(TypeError):
        condition_value({'articles': [{'excerpt_location': None}]}, EXCERPT_CONDITION)


def test_required_article_identity_stays_required():
    with pytest.raises(KeyError):
        condition_value({'articles': [{}]}, {'path': 'articles.0.label', 'equals': '제5조의2'})
