from pathlib import Path

from app.services import file_processor
from app.services.email_extractor import (
    FoundEmail, dedupe_emails, decode_cfemail, extract_emails_from_text, extract_from_html, normalize_email,
)

from tests.conftest import html


def emails(markup: str):
    return {e.email for e in extract_from_html(markup, "https://acme.test/").emails}


def test_extracts_visible_text_emails():
    assert emails(html("<p>Write to Info@Acme-Packaging.com or call us.</p>")) == {"info@acme-packaging.com"}


def test_preserves_original_display_value_but_normalizes():
    data = extract_from_html(html("<p>Sales@ACME-Packaging.com</p>"))
    assert data.emails[0].email == "sales@acme-packaging.com"
    assert data.emails[0].original == "Sales@ACME-Packaging.com"


def test_extracts_mailto_links_and_strips_query_string():
    data = extract_from_html(html('<a href="mailto:Quotes@Acme.com?subject=Hello%20there">Get a quote</a>'))
    assert [e.email for e in data.emails] == ["quotes@acme.com"]
    assert data.emails[0].origin == "mailto"


def test_mailto_with_multiple_recipients():
    assert emails(html('<a href="mailto:a@acme.com,b@acme.com">team</a>')) == {"a@acme.com", "b@acme.com"}


def test_deduplicates_same_email_in_mailto_and_text_case_insensitive():
    data = extract_from_html(html('<a href="mailto:info@acme.com">info@acme.com</a> and INFO@ACME.COM'))
    assert len(data.emails) == 1


def test_dedupe_helper_keeps_first():
    out = dedupe_emails([FoundEmail("a@x.com", "A@x.com"), FoundEmail("a@x.com", "a@X.com"), FoundEmail("b@x.com", "b@x.com")])
    assert [e.original for e in out] == ["A@x.com", "b@x.com"]


def test_obfuscated_bracketed_at_dot():
    assert emails(html("<p>orders [at] acme [dot] com</p>")) == {"orders@acme.com"}


def test_plain_word_at_is_not_treated_as_obfuscation():
    assert emails(html("<p>meet us at acme dot com tomorrow</p>")) == set()


def test_cloudflare_protected_email_is_decoded():
    key = 0x42
    encoded = f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in "hello@acme.com")
    assert decode_cfemail(encoded) == "hello@acme.com"
    assert emails(html(f'<span data-cfemail="{encoded}">[email protected]</span>')) == {"hello@acme.com"}


def test_scripts_styles_and_filenames_and_placeholders_are_ignored():
    markup = html('<script>var x="tracker@evil.com"</script><style>.a{}</style><img src="logo@2x.png"><p>logo@2x.png you@example.com name@domain.com</p>')
    assert emails(markup) == set()


def test_json_ld_email_and_business_details():
    ld = '<script type="application/ld+json">{"@type":"LocalBusiness","name":"Acme Boxes","email":"hi@acme.com","telephone":"+1 303 555 0100","address":{"addressLocality":"Denver","addressRegion":"CO","addressCountry":"US"}}</script>'
    data = extract_from_html(html(ld))
    assert [e.email for e in data.emails] == ["hi@acme.com"]
    assert (data.business_name, data.city, data.state, data.country) == ("Acme Boxes", "Denver", "Colorado", "United States")


def test_business_name_from_title_skips_generic_words():
    assert extract_from_html("<title>Contact Us | Acme Boxes</title><p>x</p>").business_name == "Acme Boxes"


def test_empty_and_garbage_input_do_not_raise():
    assert extract_from_html("").emails == []
    assert extract_from_html("<<<>>><p unclosed").emails == []
    assert extract_emails_from_text("") == []


def test_trailing_punctuation_is_removed():
    assert [e.email for e in extract_emails_from_text("Email us: sales@acme.com.")] == ["sales@acme.com"]
    assert normalize_email("mailto:Sales@Acme.com?subject=x") == "sales@acme.com"


def test_extracts_emails_from_text_file(tmp_path: Path):
    f = tmp_path / "contacts.txt"
    f.write_text("Acme: info@acme.com\nBeta - Sales@Beta.org; duplicate: info@acme.com\nsee www.acme.com", encoding="utf-8")
    res = file_processor.extract_file(f, "contacts.txt")
    assert {e.email for e in res.emails} == {"info@acme.com", "sales@beta.org"}
    assert res.unique_emails == 2 and res.duplicate_emails == 1
    assert [u.url for u in res.urls] == ["https://www.acme.com/"]
