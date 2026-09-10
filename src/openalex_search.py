"""
OpenAlex 学术论文搜索模块
从 OpenAlex 拿真实论文，并把原始 JSON 清洗成统一 Paper 对象
"""

# re 用来清洗论文标题，方便后续论文去重
import re

# Any 用来表示 OpenAlex 返回的复杂 JSON 字段
from typing import Any

# requests 用来发送 HTTP 请求
import requests

# 导入统一的论文数据结构
from .models import Paper


class OpenAlexSearcher:
    """通过 OpenAlex API 搜索真实论文"""

    # OpenAlex Works API 地址
    BASE_URL = "https://api.openalex.org/works"

    # 只请求项目真正会使用的字段，减少网络传输
    SELECT_FIELDS = ",".join(
        [
            "id",
            "doi",
            "title",
            "publication_year",
            "authorships",
            "primary_location",
            "cited_by_count",
            "abstract_inverted_index",
        ]
    )

    def __init__(
        self,
        api_key: str = "",
        contact_email: str = "",
        timeout: int = 20,
    ) -> None:

        # 保存可选 OpenAlex API Key
        self.api_key = api_key.strip()

        # 保存可选联系邮箱
        self.contact_email = contact_email.strip()

        # 保存网络请求最大等待时间
        self.timeout = timeout

        # Session 可复用底层 HTTP 连接
        self.session = requests.Session()

        # 设置项目的 User-Agent
        user_agent = "PaperResearchAgent/1.0"

        # 如果提供邮箱，则加入 User-Agent，方便服务方联系
        if self.contact_email:
            user_agent += f" (mailto:{self.contact_email})"

        # 设置所有请求都使用的公共请求头
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": user_agent,
            }
        )

    def search(
        self,
        query: str,
        max_results: int = 8,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> list[Paper]:
        """根据关键词搜索并返回 Paper论文列表"""

        # 清洗用户/Agent 生成的检索词
        query = query.strip()

        # 空检索词没有意义，直接拒绝
        if not query:
            raise ValueError("论文检索词不能为空。")

        # 项目限制一次最多保留 20 篇，避免 Prompt 过大
        if not 1 <= max_results <= 20:
            raise ValueError("max_results 必须位于 1 到 20 之间。")

        # 同时填写起止年份时检查顺序
        if start_year is not None and end_year is not None and start_year > end_year:
            raise ValueError("start_year 不能大于 end_year。")

        # OpenAlex 过滤条件列表
        filters = [
            # WriterAgent 需要摘要作为证据，因此只搜索有摘要的论文
            "has_abstract:true",
        ]

        # 如果指定最早年份，则加入日期下界
        if start_year is not None:
            filters.append(f"from_publication_date:{start_year}-01-01")

        # 如果指定最晚年份，则加入日期上界
        if end_year is not None:
            filters.append(f"to_publication_date:{end_year}-12-31")

        # 多请求一些结果，为摘要缺失/重复论文留出余量
        request_count = min(max(max_results * 2, 10), 50)

        # 构造 OpenAlex 查询参数
        params: dict[str, str | int] = {
            # search 会搜索论文标题、摘要和全文索引
            "search": query,
            # 每页请求多少条
            "per_page": request_count,
            # 多个过滤条件使用逗号连接，表示 AND
            "filter": ",".join(filters),
            # 搜索场景下按相关性从高到低排列
            "sort": "relevance_score:desc",
            # 只返回指定字段
            "select": self.SELECT_FIELDS,
        }

        # 用户配置了 Key 才发送
        if self.api_key:
            params["api_key"] = self.api_key

        try:
            # 发送 GET 请求
            response = self.session.get(
                self.BASE_URL,
                params=params,
                timeout=self.timeout,
            )

            # HTTP 非成功状态时主动抛出异常
            response.raise_for_status()

        except requests.RequestException as exc:
            # 转换成项目层更容易理解的错误信息
            raise RuntimeError(f"OpenAlex 请求失败：{exc}") from exc

        try:
            # 将响应 JSON 转成 Python 字典
            data = response.json()

        except ValueError as exc:
            # 服务端返回非 JSON 时给出明确错误。
            raise RuntimeError("OpenAlex 返回的数据不是合法 JSON。") from exc

        # OpenAlex 列表接口把实体放在 results 数组中
        raw_results = data.get("results", [])

        # 用于保存标准化后的论文
        papers: list[Paper] = []

        # 遍历原始论文 JSON
        for work in raw_results:
            # 将 OpenAlex JSON 转成统一 Paper 对象
            paper = self._convert_work_to_paper(work)

            # 没有标题的记录没有使用价值
            if not paper.title:
                continue

            # 本项目按摘要写作，没有摘要也跳过
            if not paper.abstract:
                continue

            # 保存有效论文
            papers.append(paper)

        # DOI 优先、标题兜底进行去重
        papers = self._deduplicate(papers)

        # 只保留用户需要的数量
        papers = papers[:max_results]

        # 去重完成后重新生成 P1、P2 编号
        for index, paper in enumerate(papers, start=1):
            paper.paper_id = f"P{index}"

        # 返回最终论文列表
        return papers

    def _convert_work_to_paper(self, work: dict[str, Any]) -> Paper:
        """将一个 OpenAlex Work JSON 转换成 Paper"""

        # 获取论文标题
        title = (work.get("title") or "").strip()

        # 获取 OpenAlex 唯一 ID
        openalex_id = (work.get("id") or "").strip()

        # 获取发表年份
        year = work.get("publication_year")

        # 获取被引次数，空值按 0 处理
        cited_by_count = int(work.get("cited_by_count") or 0)

        # 从 authorships 中提取作者姓名
        authors = self._extract_authors(work.get("authorships") or [])

        # primary_location 保存论文主要发表位置
        primary_location = work.get("primary_location") or {}

        # 从主要位置中提取期刊/会议来源
        venue = self._extract_venue(primary_location)

        # 清理 DOI URL 前缀，只保留纯 DOI
        doi = self._clean_doi(work.get("doi") or "")

        # OpenAlex 摘要是倒排索引，需要恢复成普通文本
        abstract = self.rebuild_abstract(work.get("abstract_inverted_index"))

        # 有 DOI 时优先使用 DOI 页面作为论文链接
        if doi:
            url = f"https://doi.org/{doi}"
        else:
            # 没有 DOI 时使用 landing page，仍没有则使用 OpenAlex 页面
            url = primary_location.get("landing_page_url") or openalex_id

        # 返回统一论文对象
        return Paper(
            paper_id="",  # P 编号会在去重后统一生成
            openalex_id=openalex_id,
            title=title,
            authors=authors,
            year=year,
            venue=venue,
            doi=doi,
            url=url,
            abstract=abstract,
            cited_by_count=cited_by_count,
        )

    @staticmethod
    def rebuild_abstract(inverted_index: dict[str, list[int]] | None) -> str:
        """将 OpenAlex abstract_inverted_index 恢复为普通摘要"""

        # 没有摘要索引时返回空字符串
        if not inverted_index:
            return ""

        # key 是单词位置，value 是对应单词
        position_to_word: dict[int, str] = {}

        # 遍历倒排索引中的每个单词
        for word, positions in inverted_index.items():
            # 一个单词可能在摘要里出现多次
            for position in positions:
                # 按原始位置记录单词
                position_to_word[position] = word

        # 从小到大排序位置，然后重新拼成句子
        abstract = " ".join(
            position_to_word[position]
            for position in sorted(position_to_word)
        )

        # 返回清理后的摘要
        return abstract.strip()

    @staticmethod
    def _extract_authors(authorships: list[dict[str, Any]]) -> list[str]:
        """从 authorships 中提取作者姓名"""

        # 保存作者姓名
        authors: list[str] = []

        # 遍历作者关系
        for authorship in authorships:
            # 获取嵌套 author 对象
            author = authorship.get("author") or {}

            # 获取作者显示名称
            name = (author.get("display_name") or "").strip()

            # 只保存非空姓名
            if name:
                authors.append(name)

        # 返回作者列表
        return authors

    @staticmethod
    def _extract_venue(primary_location: dict[str, Any]) -> str:
        """获取论文的期刊、会议或其他出版来源"""

        # source 保存出版来源信息
        source = primary_location.get("source") or {}

        # display_name 是可读的来源名称
        venue = source.get("display_name") or ""

        # 保证最终返回干净字符串
        return venue.strip()

    @staticmethod
    def _clean_doi(doi: str) -> str:
        """将 DOI URL 统一清理成纯 DOI。"""

        # 去掉首尾空格
        doi = doi.strip()

        # 常见 DOI URL 前缀
        prefix = "https://doi.org/"

        # 大小写不敏感地判断 URL 前缀
        if doi.lower().startswith(prefix):
            # 删除 URL 前缀
            doi = doi[len(prefix):]

        # 返回纯 DOI
        return doi.strip()

    def _deduplicate(self, papers: list[Paper]) -> list[Paper]:
        """优先使用 DOI、没有 DOI 时使用标题进行去重"""

        # 保存已经出现过的唯一标识
        seen: set[str] = set()

        # 保存去重结果
        unique_papers: list[Paper] = []

        # 按 OpenAlex 已给出的相关性顺序遍历
        for paper in papers:
            if paper.doi:
                key = f"doi:{paper.doi.lower()}"
            else:
                # 没有 DOI 时退化为标准化标题
                key = f"title:{self._normalize_title(paper.title)}"

            # 已经出现则跳过
            if key in seen:
                continue

            # 记录唯一标识
            seen.add(key)

            # 保存论文
            unique_papers.append(paper)

        # 返回去重后的列表
        return unique_papers

    @staticmethod
    def _normalize_title(title: str) -> str:
        """把标题转成便于去重的标准形式"""

        # 全部转成小写
        title = title.lower()

        # 删除标点、空格和下划线，只保留字母数字
        title = re.sub(r"[\W_]+", "", title)

        # 返回标准化标题
        return title
