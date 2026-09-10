"""论文引用校验、编号与 BibTeX 生成模块"""

# re 用来识别正文中的 P1、P2 等内部论文编号
import re

# 导入论文数据结构
from .models import Paper


# 匹配 P1、P2、P10 等论文 ID
PAPER_ID_PATTERN = re.compile(r"\bP\d+\b")


def collect_citation_ids(text: str) -> set[str]:
    """找出正文中出现过的所有 Paper ID"""

    # findall 返回全部匹配结果，set 自动去重
    return set(PAPER_ID_PATTERN.findall(text))


def find_invalid_citations(text: str, papers: list[Paper]) -> set[str]:
    """找出 LLM 使用但程序没有提供的虚构 Paper ID"""

    # 提取正文使用过的 ID
    used_ids = collect_citation_ids(text)

    # 真实允许使用的 ID 来自 OpenAlex 搜索结果
    valid_ids = {paper.paper_id for paper in papers}

    # 集合差集就是不存在的引用
    return used_ids - valid_ids


def get_cited_papers(text: str, papers: list[Paper]) -> list[Paper]:
    """按原搜索顺序返回正文真正引用到的论文"""

    # 获取正文出现过的 Paper ID
    used_ids = collect_citation_ids(text)

    # 保持原论文顺序，只挑出真正被引用的论文
    return [paper for paper in papers if paper.paper_id in used_ids]


def replace_paper_ids_with_numbers(text: str, cited_papers: list[Paper]) -> str:
    """将内部 [P1] [P3] 等引用转换为最终 [1] [2]等数字引用"""

    # 只针对实际引用论文重新建立连续编号
    mapping = {
        paper.paper_id: str(index)
        for index, paper in enumerate(cited_papers, start=1)
    }

    def replace(match: re.Match) -> str:
        """每遇到一个 P 编号时执行一次替换"""

        # 获取匹配到的 P1、P2 等字符串
        paper_id = match.group(0)

        # 已知 ID 替换成连续数字
        return mapping.get(paper_id, paper_id)

    # 对全文进行替换。
    return PAPER_ID_PATTERN.sub(replace, text)


def _format_authors(authors: list[str]) -> str:
    """将作者列表转换为参考文献作者字符串"""

    # 没有作者信息时给出占位文本
    if not authors:
        return "Unknown author"

    # 三位以内作者全部显示
    if len(authors) <= 3:
        return ", ".join(authors)

    # 作者较多时只显示前三位
    first_three = ", ".join(authors[:3])

    # et al. 表示其余作者
    return f"{first_three}, et al."


def format_reference(paper: Paper, number: int) -> str:
    """生成参考文献"""

    # 整理作者
    authors = _format_authors(paper.authors)

    # 没有年份时使用 n.d.
    year = str(paper.year) if paper.year is not None else "n.d."

    # 没有出版来源时给默认值
    venue = paper.venue if paper.venue else "Unknown venue"

    # 生成参考文献主体
    reference = (
        f'[{number}] {authors}, "{paper.title}," '
        f'{venue}, {year}.'
    )

    # DOI 比普通 URL 更稳定，因此优先输出 DOI
    if paper.doi:
        reference += f" doi: {paper.doi}."
    elif paper.url:
        # 没有 DOI 时至少保留论文页面
        reference += f" {paper.url}"

    # 返回完整参考文献
    return reference


def build_reference_list(cited_papers: list[Paper]) -> str:
    """为正文实际引用到的论文生成参考文献列表"""

    # 保存每一条参考文献
    references: list[str] = []

    # 按最终连续编号生成
    for index, paper in enumerate(cited_papers, start=1):
        references.append(format_reference(paper, index))

    return "\n\n".join(references)


def _escape_bibtex(text: str) -> str:
    """对常见 BibTeX 特殊字符做轻量转义"""

    # & 在 LaTeX 中有特殊含义
    text = text.replace("&", r"\&")

    # % 是 LaTeX 注释符号
    text = text.replace("%", r"\%")

    # # 是 LaTeX 特殊字符
    text = text.replace("#", r"\#")

    # _ 在 LaTeX 文本中需要转义
    text = text.replace("_", r"\_")

    # 返回转义结果
    return text


def build_bibtex_entry(paper: Paper, number: int) -> str:
    """生成BibTeX 条目"""

    # 用年份组成稳定引用 key；缺失年份时使用 nodate
    year_key = str(paper.year) if paper.year is not None else "nodate"

    # 引用 key 不依赖作者姓名，避免非英文姓名/特殊字符问题
    citation_key = f"paper{number}_{year_key}"

    # BibTeX 作者之间用 and 连接
    authors = " and ".join(paper.authors) if paper.authors else "Unknown"

    # 转义可能影响 LaTeX 的特殊字符
    title = _escape_bibtex(paper.title)
    authors = _escape_bibtex(authors)
    venue = _escape_bibtex(paper.venue or "Unknown venue")

    # 开始构造 BibTeX 行
    lines = [
        f"@article{{{citation_key},",
        f"  title = {{{title}}},",
        f"  author = {{{authors}}},",
        f"  journal = {{{venue}}},",
    ]

    # 有年份才写 year 字段
    if paper.year is not None:
        lines.append(f"  year = {{{paper.year}}},")

    # 有 DOI 才写 DOI 字段
    if paper.doi:
        lines.append(f"  doi = {{{paper.doi}}},")

    # 有 URL 才写 URL 字段
    if paper.url:
        lines.append(f"  url = {{{paper.url}}},")

    # BibTeX 最后一个字段末尾不需要逗号
    if lines[-1].endswith(","):
        lines[-1] = lines[-1][:-1]

    # 结束条目
    lines.append("}")

    # 拼成完整 BibTeX 文本
    return "\n".join(lines)


def build_bibtex(cited_papers: list[Paper]) -> str:
    """为正文实际引用到的论文生成 BibTeX 文件内容"""

    # 逐篇生成条目
    entries = [
        build_bibtex_entry(paper, index)
        for index, paper in enumerate(cited_papers, start=1)
    ]

    # 每个 BibTeX 条目之间空一行
    return "\n\n".join(entries)
