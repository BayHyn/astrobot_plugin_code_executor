import asyncio
import sys
import io
import time
import traceback
import os
from datetime import datetime
from typing import Dict, Any, List

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api import logger
from astrbot.api import AstrBotConfig
import astrbot.api.message_components as Comp
from astrbot.api.provider import ProviderRequest
from astrbot.core.message.components import Plain

from .database import ExecutionHistoryDB
from .webui import CodeExecutorWebUI


@register("code_executor", "Xican", "代码执行器 - 全能小狐狸汐林", "2.1.0--webui")
class CodeExecutorPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config or {}
        self.tools = StarTools()  # 获取框架工具

        # 优先从配置文件读取配置，否则使用默认值
        self.timeout_seconds = self.config.get("timeout_seconds", 90)
        self.max_output_length = self.config.get("max_output_length", 3000)
        self.webui_port = self.config.get("webui_port", 22334)

        # **[新功能]** 从配置文件读取输出目录
        configured_path = self.config.get("output_directory")

        if configured_path and configured_path.strip():
            self.file_output_dir = configured_path
            logger.info(f"已从配置文件加载输出目录: {self.file_output_dir}")
        else:
            # 使用框架提供的标准方式获取数据目录
            plugin_data_dir = self.tools.get_data_dir()
            self.file_output_dir = os.path.join(plugin_data_dir, 'outputs')
            logger.info(f"配置中 output_directory 为空, 使用默认输出目录: {self.file_output_dir}")

        # 确保最终确定的目录存在
        if not os.path.exists(self.file_output_dir):
            logger.info(f"路径 {self.file_output_dir} 不存在，正在创建...")
            try:
                os.makedirs(self.file_output_dir)
            except Exception as e:
                logger.error(f"创建文件夹 {self.file_output_dir} 失败！错误: {e}")

        # 初始化数据库
        plugin_data_dir = self.tools.get_data_dir()
        db_path = os.path.join(plugin_data_dir, 'execution_history.db')
        self.db = ExecutionHistoryDB(db_path)
        
        # 初始化WebUI
        self.webui = CodeExecutorWebUI(self.db, self.webui_port)
        self.webui_task = None
        
        # 异步初始化数据库和启动WebUI
        asyncio.create_task(self._async_init())

        logger.info("代码执行器插件已加载！")
    
    async def _async_init(self):
        """异步初始化数据库和WebUI"""
        try:
            # 初始化数据库
            await self.db.init_database()
            
            # 启动WebUI服务器
            self.webui_task = asyncio.create_task(self.webui.start_server())
            logger.info(f"WebUI服务已启动，访问地址: http://localhost:{self.webui_port}")
        except Exception as e:
            logger.error(f"异步初始化失败: {e}", exc_info=True)


    @filter.llm_tool(name="execute_python_code")
    async def execute_python_code(self, event: AstrMessageEvent, code: str, description: str = "") -> str:
        '''
        **【代码执行器】**
        **优先使用此函数**，它远超 `fetch_url` 的单一网页内容获取功能，这个支持计算、文件操作、可视化和复杂网络请求。仅当任务明确只需要获取网页原始内容时才考虑 `fetch_url`.

        ---
        **【调用场景】**
        **必须**在以下场景调用此函数，执行代码获取精确结果，禁止文字猜测：
        1. **计算/数据处理**：如"计算 (1+5)*3/2"或"分析数据最大值"。
        2. **文件操作**：生成/读取 Excel、PDF、CSV 、图片类型等，如"生成 Excel 表格"。
        3. **网络请求**：请求各种api或者其他网络操作。
        4. **数据可视化**：如"绘制销售趋势图"或"生成饼图"。
        5. **图像处理**：如"下载猫的图片并调整大小"。
        6. **复杂逻辑**：如"规划最短路径"或"模拟抽奖"。
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
            - **推荐优先使用此方式，它比目录检测更可靠。**
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
        - 网络：`requests`, `aiohttp`, `BeautifulSoup`, `urllib`, `socket`
        - 数据：`pandas` (as pd), `numpy` (as np), `scipy`, `statsmodels`
        - 文件：`openpyxl`, `python-docx`, `fpdf2`, `json`, `yaml`, `csv`, `sqlite3`, `pickle`
        - 图表：`matplotlib.pyplot` (as plt), `seaborn` (as sns), `plotly`, `bokeh`
        - 图像：`PIL.Image`, `PIL`, `cv2` (OpenCV), `imageio`
        - 数据库：`sqlite3`, `pymongo`, `sqlalchemy`, `psycopg2`
        - 时间处理：`datetime`, `time`, `calendar`, `dateutil`
        - 加密安全：`hashlib`, `hmac`, `secrets`, `base64`, `cryptography`
        - 文本处理：`re`, `string`, `textwrap`, `difflib`, `nltk`, `jieba`
        - 系统工具：`os`, `sys`, `io`, `shutil`, `zipfile`, `tarfile`, `pathlib`, `subprocess`
        - 数学科学：`sympy`, `math`, `statistics`, `random`, `decimal`, `fractions`
        - 其他实用：`itertools`, `collections`, `functools`, `operator`, `copy`, `uuid`

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
        logger.info(f"角色{event.role}")
        if event.role != "admin":
            await event.send(MessageChain().message("❌ 你没有权限使用此功能！"))
            return "用户不是管理员，无权限运行代码，请告诉他不要使用此功能"
        logger.info(f"收到任务: {description or '无描述'}")
        logger.debug(f"代码内容:\n{code}")
        
        # 获取发言人信息
        sender_id = event.get_sender_id()
        sender_name = event.get_sender_name()
        start_time = time.time()

        try:
            result = await self._execute_code_safely(code)
            execution_time = time.time() - start_time

            if result["success"]:
                response_parts = ["✅ 任务完成！"]
                if result["output"] and result["output"].strip():
                    output = result["output"].strip()
                    if len(output) > self.max_output_length:
                        output = output[:self.max_output_length] + "\n...(内容已截断)"
                    response_parts.append(f"📤 执行结果：\n```\n{output}\n```")

                text_response = "\n".join(response_parts)
                await event.send(MessageChain().message(text_response))

                # 构建返回给LLM的详细信息
                llm_context_parts = ["✅ 代码执行成功！"]
                
                # 添加执行输出到LLM上下文
                if result["output"] and result["output"].strip():
                    full_output = result["output"].strip()
                    llm_context_parts.append(f"📤 执行结果：\n```\n{full_output}\n```")

                # 发送文件并记录到LLM上下文
                sent_files = []
                if result["file_paths"]:
                    logger.info(f"发现 {len(result['file_paths'])} 个待发送文件，正在处理...")
                    for file_path in result["file_paths"]:
                        if not os.path.exists(file_path) or not os.path.isfile(file_path):
                            logger.warning(f"文件不存在或是个目录，跳过发送: {file_path}")
                            await event.send(MessageChain().message(
                                f"🤔 警告: AI请求发送的文件不存在: {os.path.basename(file_path)}"))
                            continue
                        try:
                            file_name = os.path.basename(file_path)
                            is_image = any(
                                file_name.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp'])
                            if is_image:
                                logger.info(f"正在以图片形式发送: {file_path}")
                                await event.send(MessageChain().file_image(file_path))
                                sent_files.append(f"📷 已发送图片: {file_name}")
                            else:
                                logger.info(f"正在以文件形式发送: {file_path}")
                                await event.send(MessageChain().message(f"📄 正在发送文件: {file_name}"))
                                chain = [Comp.File(file=file_path, name=file_name)]
                                await event.send(event.chain_result(chain))
                                sent_files.append(f"📄 已发送文件: {file_name}")
                        except Exception as e:
                            logger.error(f"发送文件/图片 {file_path} 失败: {e}", exc_info=True)
                            await event.send(MessageChain().message(f"❌ 发送文件 {os.path.basename(file_path)} 失败"))
                            sent_files.append(f"❌ 发送失败: {os.path.basename(file_path)}")
                
                # 添加文件发送信息到LLM上下文
                if sent_files:
                    llm_context_parts.append("\n".join(sent_files))

                # 构建完整的LLM上下文返回信息
                llm_context = "\n\n".join(llm_context_parts)
                
                # 记录成功执行到数据库
                try:
                    await self.db.add_execution_record(
                        sender_id=sender_id,
                        sender_name=sender_name,
                        code=code,
                        description=description,
                        success=True,
                        output=result["output"],
                        error_msg=None,
                        file_paths=result["file_paths"],
                        execution_time=execution_time
                    )
                except Exception as db_error:
                    logger.error(f"记录执行历史失败: {db_error}", exc_info=True)
                
                if not (result["output"] and result["output"].strip()) and not result["file_paths"]:
                    return "代码执行完成，但无文件、图片或文本输出。"
                return llm_context

            else:
                error_msg = f"❌ 代码执行失败！\n错误信息：\n```\n{result['error']}\n```"
                if result.get("output"):
                    error_msg += f"\n\n出错前输出：\n```\n{result['output']}\n```"
                error_msg += "\n请分析错误信息，修正代码或调整逻辑后重试。"
                await event.send(MessageChain().message(error_msg))
                
                # 记录失败执行到数据库
                try:
                    await self.db.add_execution_record(
                        sender_id=sender_id,
                        sender_name=sender_name,
                        code=code,
                        description=description,
                        success=False,
                        output=result.get("output"),
                        error_msg=result["error"],
                        file_paths=[],
                        execution_time=execution_time
                    )
                except Exception as db_error:
                    logger.error(f"记录执行历史失败: {db_error}", exc_info=True)
                
                # 返回详细的错误信息给LLM上下文
                return error_msg

        except Exception as e:
            logger.error(f"插件内部错误: {str(e)}", exc_info=True)
            execution_time = time.time() - start_time
            error_msg = f"🔥 插件内部错误：{str(e)}\n请检查插件配置或环境后重试。"
            await event.send(MessageChain().message(error_msg))
            
            # 记录插件内部错误到数据库
            try:
                await self.db.add_execution_record(
                    sender_id=sender_id,
                    sender_name=sender_name,
                    code=code,
                    description=description,
                    success=False,
                    output=None,
                    error_msg=f"插件内部错误: {str(e)}",
                    file_paths=[],
                    execution_time=execution_time
                )
            except Exception as db_error:
                logger.error(f"记录执行历史失败: {db_error}", exc_info=True)
            
            # 返回详细的错误信息给LLM上下文
            return error_msg

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
                        except Exception as e:
                            print(f"[保存图表失败: {e}]")
                        finally:
                            plt.close(fig)

                    plt.show = lambda *args, **kwargs: save_and_close_current_fig("plot")
                    plt.savefig = lambda fname, *args, **kwargs: save_and_close_current_fig(
                        os.path.splitext(os.path.basename(fname))[0] if isinstance(fname, str) else "plot"
                    )
                    exec_globals.update({'matplotlib': matplotlib, 'plt': plt})
                except ImportError:
                    logger.warning("matplotlib 不可用，图表功能禁用")

                libs_to_inject = {
                    # 数据科学核心
                    'numpy': 'np', 'pandas': 'pd', 'scipy': 'scipy', 'statsmodels': 'statsmodels',
                    # 网络请求
                    'requests': 'requests', 'aiohttp': 'aiohttp', 'urllib': 'urllib', 'socket': 'socket',
                    # 可视化
                    'seaborn': 'sns', 'plotly': 'plotly', 'bokeh': 'bokeh',
                    # 文件处理
                    'openpyxl': 'openpyxl', 'docx': 'docx', 'fpdf': 'fpdf', 
                    'json': 'json', 'yaml': 'yaml', 'csv': 'csv', 'pickle': 'pickle',
                    # 数据库
                    'sqlite3': 'sqlite3', 'pymongo': 'pymongo', 'sqlalchemy': 'sqlalchemy',
                    'psycopg2': 'psycopg2',
                    # 图像处理
                    'PIL': 'PIL', 'cv2': 'cv2', 'imageio': 'imageio',
                    # 时间处理
                    'datetime': 'datetime', 'time': 'time', 'calendar': 'calendar',
                    # 加密安全
                    'hashlib': 'hashlib', 'hmac': 'hmac', 'secrets': 'secrets', 
                    'base64': 'base64', 'cryptography': 'cryptography',
                    # 文本处理
                    're': 're', 'string': 'string', 'textwrap': 'textwrap', 
                    'difflib': 'difflib', 'nltk': 'nltk', 'jieba': 'jieba',
                    # 系统工具
                    'os': 'os', 'sys': 'sys', 'shutil': 'shutil', 'zipfile': 'zipfile',
                    'tarfile': 'tarfile', 'pathlib': 'pathlib', 'subprocess': 'subprocess',
                    # 数学科学
                    'sympy': 'sympy', 'math': 'math', 'statistics': 'statistics',
                    'random': 'random', 'decimal': 'decimal', 'fractions': 'fractions',
                    # 实用工具
                    'itertools': 'itertools', 'collections': 'collections', 
                    'functools': 'functools', 'operator': 'operator', 'copy': 'copy', 'uuid': 'uuid'
                }
                for lib_name, alias in libs_to_inject.items():
                    try:
                        lib = __import__(lib_name)
                        exec_globals[alias or lib_name] = lib
                    except ImportError:
                        logger.warning(f"库 {lib_name} 不可用，相关功能禁用")
                # 特殊库导入处理
                try:
                    from bs4 import BeautifulSoup; exec_globals['BeautifulSoup'] = BeautifulSoup
                except ImportError:
                    pass
                try:
                    from PIL import Image; exec_globals['Image'] = Image
                except ImportError:
                    pass
                try:
                    from dateutil import parser as dateutil_parser; exec_globals['dateutil_parser'] = dateutil_parser
                    import dateutil; exec_globals['dateutil'] = dateutil
                except ImportError:
                    pass
                # 机器学习库导入已移除

                exec(code_to_run, exec_globals)

                if 'plt' in exec_globals and plt.get_fignums():
                    for fig_num in list(plt.get_fignums()):
                        plt.figure(fig_num)
                        save_and_close_current_fig("plot_auto")

                if 'plt' in exec_globals: plt.show, plt.savefig = original_show, original_savefig

                # 优先使用 FILES_TO_SEND 列表，提高文件归属准确性
                if files_to_send_explicitly:
                    # 如果用户显式添加了文件到 FILES_TO_SEND，优先使用这些文件
                    all_files_to_send = files_to_send_explicitly[:]
                    # 同时检测新生成的文件作为补充
                    files_after = set(os.listdir(file_output_dir)) if os.path.exists(file_output_dir) else set()
                    newly_generated_filenames = files_after - files_before
                    newly_generated_files = [os.path.join(file_output_dir, f) for f in newly_generated_filenames]
                    # 去重合并
                    all_files_to_send.extend([f for f in newly_generated_files if f not in all_files_to_send])
                else:
                    # 如果没有显式指定文件，则使用目录检测方式
                    files_after = set(os.listdir(file_output_dir)) if os.path.exists(file_output_dir) else set()
                    newly_generated_filenames = files_after - files_before
                    all_files_to_send = [os.path.join(file_output_dir, f) for f in newly_generated_filenames]

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
                except:
                    pass

        # 使用 asyncio.to_thread 替代 threading + queue，避免阻塞事件循环
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(run_code, code, self.file_output_dir),
                timeout=self.timeout_seconds
            )
            return result
        except asyncio.TimeoutError:
            return {"success": False, "error": f"代码执行超时（超过 {self.timeout_seconds} 秒）", "output": None,
                    "file_paths": []}

    async def terminate(self):
        """插件卸载时的清理工作"""
        try:
            # 停止WebUI服务器
            if self.webui_task and not self.webui_task.done():
                logger.info("正在停止WebUI服务器...")
                await self.webui.stop_server()
                self.webui_task.cancel()
                try:
                    await self.webui_task
                except asyncio.CancelledError:
                    pass
            
            logger.info("代码执行器插件已卸载")
        except Exception as e:
            logger.error(f"插件卸载时发生错误: {e}", exc_info=True)
