from article_analysis.star_targets import (
    extract_candidates_from_article,
    extract_realtime_observation_from_article,
)


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


def test_daily_observation_excludes_global_market_article():
    row = extract_realtime_observation_from_article(
        title="［2月16日］美股指数估值数据(全球市场更新)",
        text="今天全球市场回到3.1星。",
    )
    assert row is None


def test_daily_observation_prefers_closing_value_over_intraday_value():
    row = extract_realtime_observation_from_article(
        title="［7月9日］指数估值数据(大盘深V反弹)",
        text=(
            "# ［7月9日］指数估值数据(大盘深V反弹)\n"
            "今天大盘上午下跌，回到3.9星。不过下午反弹，"
            "到收盘整体上涨，回到了3.8星。"
        ),
    )
    assert row is not None
    assert row.star == 3.8
    assert row.evidence_method == "closing_statement"


def test_daily_observation_uses_body_decimal_not_rounded_title():
    row = extract_realtime_observation_from_article(
        title="［1月6日］指数估值数据(大盘继续上涨，回到3星级)",
        text=(
            "# ［1月6日］指数估值数据(大盘继续上涨，回到3星级)\n"
            "今天大盘整体上涨，截止到收盘，大盘回到3.9星。"
        ),
    )
    assert row is not None
    assert row.star == 3.9


def test_daily_observation_rejects_range_only_value():
    row = extract_realtime_observation_from_article(
        title="［3月3日］指数估值数据(震荡)",
        text=(
            "# ［3月3日］指数估值数据(震荡)\n"
            "今天大盘上午上涨后回落。全天微涨微跌，还在4.9-5星上下。"
        ),
    )
    assert row is None


def test_daily_observation_falls_back_to_opening_state():
    row = extract_realtime_observation_from_article(
        title="［8月28日］指数估值数据(震荡行情)",
        text=(
            "# ［8月28日］指数估值数据(震荡行情)\n"
            "今天大盘上午波动不大，到下午临近收盘下跌。还在4.1星。"
        ),
    )
    assert row is not None
    assert row.star == 4.1
    assert row.evidence_method == "opening_state_statement"


def test_daily_observation_rejects_second_endpoint_of_range():
    row = extract_realtime_observation_from_article(
        title="［1月17日］指数估值数据(震荡)",
        text=(
            "# ［1月17日］指数估值数据(震荡)\n"
            "今天大盘整体上涨，截止到收盘，在5.1-5.2星上下。"
        ),
    )
    assert row is None


def test_daily_observation_accepts_exact_dated_statement_later_in_body():
    row = extract_realtime_observation_from_article(
        title="［2月17日］指数估值数据(震荡)",
        publish_date="2025-02-17",
        text=(
            "# ［2月17日］指数估值数据(震荡)\n"
            "今天大盘处于4.9-5星边界。\n"
            "目前2025年2月17日，市场在4.9星级，也是适合投资的阶段。"
        ),
    )
    assert row is not None
    assert row.star == 4.9
    assert row.evidence_method == "dated_current_statement"


def test_daily_observation_rejects_mismatched_dated_statement():
    row = extract_realtime_observation_from_article(
        title="［1月6日］指数估值数据(震荡)",
        publish_date="2025-01-06",
        text=(
            "# ［1月6日］指数估值数据(震荡)\n"
            "今天大盘在5.2-5.3星上下。\n"
            "目前2024年1月6日，市场在5.3星级。"
        ),
    )
    assert row is None



def test_historical_hypothetical_five_star_is_not_current_target():
    row = extract_realtime_observation_from_article(
        title="［7月29日］指数估值数据(市场阴跌，离5星级还远吗)",
        publish_date="2022-07-29",
        text=(
            "# ［7月29日］指数估值数据\n"
            "今天大盘整体下跌，目前还是在4.7星级，距离4.8星级不远。\n"
            "如果在今天收盘基础上再下跌6%-7%，才回到5星级。"
        ),
    )
    assert row is not None
    assert row.star == 4.7


def test_historical_prior_period_star_is_not_current_target():
    row = extract_realtime_observation_from_article(
        title="［6月1日］指数估值数据(5星级持续了多久)",
        publish_date="2022-06-01",
        text=(
            "# ［6月1日］指数估值数据\n"
            "今天A股整体波动不大。目前还是在4.9星级。\n"
            "到4月底的时候，回到了5星级。"
        ),
    )
    assert row is not None
    assert row.star == 4.9


def test_historical_midday_star_does_not_override_afternoon_close():
    row = extract_realtime_observation_from_article(
        title="［5月15日］指数估值数据(一波三折)",
        publish_date="2023-05-15",
        text=(
            "# ［5月15日］指数估值数据\n"
            "上周五收盘，大盘距离5星级非常接近。\n"
            "上午下跌，截止到中午收盘，回到了5星级。\n"
            "不过下午反弹，截止到下午收盘，还是在4.9星级。"
        ),
    )
    assert row is not None
    assert row.star == 4.9
    assert row.evidence_method == "closing_statement"


def test_historical_year_reference_is_rejected():
    row = extract_realtime_observation_from_article(
        title="［9月10日］指数估值数据(震荡)",
        publish_date="2024-09-10",
        text=(
            "# ［9月10日］指数估值数据\n"
            "今天A股整体微跌，目前还在5.8星级。\n"
            "2021年初3星级时，大盘处在更高位置。"
        ),
    )
    assert row is not None
    assert row.star == 5.8



def test_historical_closing_transition_uses_final_star():
    row = extract_realtime_observation_from_article(
        title="［9月27日］指数估值数据",
        publish_date="2022-09-27",
        text=(
            "# ［9月27日］指数估值数据\n"
            "今天上午大盘波动不大，不过午后市场突然上涨。"
            "截止到收盘，从5.1星级回到了5星级。"
        ),
    )
    assert row is not None
    assert row.star == 5.0
    assert row.evidence_method == "closing_statement"


def test_historical_fine_current_value_overrides_rounded_regime():
    row = extract_realtime_observation_from_article(
        title="［4月7日］指数估值数据",
        publish_date="2022-04-07",
        text=(
            "# ［4月7日］指数估值数据\n"
            "今天大盘整体下跌，还是在4.5星级。"
            "如果细一些计算，目前算是4.8了。"
        ),
    )
    assert row is not None
    assert row.star == 4.8
    assert row.evidence_method == "fine_current_statement"


def test_historical_prior_month_day_close_is_rejected():
    row = extract_realtime_observation_from_article(
        title="［8月1日］指数估值数据",
        publish_date="2024-08-01",
        text=(
            "# ［8月1日］指数估值数据\n"
            "今天大盘整体下跌，截止到收盘，还在5.7星。"
            "其中7月24、25日两天收盘，回到了5.8星。"
        ),
    )
    assert row is not None
    assert row.star == 5.7


def test_historical_all_day_star_can_use_mo_dao_le_wording():
    row = extract_realtime_observation_from_article(
        title="［2月2日］指数估值数据",
        publish_date="2024-02-02",
        text=(
            "# ［2月2日］指数估值数据\n"
            "今天大盘下午2点半附近一度下跌4.9%。"
            "到2点半之后反弹，全天中证全指下跌2.37%，也摸到了5.9星级，距离5.8星不远。"
        ),
    )
    assert row is not None
    assert row.star == 5.9


def test_2026_01_14_final_afternoon_close_overrides_midday_exact():
    row = extract_realtime_observation_from_article(
        title="［1月14日］指数估值数据",
        publish_date="2026-01-14",
        text=(
            "# ［1月14日］指数估值数据\n"
            "上午上涨，到中午收盘达到3.7星。"
            "不过下午回落，收盘还在3.8星。"
        ),
    )
    assert row is not None
    assert row.star == 3.8
    assert row.evidence_method == "closing_statement"


def test_2026_04_13_final_closing_range_beats_future_conditional_exact():
    row = extract_realtime_observation_from_article(
        title="［4月13日］指数估值数据",
        publish_date="2026-04-13",
        text=(
            "# ［4月13日］指数估值数据\n"
            "到收盘，在4.0到3.9星边界上下。"
            "如果明天继续上涨，也就回到3.9星了。"
        ),
    )
    assert row is None


def test_2026_07_14_final_closing_range_beats_morning_exact():
    row = extract_realtime_observation_from_article(
        title="［7月14日］指数估值数据",
        publish_date="2026-07-14",
        text=(
            "# ［7月14日］指数估值数据\n"
            "上午大盘下跌，回到4.1星。"
            "不过到下午大盘又深V反弹起来。"
            "到收盘，回到4.0-3.9星上下的位置。"
        ),
    )
    assert row is None


def test_historical_explicit_not_returned_star_is_rejected():
    row = extract_realtime_observation_from_article(
        title="［4月6日］指数估值数据",
        publish_date="2021-04-06",
        text=(
            "# ［4月6日］指数估值数据\n"
            "今天A股整体上涨，不过A股也没有回到4星级。"
        ),
    )
    assert row is None


def test_historical_distance_and_future_return_are_rejected():
    row = extract_realtime_observation_from_article(
        title="［3月30日］指数估值数据",
        publish_date="2021-03-30",
        text=(
            "# ［3月30日］指数估值数据\n"
            "今天市场上涨。A股整体距离4星级也不远，等回到4星级再继续行动。"
        ),
    )
    assert row is None
