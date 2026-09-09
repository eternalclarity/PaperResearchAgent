"""
PaperResearchAgent 的核心工作流
用户研究主题 -> QueryAgent把主题优化成英文检索词 -> OpenAlexSearcher检索真实论文 -> Paper 对象列表 -> WriterAgent基于论文摘要生成正文 -> Citation 校验检查 [P1] [P2] 是否真实存在 -> 转换引用编号[P1] → [1] -> 生成 References / BibTeX -> 保存
"""

# json 用于保存结构化论文数据
import json

# os 用于读取环境变量
import os

# re 用于轻量清理 QueryAgent 输出
import re

# Path 用于跨平台处理输出目录
from pathlib import Path

# load_dotenv 用于读取项目根目录中的 .env
from dotenv import load_dotenv

# HelloAgentsLLM 负责连接模型, SimpleAgent 用于构建两个简单 Agent
from hello_agents import HelloAgentsLLM, SimpleAgent

# 导入引用处理函数
from .citation import (
    build_bibtex,
    build_reference_list,
    collect_citation_ids,
    find_invalid_citations,
    get_cited_papers,
    replace_paper_ids_with_numbers,
)

# 导入论文数据结构
from .models import Paper

# 导入 OpenAlex 搜索器
from .openalex_search import OpenAlexSearcher


# QueryAgent 只负责把主题整理成适合数据库搜索的英文关键词
QUERY_AGENT_PROMPT = """
你是一名学术文献检索助手。

你的唯一任务是：
把用户给出的研究主题整理成适合 OpenAlex 搜索的简洁英文检索词。

要求：
1. 优先保留最重要的学术概念。
2. 不要生成长句。
3. 不要解释。
4. 不要生成 Markdown。
5. 不要输出 JSON。
6. 只输出一行英文检索关键词。

示例：
用户主题：基于大语言模型的多模态讽刺检测
输出：large language model multimodal sarcasm detection
""".strip()


# WriterAgent 只允许依据传入的真实论文摘要进行写作
WRITER_AGENT_PROMPT = """
你是一名严谨的学术论文写作助手。

你只能依据用户提供的真实论文信息和论文摘要进行写作。

必须严格遵守：
1. 不得编造任何论文、作者、年份、DOI。
2. 不得编造摘要中没有提供的实验数值或结论。
3. 所有文献引用必须使用提供的 Paper ID，例如 [P1]。
4. 多篇论文可以写成 [P1, P3]。
5. 禁止使用不存在的 Paper ID。
6. 不要自己生成 References 部分。
7. 如果证据不足，应采用谨慎表述，而不是补造事实。
8. 写作要形成连贯论述，不要简单逐篇罗列摘要。
""".strip()


class PaperResearchAssistant:
    """论文智能助手核心类 -协调检索、写作、引用校验和文件输出"""

    def __init__(self, output_dir: str = "outputs") -> None:

        # 加载 .env 中的环境变量
        load_dotenv()

        # 保存输出目录路径
        self.output_dir = Path(output_dir)

        # 输出目录不存在时自动创建
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 读取可选 OpenAlex API Key
        openalex_api_key = os.getenv("OPENALEX_API_KEY", "")

        # 读取可选联系邮箱
        contact_email = os.getenv("CONTACT_EMAIL", "")

        # 创建 OpenAlex 搜索器
        self.searcher = OpenAlexSearcher(
            api_key=openalex_api_key,
            contact_email=contact_email,
        )

        # HelloAgents 会根据 .env 中的 LLM_* 配置连接模型
        self.llm = HelloAgentsLLM()

        # 创建 QueryAgent
        self.query_agent = SimpleAgent(
            name="QueryAgent",
            llm=self.llm,
            system_prompt=QUERY_AGENT_PROMPT,
        )

        # 创建 WriterAgent
        self.writer_agent = SimpleAgent(
            name="WriterAgent",
            llm=self.llm,
            system_prompt=WRITER_AGENT_PROMPT,
        )

    def optimize_search_query(self, topic: str) -> str:
        """将用户研究主题转换为简洁英文检索词"""

        # 构造 QueryAgent 输入
        prompt = (
            "请将下面研究主题转换成适合学术论文数据库搜索的英文关键词：\n\n"
            f"{topic}"
        )

        # 调用 QueryAgent
        result = self.query_agent.run(prompt)

        # Agent 没返回内容时直接使用原主题
        if result is None:
            return topic

        # 转成普通字符串并清理空白
        result = str(result).strip()

        # 空结果同样回退原主题
        if not result:
            return topic

        # 正常提示词要求一行，因此只取第一行
        first_line = result.splitlines()[0].strip()

        # 去掉模型偶尔添加的引号或代码符号
        first_line = first_line.strip('`"\' ')

        # 去掉偶尔出现的 Query: 等前缀
        first_line = re.sub(
            r"^(search\s*query|query|检索词)\s*[:：]\s*",
            "",
            first_line,
            flags=re.IGNORECASE,
        )

        # 异常长的输出不适合作为搜索词，回退原主题
        if len(first_line) > 300:
            return topic

        return first_line if first_line else topic

    @staticmethod
    def _build_source_context(papers: list[Paper]) -> str:
        """将多篇论文整理成 WriterAgent 可读的证据上下文"""

        # 每篇论文先转成统一 Evidence Block
        blocks = [paper.to_prompt_block() for paper in papers]

        # 用明显分隔线隔开不同论文，降低模型串淆概率
        separator = "\n\n" + "=" * 70 + "\n\n"

        # 返回完整证据文本
        return separator.join(blocks)

    def _build_writing_prompt(
        self,
        topic: str,
        content_type: str,
        language: str,
        papers: list[Paper],
    ) -> str:
        """构造 WriterAgent 的完整写作任务"""

        # 把真实论文整理成证据上下文
        source_context = self._build_source_context(papers)

        # 为中英文分别给一个适中的默认长度
        length_requirement = (
            "about 700-1000 words"
            if language == "英文"
            else "约 800-1200 个中文字"
        )

        # 返回完整 Prompt
        return f"""
研究主题：
{topic}

需要生成的内容类型：
{content_type}

输出语言：
{language}

建议长度：
{length_requirement}

写作要求：
1. 只能使用下面提供的论文作为文献证据。
2. 不得引用未提供的论文。
3. 每个重要学术观点尽量提供引用。
4. 引用格式必须使用 Paper ID，例如 [P1]。
5. 多篇论文可以写成 [P1, P3]。
6. 不要生成参考文献列表。
7. 不要编造摘要中没有出现的具体实验结果。
8. 内容应具有论文写作风格，而不是简单逐篇罗列摘要。
9. 可以综合比较不同工作的研究思路、共同点和差异。
10. 如果证据不足，应采用谨慎表述。

下面是本次检索得到的真实论文信息：

{source_context}

现在请生成 {content_type}。
""".strip()

    def _repair_citations(
        self,
        topic: str,
        draft: str,
        papers: list[Paper],
    ) -> str:
        """引用缺失或出现非法 ID 时，让 WriterAgent 自动修正一次"""

        # 获取所有合法 Paper ID
        valid_ids = ", ".join(paper.paper_id for paper in papers)

        # 再次附上真实论文证据，避免修复时脱离上下文
        source_context = self._build_source_context(papers)

        # 构造修复提示词。
        prompt = f"""
你刚才生成的内容存在引用格式问题，请完整修正。

研究主题：
{topic}

唯一允许使用的 Paper ID：
{valid_ids}

要求：
1. 只允许引用上面列出的 Paper ID。
2. 每个重要学术观点尽量提供真实文献支持。
3. 引用格式使用 [P1] 或 [P1, P2]。
4. 禁止编造新的 Paper ID。
5. 不生成 References。
6. 只能依据下面重新提供的论文证据。

真实论文证据：
{source_context}

需要修正的原始内容：
{draft}

请直接输出修正后的完整正文。
""".strip()

        # 调用 WriterAgent 修复
        result = self.writer_agent.run(prompt)

        # 修复调用失败时保留原稿，由后续硬校验决定是否拒绝输出
        if result is None:
            return draft

        # 返回修复后的正文
        return str(result).strip()

    def generate_content(
        self,
        topic: str,
        content_type: str,
        language: str,
        papers: list[Paper],
    ) -> str:
        """基于真实论文生成正文，并执行引用 ID 硬校验"""

        # 构造写作 Prompt
        prompt = self._build_writing_prompt(
            topic=topic,
            content_type=content_type,
            language=language,
            papers=papers,
        )

        # 调用 WriterAgent
        result = self.writer_agent.run(prompt)

        # 模型调用失败时终止流程
        if result is None:
            raise RuntimeError("WriterAgent 没有返回内容。")

        # 清理生成正文
        draft = str(result).strip()

        # 空内容没有意义
        if not draft:
            raise RuntimeError("WriterAgent 返回了空内容。")

        # 提取正文使用到的所有 Paper ID
        used_ids = collect_citation_ids(draft)

        # 找出不属于真实检索结果的 Paper ID
        invalid_ids = find_invalid_citations(draft, papers)

        # 没引用或出现非法引用时，自动尝试修复一次
        if not used_ids or invalid_ids:
            print("\n[引用检查] 检测到引用问题，正在自动修正一次...")
            draft = self._repair_citations(topic, draft, papers)

        # 修复完成后再次收集引用
        used_ids = collect_citation_ids(draft)

        # 修复完成后再次检查非法引用
        invalid_ids = find_invalid_citations(draft, papers)

        # 仍存在虚构 ID 时直接拒绝生成最终报告
        if invalid_ids:
            invalid_text = ", ".join(sorted(invalid_ids))
            raise RuntimeError(f"检测到不存在的论文引用：{invalid_text}")

        # 完全没有引用同样不满足论文助手要求
        if not used_ids:
            raise RuntimeError("生成内容中没有任何文献引用。")

        # 返回通过 ID 校验的正文
        return draft

    @staticmethod
    def _print_papers(papers: list[Paper]) -> None:
        """在终端展示本次检索到的论文"""

        # 打印分隔线
        print("\n" + "=" * 70)

        # 展示论文数量
        print(f"检索到 {len(papers)} 篇含摘要的论文")

        # 打印分隔线
        print("=" * 70)

        # 逐篇展示关键信息
        for paper in papers:
            # 年份缺失时显示 Unknown
            year = paper.year if paper.year is not None else "Unknown"

            # 第一行展示编号和标题。
            print(f"[{paper.paper_id}] {paper.title}")

            # 第二行展示年份和被引次数。
            print(f"    Year: {year} | Citations: {paper.cited_by_count}")

    @staticmethod
    def _build_report(
        topic: str,
        search_query: str,
        content_type: str,
        generated_content: str,
        cited_papers: list[Paper],
    ) -> str:
        """生成最终 Markdown 报告"""

        # 只根据真正引用到的论文建立连续数字编号
        final_content = replace_paper_ids_with_numbers(
            generated_content,
            cited_papers,
        )

        # 参考文献同样只包含正文真正引用到的论文
        references = build_reference_list(cited_papers)

        # 拼成完整 Markdown
        return f"""# PaperResearchAgent 生成报告

## 研究主题

{topic}

## 实际检索关键词

`{search_query}`

## 生成内容类型

{content_type}

---

## 生成内容

{final_content}

---

## 参考文献

{references}
"""

    def _save_outputs(
        self,
        topic: str,
        search_query: str,
        report: str,
        all_papers: list[Paper],
        cited_papers: list[Paper],
    ) -> None:
        """保存 Markdown、完整搜索结果 JSON 和实际引用 BibTeX"""

        # 1）保存最终 Markdown 报告
        report_path = self.output_dir / "report.md"
        report_path.write_text(report, encoding="utf-8")

        # 2）保存本次全部检索论文，方便复查和后续扩展
        paper_data = {
            "topic": topic,
            "search_query": search_query,
            "retrieved_count": len(all_papers),
            "cited_count": len(cited_papers),
            "cited_paper_ids": [paper.paper_id for paper in cited_papers],
            "papers": [paper.to_dict() for paper in all_papers],
        }

        papers_path = self.output_dir / "papers.json"
        papers_path.write_text(
            json.dumps(paper_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 3）BibTeX 只保存正文真正引用过的论文
        bibtex_path = self.output_dir / "references.bib"
        bibtex_path.write_text(
            build_bibtex(cited_papers),
            encoding="utf-8",
        )

        print("\n输出文件已保存：")
        print(f"  - {report_path}")
        print(f"  - {papers_path}")
        print(f"  - {bibtex_path}")

    def research(
        self,
        topic: str,
        content_type: str = "文献综述",
        max_papers: int = 8,
        start_year: int | None = None,
        end_year: int | None = None,
        language: str = "中文",
    ) -> str:
        """执行主题 → 检索 → 写作 → 校验 → 输出”的完整流程 """

        # 清理研究主题
        topic = topic.strip()

        # 空主题无法检索
        if not topic:
            raise ValueError("研究主题不能为空。")

        # Step 1：生成更适合学术数据库的检索词
        print("\n[Step 1/4] 正在生成论文检索关键词...")
        search_query = self.optimize_search_query(topic)
        print(f"检索关键词：{search_query}")

        # Step 2：从 OpenAlex 搜索真实论文
        print("\n[Step 2/4] 正在从 OpenAlex 搜索真实论文...")
        papers = self.searcher.search(
            query=search_query,
            max_results=max_papers,
            start_year=start_year,
            end_year=end_year,
        )

        # 没搜到可用论文时无法继续生成
        if not papers:
            raise RuntimeError(
                "没有检索到包含摘要的相关论文，请更换主题或扩大年份范围。"
            )

        # 在终端展示检索结果
        self._print_papers(papers)

        # Step 3：基于真实摘要生成正文
        print("\n[Step 3/4] 正在基于真实论文摘要生成内容...")
        generated_content = self.generate_content(
            topic=topic,
            content_type=content_type,
            language=language,
            papers=papers,
        )

        # 找到正文实际使用的论文
        cited_papers = get_cited_papers(generated_content, papers)

        if not cited_papers:
            raise RuntimeError("正文没有引用任何检索到的论文。")

        # Step 4：统一编号并保存最终文件
        print("\n[Step 4/4] 正在生成参考文献并保存结果...")
        report = self._build_report(
            topic=topic,
            search_query=search_query,
            content_type=content_type,
            generated_content=generated_content,
            cited_papers=cited_papers,
        )

        # 保存报告、搜索结果和 BibTeX
        self._save_outputs(
            topic=topic,
            search_query=search_query,
            report=report,
            all_papers=papers,
            cited_papers=cited_papers,
        )

        # 返回完整报告，main.py 可以继续打印
        return report
