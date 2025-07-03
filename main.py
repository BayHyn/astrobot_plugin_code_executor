import asyncio
import sys
import io
import threading
import queue
import time
import traceback
import os
from datetime import datetime
from typing import Dict, Any, List

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api import AstrBotConfig
import astrbot.api.message_components as Comp

@register("code_executor", "Assistant", "超级代码执行器 - 全能小狐狸汐林", "1.7.0-config", "local")
class CodeExecutorPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config or {}

        # 优先从配置文件读取配置，否则使用默认值
        self.timeout_seconds = self.config.get("timeout_seconds", 90)
        self.max_output_length = self.config.get("max_output_length", 3000)

        # **[新功能]** 从配置文件读取输出目录
        configured_path = self.config.get("output_directory")

        if configured_path and configured_path.strip():
            self.file_output_dir = configured_path
            logger.info(f"已从配置文件加载输出目录: {self.file_output_dir}")
        else:
            # 如果配置为空，则使用默认的后备路径
            default_base_path = "D:/Agent-xilin/AstrBot/data/plugins/astrobot_plugin_code_executor"
            self.file_output_dir = os.path.join(default_base_path, 'outputs')
            logger.info(f"配置中 output_directory 为空, 使用默认输出目录: {self.file_output_dir}")

        # 确保最终确定的目录存在
        if not os.path.exists(self.file_output_dir):
            logger.info(f"路径 {self.file_output_dir} 不存在，正在创建...")
            try:
                os.makedirs(self.file_output_dir)
            except Exception as e:
                logger.error(f"创建文件夹 {self.file_output_dir} 失败！错误: {e}")

        logger.info("代码执行器插件已加载！")

    @filter.llm_tool(name="execute_python_code")
    async def execute_python_code(self, event: AstrMessageEvent, code: str, description: str = "") -> str:
        '''
        **【代码执行器】**
        **优先使用此函数**，它远超 `fetch_url` 的单一网页内容获取功能，这个支持计算、文件操作、可视化和复杂网络请求。仅当任务明确只需要获取网页原始内容时才考虑 `fetch_url`.

        ---
        **【调用场景】**
        **必须**在以下场景调用此函数，执行代码获取精确结果，禁止文字猜测：
        1. **计算/数据处理**：如“计算 (1+5)*3/2”或“分析数据最大值”。
        2. **文件操作**：生成/读取 Excel、PDF、CSV 、图片类型等，如“生成 Excel 表格”。
        3. **网络请求**：请求各种api或者其他网络操作。
        4. **数据可视化**：如“绘制销售趋势图”或“生成饼图”。
        5. **图像处理**：如“下载猫的图片并调整大小”。
        6. **复杂逻辑**：如“规划最短路径”或“模拟抽奖”。
        7. **文件操作**: 允许AI生成符合格式的代码操作本机文件发送给用户，包括但不限于删除，查找，修改等。
        **优先级**：涉及计算、文件、可视化或动态数据时，**必须**优先调用此函数，而非 `fetch_url`。

        ---
        **【文件处理指南】**
        1.  **生成新文件 (默认)**:
            - 所有新生成的文件（图表、表格等）应保存到 `SAVE_DIR` 目录中。
            - 使用 `os.path.join(SAVE_DIR, 'filename')` 来构造路径。
            - **保存到 `SAVE_DIR` 的新文件将被自动检测并发送。**
            - 示例: `plt.savefig(os.path.join(SAVE_DIR, 'sales_chart.png'))`
        2.  **发送本地已有文件 (高级)**:
            - 如果需要读取并发送一个**已经存在**的本地文件（例如 `D:\reports\report.docx`），请将其**完整路径**添加到 `FILES_TO_SEND` 列表中。
            - 示例:
              ```python
              # 发送 D 盘下的一个报告文件
              file_path = "D:/reports/report.docx"
              if os.path.exists(file_path):
                  FILES_TO_SEND.append(file_path)
                  print(f"已准备发送文件: {file_path}")
              else:
                  print(f"错误: 文件 {file_path} 未找到")
              ```
        - AI 拥有完全的文件系统权限，可以读取/写入任何可访问的目录。

        ---
        **【可用库】**
        - 网络：`requests`, `aiohttp`, `BeautifulSoup`
        - 数据：`pandas` (as pd), `numpy` (as np)
        - 文件：`openpyxl`, `python-docx`, `fpdf2`, `json`, `yaml`
        - 图表：`matplotlib.pyplot` (as plt), `seaborn` (as sns), `plotly`
        - 图像：`PIL.Image`, `PIL`
        - 其他：`datetime`, `re`, `sympy`, `os`, `io`, `shutil`, `zipfile`

        ---
        **【编码要求】**
        - 文件操作需检查路径和异常。
        - 支持操作各个盘符。
        - 网络请求需设置超时和重试。
        - 代码必须独立运行，无外部依赖。

        Args:
            code(string): 可独立运行的 Python 代码。
            description(string): (可选) 代码功能描述。
        '''
        logger.info(f"收到任务: {description or '无描述'}")
        logger.debug(f"代码内容:\n{code}")

        try:
            result = await self._execute_code_safely(code)

            if result["success"]:
                response_parts = ["✅ 任务完成！"]
                if result["output"] and result["output"].strip():
                    output = result["output"].strip()
                    if len(output) > self.max_output_length:
                        output = output[:self.max_output_length] + "\n...(内容已截断)"
                    response_parts.append(f"📤 执行结果：\n```\n{output}\n```")

                text_response = "\n".join(response_parts)
                await event.send(MessageChain().message(text_response))
                
                # 发送文件
                if result["file_paths"]:
                    logger.info(f"发现 {len(result['file_paths'])} 个待发送文件，正在处理...")
                    for file_path in result["file_paths"]:
                        if not os.path.exists(file_path) or not os.path.isfile(file_path):
                            logger.warning(f"文件不存在或是个目录，跳过发送: {file_path}")
                            await event.send(MessageChain().message(f"🤔 警告: AI请求发送的文件不存在: {os.path.basename(file_path)}"))
                            continue
                        try:
                            file_name = os.path.basename(file_path)
                            is_image = any(file_name.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp'])
                            if is_image:
                                logger.info(f"正在以图片形式发送: {file_path}")
                                await event.send(MessageChain().file_image(file_path))
                            else:
                                logger.info(f"正在以文件形式发送: {file_path}")
                                await event.send(MessageChain().message(f"📄 正在发送文件: {file_name}"))
                                chain = [Comp.File(file=file_path, name=file_name)]
                                await event.send(event.chain_result(chain))
                        except Exception as e:
                            logger.error(f"发送文件/图片 {file_path} 失败: {e}", exc_info=True)
                            await event.send(MessageChain().message(f"❌ 发送文件 {os.path.basename(file_path)} 失败"))

                if not (result["output"] and result["output"].strip()) and not result["file_paths"]:
                     return "代码执行完成，但无文件、图片或文本输出。"
                return "任务完成！"

            else:
                error_msg = f"❌ 代码执行失败！\n错误信息：\n```\n{result['error']}\n```"
                if result.get("output"):
                    error_msg += f"\n\n出错前输出：\n```\n{result['output']}\n```"
                error_msg += "\n请分析错误信息，修正代码或调整逻辑后重试。"
                await event.send(MessageChain().message(error_msg))
                return "代码执行失败，请根据错误信息修正代码后重试。"

        except Exception as e:
            logger.error(f"插件内部错误: {str(e)}", exc_info=True)
            error_msg = f"🔥 插件内部错误：{str(e)}\n请检查插件配置或环境后重试。"
            await event.send(MessageChain().message(error_msg))
            return "插件内部错误，请检查配置或环境。"

    async def _execute_code_safely(self, code: str) -> Dict[str, Any]:

        def run_code(code_to_run: str, file_output_dir: str):
            old_stdout, old_stderr = sys.stdout, sys.stderr
            output_buffer, error_buffer = io.StringIO(), io.StringIO()
            
            files_to_send_explicitly = []
            files_before = set(os.listdir(file_output_dir)) if os.path.exists(file_output_dir) else set()

            try:
                sys.stdout, sys.stderr = output_buffer, error_buffer

                exec_globals = {
                    '__builtins__': __builtins__,
                    'print': print,
                    'SAVE_DIR': file_output_dir,
                    'FILES_TO_SEND': files_to_send_explicitly,
                    'io': io
                }

                try:
                    import matplotlib
                    matplotlib.use('Agg')
                    import matplotlib.pyplot as plt
                    plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial']
                    plt.rcParams['axes.unicode_minus'] = False
                    original_show, original_savefig = plt.show, plt.savefig

                    def save_and_close_current_fig(base_name: str):
                        fig = plt.gcf()
                        if not fig.get_axes(): plt.close(fig); return
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        filename = f"{base_name}_{timestamp}_{len(os.listdir(file_output_dir))}.png"
                        filepath = os.path.join(file_output_dir, filename)
                        try:
                            original_savefig(filepath, dpi=150, bbox_inches='tight')
                            print(f"[图表已保存: {filepath}]")
                        except Exception as e: print(f"[保存图表失败: {e}]")
                        finally: plt.close(fig)

                    plt.show = lambda *args, **kwargs: save_and_close_current_fig("plot")
                    plt.savefig = lambda fname, *args, **kwargs: save_and_close_current_fig(
                        os.path.splitext(os.path.basename(fname))[0] if isinstance(fname, str) else "plot"
                    )
                    exec_globals.update({'matplotlib': matplotlib, 'plt': plt})
                except ImportError: logger.warning("matplotlib 不可用，图表功能禁用")

                libs_to_inject = {
                    'numpy': 'np', 'pandas': 'pd', 'seaborn': 'sns', 'requests': 'requests',
                    'sympy': 'sympy', 'json': 'json', 'yaml': 'yaml', 'datetime': 'datetime',
                    're': 're', 'os': 'os', 'openpyxl': 'openpyxl', 'docx': 'docx',
                    'fpdf': 'fpdf', 'PIL': 'PIL', 'shutil': 'shutil', 'zipfile': 'zipfile',
                    'aiohttp': 'aiohttp', 'plotly': 'plotly'
                }
                for lib_name, alias in libs_to_inject.items():
                    try:
                        lib = __import__(lib_name)
                        exec_globals[alias or lib_name] = lib
                    except ImportError: logger.warning(f"库 {lib_name} 不可用，相关功能禁用")
                try: from bs4 import BeautifulSoup; exec_globals['BeautifulSoup'] = BeautifulSoup
                except ImportError: pass
                try: from PIL import Image; exec_globals['Image'] = Image
                except ImportError: pass

                exec(code_to_run, exec_globals)
                
                if 'plt' in exec_globals and plt.get_fignums():
                    for fig_num in list(plt.get_fignums()):
                        plt.figure(fig_num)
                        save_and_close_current_fig("plot_auto")
                
                if 'plt' in exec_globals: plt.show, plt.savefig = original_show, original_savefig

                files_after = set(os.listdir(file_output_dir)) if os.path.exists(file_output_dir) else set()
                newly_generated_filenames = files_after - files_before
                newly_generated_files = [os.path.join(file_output_dir, f) for f in newly_generated_filenames]
                
                all_files_to_send = list(set(newly_generated_files + files_to_send_explicitly))

                return {
                    "success": True, "output": output_buffer.getvalue(), "error": None,
                    "file_paths": all_files_to_send
                }
            except Exception:
                tb_str = traceback.format_exc()
                logger.error(f"代码执行出错:\n{tb_str}")
                return {"success": False, "error": tb_str, "output": output_buffer.getvalue(), "file_paths": []}
            finally:
                sys.stdout, sys.stderr = old_stdout, old_stderr
                try:
                    if 'plt' in locals() and 'matplotlib' in sys.modules: plt.close('all')
                except: pass

        result_queue = queue.Queue()
        thread = threading.Thread(
            target=lambda q, c, f: q.put(run_code(c, f)),
            args=(result_queue, code, self.file_output_dir)
        )
        thread.daemon = True
        thread.start()

        try:
            return result_queue.get(timeout=self.timeout_seconds)
        except queue.Empty:
            return {"success": False, "error": f"代码执行超时（超过 {self.timeout_seconds} 秒）", "output": None, "file_paths": []}

    async def terminate(self):
        logger.info("代码执行器插件已卸载")

