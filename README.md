# PaperResearchAgent

---

## 1. 项目介绍

```text
用户研究主题
    ↓
QueryAgent 生成检索词
    ↓
OpenAlex 搜索真实论文
    ↓
提取题名 / 作者 / 年份 / DOI / 摘要
    ↓
WriterAgent 基于真实摘要生成内容
    ↓
Python 校验引用 ID
    ↓
生成 report.md + papers.json + references.bib
```

---

## 2. 项目功能

- 根据中文或英文研究主题生成学术检索词

- 调用 OpenAlex 自动搜索真实论文

- 基于真实论文摘要生成文献综述

- 支持 Related Work / Introduction / 研究背景

- 检测 LLM 使用的不存在论文 ID

- 生成 Markdown 报告

- 生成 BibTeX

Thank you! Thank you for your read! Starts! Give your Starts!
