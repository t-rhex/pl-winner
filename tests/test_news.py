from src.fpl import parse_news_discount


def test_parse_news_available_default():
    assert parse_news_discount("a", "") == 1.0
    assert parse_news_discount("a", "Knock - 75% chance of playing") == 1.0


def test_parse_news_suspended_status():
    assert parse_news_discount("s", "") == 0.0


def test_parse_news_unavailable_status():
    assert parse_news_discount("u", "") == 0.0
    assert parse_news_discount("n", "") == 0.0


def test_parse_news_red_card_in_text():
    assert parse_news_discount("a", "Red card - 1 match suspension") == 0.0


def test_parse_news_season_out():
    assert parse_news_discount("a", "Out for the season") == 0.0


def test_parse_news_transferred():
    assert parse_news_discount("a", "Transferred to Real Madrid") == 0.0
    assert parse_news_discount("a", "Has left the club") == 0.0
