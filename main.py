"""
PaperResearchAgent 命令行入口
接收用户输入 → 校验参数 → 创建 PaperResearchAssistant → 调用 research() → 输出结果
"""

# 导入论文智能助手主类
from src.paper_assistant import PaperResearchAssistant


# 用户可以选择的生成内容类型
CONTENT_TYPES = {
    "1": "文献综述",
    "2": "Related Work",
    "3": "Introduction",
    "4": "研究背景",
}


def read_integer(
    prompt: str,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    """读取预期范围内的合法整数；直接回车则使用默认值"""

    # 输入不合法时循环询问。
    while True:
        # 读取并清理输入。
        value = input(prompt).strip()  # strip() 去掉首尾空格和换行

        # 用户直接回车则使用默认值
        if not value:
            return default

        try:
            # 尝试转换为整数。
            number = int(value)
        except ValueError:
            # 非整数时提示重新输入
            print("请输入整数。")
            continue

        # 检查整数范围。
        if not min_value <= number <= max_value:
            print(f"请输入 {min_value}-{max_value} 之间的整数。")
            continue

        # 返回合法整数。
        return number


def read_optional_year(prompt: str) -> int | None:
    """读取可选年份, 直接回车表示不限制"""

    # 输入不合法时循环询问。
    while True:
        # 读取年份文本。
        value = input(prompt).strip()

        # 空输入表示不设置年份限制
        if not value:
            return None

        try:
            # 尝试转成整数
            year = int(value)
        except ValueError:
            # 非整数年份重新输入
            print("年份必须是整数。")
            continue

        # 检查年份是否合理
        if not 1000 <= year <= 3000:
            print("请输入合理的年份。")
            continue

        # 返回合法年份
        return year


def choose_content_type() -> str:
    """让用户选择需要生成的论文内容类型"""

    # 打印选项标题
    print("\n选择需要生成的内容：")

    # 展示所有内容类型
    for key, value in CONTENT_TYPES.items():
        print(f"{key}. {value}")

    # 获取用户选择
    choice = input("选择 [默认 1]：").strip()

    # 空输入默认选择 1
    if not choice:
        choice = "1"

    # 不合法选项也安全回退到文献综述
    return CONTENT_TYPES.get(choice, "文献综述")


def choose_language() -> str:
    """选择最终生成语言"""

    # 展示语言选项。
    print("\n选择输出语言：")
    print("1. 中文")
    print("2. 英文")

    # 读取选择。
    choice = input("请选择 [默认 1]：").strip()

    # 只有输入 2 才选择英文，其余默认中文
    return "英文" if choice == "2" else "中文"


def main() -> None:
    """运行论文助手"""

    # 打印项目标题
    print("=" * 70)
    print("PaperResearchAgent")
    print("=" * 70)

    # 获取用户研究主题
    topic = input("\n输入研究主题：\n> ").strip()

    # 主题为空时直接结束
    if not topic:
        print("研究主题不能为空!")
        return

    # 选择内容类型
    content_type = choose_content_type()

    # 选择输出语言
    language = choose_language()

    # 获取需要检索的论文数量
    max_papers = read_integer(
        "\n检索多少篇论文 [默认 8，范围 1-20]：",
        default=8,
        min_value=1,
        max_value=20,
    )

    # 获取可选最早年份
    start_year = read_optional_year(
        "\n最早发表年份 [直接回车表示不限]："
    )

    # 获取可选最晚年份
    end_year = read_optional_year(
        "最晚发表年份 [直接回车表示不限]："
    )

    # 检查起止年份关系
    if (
        start_year is not None
        and end_year is not None
        and start_year > end_year
    ):
        print("错误：最早年份不能大于最晚年份!")
        return

    try:
        # 创建论文智能助手
        assistant = PaperResearchAssistant()

        # 调用.research()方法, 执行完整研究流程
        report = assistant.research(
            topic=topic,
            content_type=content_type,
            max_papers=max_papers,
            start_year=start_year,
            end_year=end_year,
            language=language,
        )

    except KeyboardInterrupt:
        # 用户按 Ctrl+C 时友好结束
        print("\n\n 666! 程序已取消! ")
        return

    except Exception as exc:
        # 捕获项目其他运行异常
        print("\n程序运行失败：")
        print(exc)
        return

    # 在终端展示最终报告
    print("\n\n" + "=" * 70)
    print("生成结果如下")
    print("=" * 70 + "\n")
    print(report)


if __name__ == "__main__":
    main()
