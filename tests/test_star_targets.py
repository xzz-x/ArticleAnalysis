from article_analysis.star_targets import extract_candidates_from_article


def test_extract_decimal_star():
    rows = extract_candidates_from_article(
        article_id="a1",
        publish_date="2026-07-16",
        title="7月16日指数估值数据",
        text="目前螺丝钉星级为4.1星，继续耐心投资。",
        relative_path="2026/a1.html",
    )
    assert len(rows) == 1
    assert rows[0].star == 4.1
    assert rows[0].confidence >= 0.9


def test_extract_chinese_half_star():
    rows = extract_candidates_from_article(
        article_id="a2",
        publish_date="2022-01-01",
        title="示例",
        text="市场进入四星半区域。",
        relative_path="2022/a2.html",
    )
    assert rows[0].star == 4.5
