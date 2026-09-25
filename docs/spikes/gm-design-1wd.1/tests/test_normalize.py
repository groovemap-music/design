"""Normalization and blocking-key rules, on invented values only."""
from normalize import (
    barcode_digits,
    barcode_key,
    catno_adr,
    catno_key,
    fold,
    format_family,
    name_key,
    script_bucket,
    title_key,
    year_of,
)


def test_fold_strips_marks_case_and_punctuation():
    assert fold("Crème Brûlée: Live!") == "creme brulee live"
    assert fold("  A  -  B ") == "a b"
    assert fold(None) == ""


def test_name_key_strips_discogs_disambiguator():
    assert name_key("The Example Quartet (2)") == "the example quartet"
    assert name_key("Band (Live)") == "band live"


def test_title_key_keeps_parenthetical_words():
    assert title_key("Northern Lights (Remastered)") == "northern lights remastered"


def test_barcode_rules():
    assert barcode_digits("0 12345 67890 5") == "012345678905"
    assert barcode_key("0 12345 67890 5") == "0012345678905"
    assert barcode_key("0012345678905") == "0012345678905"
    assert barcode_key("00012345678905") == "0012345678905"
    assert barcode_key("1234") is None
    assert barcode_key("0000000000000") is None
    assert barcode_key("12345670") == "12345670"


def test_catno_rules():
    assert catno_adr("  img   101 ") == "IMG 101"
    assert catno_key("IMG-101") == catno_key("img 101") == "IMG101"
    assert catno_key("[none]") is None
    assert catno_key("none") is None
    assert catno_key("") is None


def test_year_and_format():
    assert year_of("2001-05-00") == "2001"
    assert year_of("0000") is None
    assert year_of(None) is None
    assert format_family('12" Vinyl') == "vinyl"
    assert format_family("CD") == "cd"
    assert format_family("Digital Media") == "digital"
    assert format_family("File") == "digital"
    assert format_family("Cassette") == "cassette"
    assert format_family("Box Set") == "other"
    assert format_family(None) is None


def test_script_bucket():
    assert script_bucket("Northern Lights") == "latin"
    assert script_bucket("Северное сияние") == "non_latin"
    assert script_bucket("1999") == "unknown"


def test_country_keys_map_both_vocabularies():
    from normalize import country_keys

    assert country_keys("GB", "musicbrainz") == {"uk"}
    assert country_keys("XE", "musicbrainz") == {"europe"}
    assert country_keys("ZZ", "musicbrainz") == frozenset()
    assert country_keys("UK & Europe", "discogs") >= {"uk", "europe"}
    assert country_keys("Germany, Austria, & Switzerland", "discogs") >= {"germany", "austria", "switzerland"}
    assert country_keys(None, "discogs") == frozenset()
