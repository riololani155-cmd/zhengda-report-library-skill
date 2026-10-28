# zhengda-report-library-skill

一个通用的 AI Agent Skill：检索并精读本地「正大杯国奖报告库」（2020-2025 年全国大学生市场调查与分析大赛获奖报告 PDF，共 153 篇）。

支持任意遵循 Agent Skills 规范（`SKILL.md`）的 AI 工具，例如 Claude Code、Kimi Work、Cursor 等。

## 功能

- **文件名检索**：按关键词快速筛选报告。
- **PDF 全文检索**：对全部报告建立 SQLite 索引，返回命中文件、页码与上下文片段；索引自动增量更新。
- **按年份 / 奖项筛选**：`-y 2023`、`-a 国一`。
- **库统计**：`--stats` 查看各年份、各奖项的报告数量。

## 安装

### Claude Code

```bash
# 项目级（仅当前项目可用）
cp -r zhengda-report-library-skill .claude/skills/zhengda-report-library
# 或用户级（所有项目可用）
cp -r zhengda-report-library-skill ~/.claude/skills/zhengda-report-library
```

### Kimi Work

在插件目录按个人插件规范放置（`kimi.plugin.json` + `skills/zhengda-report-library/`），或直接在 Kimi Work 插件市场安装后使用。

### 其他 / 手动使用

不安装也能直接用——任何 AI 只要读到 `SKILL.md` 就知道怎么调用脚本；也可以纯命令行使用：

```bash
pip install pypdf
python scripts/search_reports.py 养老
python scripts/search_reports.py -f IPA -y 2023
python scripts/search_reports.py --stats
```

## 配置报告库路径

报告库（PDF 文件）**不在本仓库内**，需要你自己准备。三种方式告诉脚本库在哪：

1. 命令行参数：`python scripts/search_reports.py 养老 -l "D:\路径\国奖报告库_2020-2025"`
2. 环境变量：`set ZHENGDA_LIB=D:\路径\国奖报告库_2020-2025`（Windows）/ `export ZHENGDA_LIB=...`（macOS/Linux）
3. 直接编辑 `scripts/search_reports.py` 里的 `DEFAULT_LIB` 常量

库目录结构：根目录下按年份分文件夹存放 PDF，文件名形如 `【23国三】报告标题.pdf`。

## 目录结构

```
zhengda-report-library-skill/
├── SKILL.md                  # Agent Skill 定义（AI 读取的入口）
├── README.md                 # 本文件
├── scripts/
│   └── search_reports.py     # 检索脚本（Python 3.8+，依赖 pypdf）
└── .gitignore
```

## 说明

- 报告 PDF 为大赛获奖作品，受版权保护，本仓库只分发检索工具，不分发 PDF。
- 部分早年报告是扫描件（无文字层），全文检索无法命中属正常现象。
- 首次全文检索需 1-2 分钟建索引，之后秒回。
