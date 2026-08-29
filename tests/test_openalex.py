"""OpenAlex 客户端的纯函数部分。

碰网络的 fetch_json() 不在这里测——与 llm/claude.py 的 request()、
editor.py 的 $EDITOR 同一个约定：网络收窄到一处，其余用 fixture 测。
"""

from __future__ import annotations

import pytest

from ari.openalex import (
    Budget,
    bare_doi,
    OpenAlexUnavailable,
    build_ids_url,
    build_url,
    normalize,
    parse_budget,
    reconstruct_abstract,
    short_id,
    user_agent,
)


def test_short_id_keeps_the_work_number_not_the_url():
    """事件流里存短 ID：URL 前缀会变，W 号不会。"""
    assert short_id("https://openalex.org/W2095705004") == "W2095705004"
    assert short_id("W2095705004") == "W2095705004"
    assert short_id("") == ""


def test_reconstruct_abstract_from_the_inverted_index():
    """OpenAlex 不给 abstract 原文，只给 {词: [位置...]}。"""
    inverted = {"Dropout": [0], "is": [1], "a": [2], "technique": [3]}

    assert reconstruct_abstract(inverted) == "Dropout is a technique"


def test_reconstruct_abstract_handles_repeats_and_gaps():
    """同一个词出现在多处；位置也可能不连续（原文里被剔掉的词）。"""
    inverted = {"the": [0, 4], "cat": [1], "sat": [2], "mat": [6]}

    # 缺位不补空格，按序号拼接即可
    assert reconstruct_abstract(inverted) == "the cat sat the mat"


@pytest.mark.parametrize("bad", [None, {}, "不是字典", {"词": "不是列表"}])
def test_reconstruct_abstract_survives_missing_or_malformed(bad):
    """没有摘要是常态，不是异常——很多条目本来就没有。"""
    assert reconstruct_abstract(bad) == ""


def test_normalize_a_complete_work():
    raw = {
        "id": "https://openalex.org/W2095705004",
        "ids": {"openalex": "https://openalex.org/W2095705004", "doi": "https://doi.org/10.5555/x"},
        "title": "Dropout: a simple way to prevent neural networks from overfitting",
        "publication_year": 2014,
        "cited_by_count": 34236,
        "referenced_works": ["https://openalex.org/W1", "https://openalex.org/W2"],
        "abstract_inverted_index": {"Deep": [0], "nets": [1]},
        "authorships": [
            {"author": {"display_name": "Nitish Srivastava"}},
            {"author": {"display_name": "Geoffrey Hinton"}},
        ],
        "primary_location": {"source": {"display_name": "JMLR"}},
    }

    paper = normalize(raw)

    assert paper.work == "W2095705004"
    assert paper.year == 2014
    assert paper.cited_by == 34236
    assert paper.authors == ["Nitish Srivastava", "Geoffrey Hinton"]
    assert paper.venue == "JMLR"
    assert paper.abstract == "Deep nets"
    assert paper.doi == "10.5555/x"
    assert paper.referenced == ["W1", "W2"]


def test_normalize_tolerates_the_nulls_openalex_actually_returns():
    """primary_location、doi、authorships 都可能是 null 或缺失。

    实测：Dropout 那篇 JMLR 在 OpenAlex 里 doi 就是 null。所以主键必须是
    Work ID，把 DOI 当主键会丢掉真实存在的论文。
    """
    paper = normalize(
        {
            "id": "https://openalex.org/W2095705004",
            "title": "Dropout: a simple way to prevent neural networks from overfitting",
            "publication_year": 2014,
            "primary_location": None,
            "ids": {"openalex": "https://openalex.org/W2095705004"},
        }
    )

    assert paper.work == "W2095705004"
    assert paper.doi == ""
    assert paper.venue == ""
    assert paper.authors == []
    assert paper.abstract == ""
    assert paper.referenced == []
    assert paper.cited_by == 0


def test_normalize_never_leaves_an_empty_title():
    assert normalize({"id": "https://openalex.org/W1", "title": None}).title == "（无标题）"


def test_build_url_carries_query_year_and_select():
    url = build_url("dropout small data", per_page=25, from_year=2021)

    assert url.startswith("https://api.openalex.org/works?")
    assert "search=dropout+small+data" in url
    assert "per_page=25" in url
    assert "from_publication_date%3A2021-01-01" in url
    # referenced_works 是分层算法的输入，必须在 select 里
    assert "referenced_works" in url
    assert "abstract_inverted_index" in url


def test_build_url_caps_per_page():
    """信用点有限，而且再多也读不完。"""
    assert "per_page=200" in build_url("x", per_page=9999)
    assert "per_page=1" in build_url("x", per_page=0)


def test_build_url_refuses_an_empty_query():
    with pytest.raises(OpenAlexUnavailable):
        build_url("   ")


def test_parse_budget_reads_the_credit_headers():
    """限流是信用点制，不是每天 N 次。额度要读出来给人看，不能等 429。"""
    budget = parse_budget(
        {"x-ratelimit-limit": "1000", "x-ratelimit-remaining": "980", "x-ratelimit-reset": "71829"}
    )

    assert budget == Budget(limit=1000, remaining=980, reset_seconds=71829)
    assert budget.exhausted is False


def test_parse_budget_treats_missing_headers_as_unknown_not_as_zero():
    """头缺了是「不知道」，不是「没额度」——否则会无谓地拦住用户。"""
    budget = parse_budget({})

    assert budget.remaining is None
    assert budget.exhausted is False


def test_budget_knows_when_it_is_spent():
    assert Budget(limit=1000, remaining=0).exhausted is True


def test_user_agent_is_polite_when_an_email_is_configured():
    assert user_agent("me@lab.edu") == "ariadne (mailto:me@lab.edu)"
    assert user_agent("") == "ariadne"
    assert user_agent("  ") == "ariadne"


def test_bare_doi_keeps_the_slash_inside_the_doi():
    """DOI 本身含斜杠，按路径段切会把 10.5555/x 截成 x。"""
    assert bare_doi("https://doi.org/10.1145/3292500.3330701") == "10.1145/3292500.3330701"
    assert bare_doi("doi:10.5555/x") == "10.5555/x"
    assert bare_doi("10.5555/x") == "10.5555/x"
    assert bare_doi("") == ""


def test_build_ids_url_batches_works():
    """分层的第二步：里程碑通常不在种子集里，要按 ID 取回来。"""
    url = build_ids_url(["W1", "https://openalex.org/W2", "W3"])

    assert "filter=openalex_id:W1|W2|W3" in url
    assert "per_page=3" in url


def test_build_ids_url_caps_the_batch():
    """filter 拼在 query string 里，太长会被拒。"""
    url = build_ids_url([f"W{i}" for i in range(200)])

    assert url.count("|") == 49  # 50 个 ID，49 个分隔符
    assert "per_page=50" in url


def test_build_ids_url_refuses_an_empty_batch():
    with pytest.raises(OpenAlexUnavailable):
        build_ids_url(["", None])
