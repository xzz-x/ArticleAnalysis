from __future__ import annotations

import json

from research.extract_today_star_har import analyze


def test_history_star_candidate_is_ranked_and_secrets_are_redacted() -> None:
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "POST",
                        "url": (
                            "https://api.example.test/history/star"
                            "?token=secret-token&start=2018-01-01"
                        ),
                        "postData": {
                            "mimeType": "application/json",
                            "text": json.dumps(
                                {
                                    "authorization": "secret-auth",
                                    "startDate": "2018-01-01",
                                }
                            ),
                        },
                    },
                    "response": {
                        "status": 200,
                        "content": {
                            "mimeType": "application/json",
                            "text": json.dumps(
                                {
                                    "data": [
                                        {
                                            "date": "2018-01-02",
                                            "star": 5.0,
                                            "indexCode": "000985",
                                        },
                                        {
                                            "date": "2018-01-03",
                                            "star": 4.9,
                                            "indexCode": "000985",
                                        },
                                    ]
                                }
                            ),
                        },
                    },
                },
                {
                    "request": {
                        "method": "GET",
                        "url": "https://api.example.test/profile",
                    },
                    "response": {
                        "status": 200,
                        "content": {
                            "mimeType": "application/json",
                            "text": json.dumps({"name": "test-user"}),
                        },
                    },
                },
            ]
        }
    }

    candidates = analyze(har)

    assert len(candidates) == 1
    candidate = candidates[0]

    assert candidate["host"] == "api.example.test"
    assert candidate["path"] == "/history/star"
    assert candidate["response"]["date_samples"] == [
        "2018-01-02",
        "2018-01-03",
    ]
    assert candidate["response"]["star_field_samples"][0]["value"] == 5.0

    assert "secret-token" not in candidate["url"]
    assert candidate["request_body"]["authorization"] == "<redacted>"
    assert "response:000985" in candidate["reasons"]
    assert "star_like_field" in candidate["reasons"]
