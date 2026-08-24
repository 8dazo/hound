from hound.fetchers.changelog_scraper import ChangelogScraper


def test_parse_rss_feed():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Stripe API Changelog</title>
    <item>
      <title>Version 2026-05-01 Released</title>
      <pubDate>Mon, 01 May 2026 00:00:00 GMT</pubDate>
      <description>&lt;p&gt;Field &lt;code&gt;source&lt;/code&gt; is deprecated on /v1/charges.&lt;/p&gt;</description>
      <link>https://stripe.com/changelog/2026-05-01</link>
    </item>
  </channel>
</rss>
"""
    scraper = ChangelogScraper()
    entries = scraper.parse_feed(xml)
    assert len(entries) == 1
    assert entries[0].title == "Version 2026-05-01 Released"
    assert "source is deprecated" in entries[0].content
    assert entries[0].url == "https://stripe.com/changelog/2026-05-01"

    chunks = scraper.to_doc_chunks(entries)
    assert len(chunks) == 1
    assert "Version 2026-05-01 Released" in chunks[0].heading


def test_parse_html_changelog():
    html_doc = """
<html>
<body>
  <article>
    <h2>Breaking: Removed legacy endpoints</h2>
    <p>The <code>/v1/tokens</code> endpoint has been sunset and removed.</p>
  </article>
  <article>
    <h2>New features in May</h2>
    <p>Added support for instant payouts across 5 new regions.</p>
  </article>
</body>
</html>
"""
    scraper = ChangelogScraper()
    entries = scraper.parse_html(html_doc)
    assert len(entries) == 2
    assert entries[0].title == "Breaking: Removed legacy endpoints"
    assert "/v1/tokens endpoint has been sunset" in entries[0].content
