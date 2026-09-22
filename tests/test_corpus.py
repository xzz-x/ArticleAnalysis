from pathlib import Path

from article_analysis.corpus import ingest_corpus


def test_markdown_title_preserves_decimal_and_is_canonical(tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    stem = "[2025-02-19-2154]2月19日指数估值数据A股上涨回到49星"
    (corpus / f"{stem}.md").write_text(
        "# ［2月19日］指数估值数据(A股上涨，回到4.9星）\n\n"
        "_2025年02月19日 21:54_\n\n今天大盘整体上涨，截止到收盘，又回到4.9星。\n",
        encoding="utf-8",
    )
    (corpus / f"{stem}.html").write_text(
        "<html><head>"
        "<meta property='og:title' content='［2月19日］指数估值数据(A股上涨，回到4.9星）'>"
        "<meta property='og:url' content='https://mp.weixin.qq.com/s/example'>"
        "</head><body>今天大盘整体上涨，截止到收盘，又回到4.9星。</body></html>",
        encoding="utf-8",
    )

    df = ingest_corpus(
        corpus,
        tmp_path / "articles.parquet",
        tmp_path / "manifest.parquet",
        [".md", ".html"],
    )

    canonical = df[df["is_canonical"]]
    assert len(canonical) == 1
    row = canonical.iloc[0]
    assert row["suffix"] == ".md"
    assert "4.9星" in row["title"]
    assert row["publish_date"] == "2025-02-19"

    html_row = df[df["suffix"] == ".html"].iloc[0]
    assert html_row["source_url"] == "https://mp.weixin.qq.com/s/example"
    assert row["source_url"] == "https://mp.weixin.qq.com/s/example"
