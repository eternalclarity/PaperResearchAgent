"""定义统一的论文数据模型 Paper"""

# dataclass 用来快速定义只保存数据的类
from dataclasses import asdict, dataclass


@dataclass
class Paper:
    """论文数据类"""

    # 程序内部论文编号，例如 P1、P2
    paper_id: str

    # OpenAlex 为论文分配的唯一 ID
    openalex_id: str

    # 论文标题
    title: str

    # 作者姓名列表
    authors: list[str]

    # 发表年份；缺失时为 None
    year: int | None

    # 期刊、会议或其他出版来源
    venue: str

    # DOI；缺失时为空字符串
    doi: str

    # 论文可访问页面
    url: str

    # 论文摘要
    abstract: str

    # OpenAlex 中的被引次数
    cited_by_count: int = 0

    def to_dict(self) -> dict:
        """转换为普通字典，便于写入 JSON"""

        # asdict 会自动把 dataclass 的所有字段转成 dict
        return asdict(self)

    def to_prompt_block(self, max_abstract_chars: int = 2200) -> str:
        """整理成适合发送给 WriterAgent 的证据文本"""

        # 作者不存在时给出明确占位文本
        authors_text = ", ".join(self.authors) if self.authors else "Unknown authors"

        # 年份不存在时避免输出 Python 的 None
        year_text = str(self.year) if self.year is not None else "Unknown"

        # 出版来源不存在时给出占位文本
        venue_text = self.venue if self.venue else "Unknown"

        # DOI 不存在时明确说明
        doi_text = self.doi if self.doi else "None"

        # 默认使用完整摘要
        abstract_text = self.abstract

        # 摘要过长时截断，避免一次 Prompt 太大
        if len(abstract_text) > max_abstract_chars:
            abstract_text = abstract_text[:max_abstract_chars].rstrip() + " ..."

        # 用固定格式返回，方便模型区分不同字段
        return (
            f"Paper ID: {self.paper_id}\n"
            f"Title: {self.title}\n"
            f"Authors: {authors_text}\n"
            f"Year: {year_text}\n"
            f"Venue: {venue_text}\n"
            f"DOI: {doi_text}\n"
            f"Cited by: {self.cited_by_count}\n"
            f"Abstract:\n{abstract_text}"
        )
