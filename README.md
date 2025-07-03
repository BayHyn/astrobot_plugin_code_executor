# AstrBot代码执行器插件 (Super Code Executor) - 全能小狐狸汐林

![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)![Python Version](https://img.shields.io/badge/python-3.10%2B-orange.svg)![Plugin Version](https://img.shields.io/badge/version-1.6.1--final-brightgreen)![Framework](https://img.shields.io/badge/framework-AstrBot-D72C4D)

**一个为 AstrBot 框架打造的，拥有完全本地系统访问权限的Python 代码执行函数插件。**

限制了仅管理员用户才能使用此函数，该插件移除了所有传统代码执行工具的沙盒限制，赋予语言模型（LLM）直接、完整地操作本地文件系统和执行任意代码的能力。它的设计理念是“权力越大，能力越强”，旨在将您的 AI 助手从一个咨询者，转变为一个能够直接在您电脑上完成任务的执行者。

---

## ✨ 特色功能

*   **无限制代码执行**: 执行任意 Python 代码，没有任何函数或模块的黑名单。
*   **完全文件系统访问**: 使用 `os`, `shutil` 等库，在所有盘符（如 `C:\`, `D:\`）上自由地创建、读取、修改、删除文件和目录。
*   **智能文件发送**:
    *   **自动检测**: 自动发现并发送在默认工作目录 (`SAVE_DIR`) 中新创建的所有文件。
    *   **指定发送**: 通过将任意文件的完整路径添加到 `FILES_TO_SEND` 列表，可以发送您电脑上任何位置的已有文件。
*   **丰富的预装库**: 内置了 `pandas`, `numpy`, `matplotlib`, `requests`, `openpyxl` 等大量常用库，开箱即用，满足数据分析、网络请求、文件处理等各种需求。
*   **自动化图表生成**: `matplotlib` 绘图后无需手动保存，插件会自动将图表保存为图片文件并发送。

---

## 🚀 安装

1.  下载 `code_executor_plugin.py` 文件（或者您重命名后的插件文件）。
2.  将该文件放入您的 AstrBot 的插件目录中，通常是 `<AstrBot根目录>/data//plugins/`。
3.  重启您的 AstrBot 程序。

---

## ⚙️ 配置


插件的关键行为通过其 `config.json` 文件进行配置。您可以在首次运行后在插件的数据目录中找到它。

**`config.json` 示例:**

```json
{
    "timeout_seconds": {
      "description": "代码执行超时时间（秒）",
      "type": "int",
      "default": 10,
      "hint": "设置代码执行的最大等待时间，防止死循环"
    },
    "max_output_length": {
      "description": "输出结果最大长度",
      "type": "int",
      "default": 2000,
      "hint": "限制返回结果的字符数，避免输出过长"
    },
    "enable_plots": {
      "description": "是否启用图表生成",
      "type": "bool",
      "default": true,
      "hint": "启用后可以生成matplotlib图表并返回图片"
    },
    "output_directory": {
      "description": "代码生成的默认工作目录",
      "type": "string",
      "default": "",
      "hint": "留空则使用插件内置的默认路径(会报错）。推荐填写一个绝对路径，例如 'D:/my_ai_outputs' 或 '/home/user/ai_outputs'。AI将在此目录中创建和读取文件。"
    }
  }
  
```

插件的部分行为可以通过修改其源代码进行配置。请打开插件的 `.py` 文件进行修改。

关键配置项位于 `__init__` 方法中：

```python
# 插件超时时间（秒）
self.timeout_seconds = self.config.get("timeout_seconds", 90)

# 返回给LLM的最大文本长度
self.max_output_length = self.config.get("max_output_length", 3000)

# 默认的工作目录，用于存放生成的文件
# ‼️【重要】请务必将此路径修改为您自己电脑上的有效路径！
base_path = "D:/Agent-xilin/AstrBot/data/plugins/astrobot_plugin_code_executor"
self.file_output_dir = os.path.join(base_path, 'outputs')
‼️ 注意： base_path 是硬编码的，您必须根据自己的环境修改此路径，否则插件将无法正常工作。

📖 使用方法
当您向语言模型下达指令时，它会自动调用此工具。以下是AI使用此工具的核心逻辑：

1. 生成新文件 (默认方式)
当任务需要创建新文件时（如生成报告、数据表、图表），AI 会将文件保存在 SAVE_DIR 目录中。插件会自动检测到这些新文件并发送给您。

AI 执行的代码示例:

PYTHON
import pandas as pd
import os

# 创建一个数据表
data = {'产品': ['A', 'B', 'C'], '销量': [100, 150, 80]}
df = pd.DataFrame(data)

# 使用 os.path.join 将其保存在默认工作目录
save_path = os.path.join(SAVE_DIR, 'sales_report.xlsx')
df.to_excel(save_path, index=False)

print(f"销售报告已生成: {save_path}")
插件会自动将 sales_report.xlsx 发送给用户。

2. 发送本地已有文件 (高级方式)
当您需要AI发送一个电脑上已经存在的文件时，可以让AI将该文件的完整路径添加到 FILES_TO_SEND 列表中。

您的指令示例:

“帮我把 D盘 marketing 文件夹里的 quarterly_review.pptx 发给我”

AI 执行的代码示例:

PYTHON
import os

# AI 根据指令定位文件
file_path = "D:/marketing/quarterly_review.pptx"

# 检查文件是否存在，并添加到待发送列表
if os.path.exists(file_path):
    FILES_TO_SEND.append(file_path)
    print(f"已准备发送文件: {file_path}")
else:
    print(f"错误: 文件未找到 at {file_path}")
插件会将 D:/marketing/quarterly_review.pptx 发送给用户。
```

‼️ 安全警告 ‼️
此插件权限较大，带来了巨大的安全风险。

它没有沙盒。语言模型执行的代码将拥有与运行 AstrBot 程序的用户完全相同的权限。
一个错误的或恶意的指令可能会导致语言模型执行破坏性操作（例如，os.remove("C:/boot.ini") 或 shutil.rmtree("C:/Users/YourUser/Documents")）。
请仅在完全私有、可信的环境中运行此插件。 不要将搭载此插件的机器人暴露在公共网络或不受信任的用户面前。
您对使用此插件造成的所有后果负全部责任。
