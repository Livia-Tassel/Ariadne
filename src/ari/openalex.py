"""OpenAlex 客户端。见 v0.5 spec §3。

只有 `fetch_json()` 碰网络，其余全是纯函数——与 llm/claude.py 的
request()、editor.py 的 $EDITOR 是同一个结构，测试不调它。

三处接口实情是对着 api.openalex.org 实测的，不是凭记忆写的：

1. 不需要 API key，直接 GET。
2. 限流是**信用点**制，不是「每天 N 次」。响应头给出预算，一次取 25 篇
   带 referenced_works 的检索约花 10 点，池子 1000 点、约 20 小时重置。
   所以额度要读出来给人看，不能等到 429 才说。
3. 稳定标识是 OpenAlex Work ID（W2095705004），**不是 DOI**——Dropout
   那篇 JMLR 的 doi 字段就是 null，arXiv ID 也不保证存在。
4. 摘要只有倒排索引，没有原文字段，要自己还原。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

API = "https://api.openalex.org/works"

# 一次检索取回的论文数上限。再多也读不完，而且信用点是有限的。
MAX_PER_PAGE = 200

_SELECT = (
    "id,ids,title,publication_year,cited_by_count,referenced_works,"
    "abstract_inverted_index,authorships,primary_location,type"
)


class OpenAlexUnavailable(RuntimeError):
    """这次拿不到文献。调用方应当降级，不应当中断。

    与 LLMUnavailable 同一个角色：所有失败——断网、限流、返回不是 JSON、
    服务改了字段——对调用方而言没有区别，都是「这次抓不到」。只有收敛成
    一种，降级代码才写得干净。
    """


@dataclass(frozen=True)
class Budget:
    """限流预算，从响应头读出来。"""

    limit: int | None = None
    remaining: int | None = None
    reset_seconds: int | None = None

    @property
    def exhausted(self) -> bool:
        return self.remaining is not None and self.remaining <= 0


@dataclass(frozen=True)
class Paper:
    work: str  # W2095705004，主键
    title: str
    year: int | None
    authors: list[str] = field(default_factory=list)
    venue: str = ""
    cited_by: int = 0
    abstract: str = ""
    doi: str = ""
    referenced: list[str] = field(default_factory=list)


def short_id(url_or_id: str) -> str:
    """https://openalex.org/W2095705004 → W2095705004

    事件流里存短 ID：URL 前缀会变，W 号不会。
    """
    if not url_or_id:
        return ""
    return str(url_or_id).rstrip("/").rsplit("/", 1)[-1]


def bare_doi(url: str) -> str:
    """https://doi.org/10.5555/x → 10.5555/x

    DOI 本身含斜杠，不能按路径段切——那会把 10.5555/x 截成 x。
    """
    raw = (url or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if raw.lower().startswith(prefix):
            return raw[len(prefix):]
    return raw


def reconstruct_abstract(inverted: dict | None) -> str:
    """从 abstract_inverted_index 还原摘要原文。

    OpenAlex 不给 abstract 字段，只给 {词: [位置...]}。实测 Attention Is
    All You Need 能还原出 1136 字符的完整摘要，足够做「值不值得精读」和
    「它相对于那篇改了什么」的判断。

    位置可能不连续（原文里被剔掉的词），按序号排序拼接即可，不补空位。
    """
    if not isinstance(inverted, dict) or not inverted:
        return ""
    at: dict[int, str] = {}
    for word, positions in inverted.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                at[position] = word
    return " ".join(at[i] for i in sorted(at))


def parse_budget(headers) -> Budget:
    """从响应头读限流预算。头缺失或不是数字都当作未知，不抛异常。"""

    def number(name):
        raw = headers.get(name) if headers else None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    return Budget(
        limit=number("x-ratelimit-limit"),
        remaining=number("x-ratelimit-remaining"),
        reset_seconds=number("x-ratelimit-reset"),
    )


def normalize(raw: dict) -> Paper:
    """一条 OpenAlex Work → Paper。缺字段一律给安全的默认值。

    primary_location 与 doi 都可能是 null，authorships 里也可能没有
    display_name——这些不是异常情况，是常态。
    """
    location = raw.get("primary_location") or {}
    source = location.get("source") or {}
    authors = []
    for item in raw.get("authorships") or []:
        author = (item or {}).get("author") or {}
        name = author.get("display_name")
        if name:
            authors.append(name)
    return Paper(
        work=short_id(raw.get("id") or ""),
        title=(raw.get("title") or "").strip() or "（无标题）",
        year=raw.get("publication_year"),
        authors=authors,
        venue=(source.get("display_name") or "").strip(),
        cited_by=raw.get("cited_by_count") or 0,
        abstract=reconstruct_abstract(raw.get("abstract_inverted_index")),
        doi=bare_doi((raw.get("ids") or {}).get("doi") or ""),
        referenced=[short_id(ref) for ref in (raw.get("referenced_works") or [])],
    )


def build_url(query: str, *, per_page: int = 50, from_year: int | None = None) -> str:
    """把检索式拼成请求 URL。纯函数，可测。"""
    query = (query or "").strip()
    if not query:
        raise OpenAlexUnavailable("检索式不能为空")
    per_page = max(1, min(int(per_page), MAX_PER_PAGE))

    filters = ["type:article"]
    if from_year:
        filters.append(f"from_publication_date:{int(from_year)}-01-01")

    params = {
        "search": query,
        "filter": ",".join(filters),
        "per_page": str(per_page),
        "select": _SELECT,
        "sort": "relevance_score:desc",
    }
    return f"{API}?{urllib.parse.urlencode(params)}"


# 一次 URL 里塞的 ID 数上限。OpenAlex 的 filter 是拼在 query string 里的，
# 太长会被拒；50 个已经远超一次调研需要的里程碑数量。
MAX_IDS = 50


def build_ids_url(works: list[str]) -> str:
    """按 Work ID 批量取元数据。

    分层需要两步：先取种子集算内部被引，再按 ID 把里程碑本身取回来——
    里程碑通常**不在**种子集里（种子集限定了近几年，而地基论文是老的）。
    """
    ids = [short_id(work) for work in works if short_id(work)]
    if not ids:
        raise OpenAlexUnavailable("没有要查的 Work ID")
    if len(ids) > MAX_IDS:
        ids = ids[:MAX_IDS]
    params = {
        "filter": "openalex_id:" + "|".join(ids),
        "per_page": str(len(ids)),
        "select": _SELECT,
    }
    return f"{API}?{urllib.parse.urlencode(params, safe='|:')}"


def user_agent(mailto: str = "") -> str:
    """礼貌起见带上联系邮箱。不带也能用，实测额度一样。"""
    mailto = (mailto or "").strip()
    return f"ariadne (mailto:{mailto})" if mailto else "ariadne"


def fetch_json(url: str, *, mailto: str = "", timeout: int = 30) -> tuple[dict, Budget]:
    """本模块唯一碰网络的函数。所有失败收敛成 OpenAlexUnavailable。"""
    request = urllib.request.Request(url, headers={"User-Agent": user_agent(mailto)})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            budget = parse_budget(response.headers)
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            retry = exc.headers.get("Retry-After") if exc.headers else None
            hint = f"，{retry} 秒后再试" if retry else ""
            raise OpenAlexUnavailable(f"OpenAlex 额度用尽{hint}") from exc
        raise OpenAlexUnavailable(f"OpenAlex 返回 {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise OpenAlexUnavailable(f"连不上 OpenAlex：{exc.reason}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OpenAlexUnavailable(f"OpenAlex 返回的不是合法 JSON：{exc}") from exc
    if not isinstance(body, dict):
        raise OpenAlexUnavailable("OpenAlex 返回的顶层不是一个对象")
    return body, budget


def search(
    query: str, *, per_page: int = 50, from_year: int | None = None, mailto: str = ""
) -> tuple[list[Paper], Budget]:
    """按检索式取一批论文。失败一律 OpenAlexUnavailable。"""
    body, budget = fetch_json(build_url(query, per_page=per_page, from_year=from_year), mailto=mailto)
    results = body.get("results")
    if not isinstance(results, list):
        raise OpenAlexUnavailable("OpenAlex 的响应里没有 results")
    papers = [normalize(item) for item in results if isinstance(item, dict)]
    return [paper for paper in papers if paper.work], budget


def fetch_by_ids(works: list[str], *, mailto: str = "") -> tuple[list[Paper], Budget]:
    """按 Work ID 批量取元数据。失败一律 OpenAlexUnavailable。"""
    body, budget = fetch_json(build_ids_url(works), mailto=mailto)
    results = body.get("results")
    if not isinstance(results, list):
        raise OpenAlexUnavailable("OpenAlex 的响应里没有 results")
    papers = [normalize(item) for item in results if isinstance(item, dict)]
    return [paper for paper in papers if paper.work], budget
