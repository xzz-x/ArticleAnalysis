from article_analysis.star_targets import extract_candidates_from_article


def test_extract_decimal_star():
    rows = extract_candidates_from_article(
        article_id="a1",
        publish_date="2026-07-16",
        title="7月16日指数估值数据",
        text="今天大盘下跌，截止到收盘，目前螺丝钉星级为4.1星。",
        relative_path="2026/a1.html",
    )
    realtime = [row for row in rows if row.source_location == "text" and row.star == 4.1]
    assert realtime
    assert realtime[0].relation == "realtime"
    assert realtime[0].confidence >= 0.99


def test_extract_chinese_half_star():
    rows = extract_candidates_from_article(
        article_id="a2",
        publish_date="2022-01-01",
        title="示例",
        text="市场进入四星半区域。",
        relative_path="2022/a2.html",
    )
    assert any(row.star == 4.5 for row in rows)


def test_compact_downloaded_title_fallback():
    rows = extract_candidates_from_article(
        article_id="a3",
        publish_date="2025-02-19",
        title="2月19日指数估值数据A股上涨回到49星如果回到3星大盘是多少点呢",
        text="今天大盘整体上涨。",
        relative_path="2025/a3.md",
    )
    title_rows = [row for row in rows if row.source_location == "title" and row.star == 4.9]
    assert title_rows
    assert title_rows[0].relation == "realtime"
    assert title_rows[0].confidence == 0.99


def test_rule_range_is_not_realtime():
    rows = extract_candidates_from_article(
        article_id="a4",
        publish_date="2025-07-29",
        title="从5星到3星，不同星级下如何投资",
        text="4星级-4.9星级，还有低估品种，可以做股票基金投资。",
        relative_path="2025/a4.md",
    )
    range_rows = [row for row in rows if row.source_location == "text"]
    assert range_rows
    assert all(row.relation == "range_or_rule" for row in range_rows)
    assert all(row.confidence <= 0.20 for row in range_rows)
