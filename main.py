import asyncio
import sys
import io
import time
import traceback
import os
import base64
from datetime import datetime
from typing import Dict, Any, List
import requests

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api import logger
from astrbot.api import AstrBotConfig
import astrbot.api.message_components as Comp
from astrbot.api.provider import ProviderRequest
from astrbot.core.message.components import Plain

from .database import ExecutionHistoryDB
from .webui import CodeExecutorWebUI


@register("code_executor", "Xican", "代码执行器 - 全能小狐狸汐林", "2.2.3--img")
class CodeExecutorPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config or {}
        self.tools = StarTools()  # 获取框架工具

        # 优先从配置文件读取配置，否则使用默认值
        self.timeout_seconds = self.config.get("timeout_seconds", 90)
        self.max_output_length = self.config.get("max_output_length", 3000)
        self.enable_webui = self.config.get("enable_webui", False)
        self.webui_port = self.config.get("webui_port", 10000)
        self.enable_lagrange_adapter = self.config.get("enable_lagrange_adapter", False)
        self.lagrange_api_port = self.config.get("lagrange_api_port", 8083)
        self.enable_local_route_sending = self.config.get("enable_local_route_sending", False)
        self.lagrange_host = self.config.get("lagrange_host", "127.0.0.1")
        self.local_route_host = self.config.get("local_route_host", "localhost")

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
        
        # 只有启用WebUI时才初始化
        if self.enable_webui:
            self.webui = CodeExecutorWebUI(
                self.db, 
                self.webui_port, 
                self.file_output_dir, 
                self.enable_local_route_sending
            )
        else:
            self.webui = None
        self.webui_task = None
        
        # 异步初始化数据库和启动WebUI
        asyncio.create_task(self._async_init())

        logger.info("代码执行器插件已加载！")
    
    async def _upload_file_via_lagrange(self, file_path: str, event: AstrMessageEvent) -> bool:
        """通过Lagrange API上传文件"""
        try:
            file_name = os.path.basename(file_path)
            
            # 检查是否为私聊
            is_private = event.is_private_chat() if hasattr(event, 'is_private_chat') else False
            
            if is_private:
                # 私聊文件上传
                url = f"http://{self.lagrange_host}:{self.lagrange_api_port}/upload_private_file"
                data = {
                    "user_id": event.get_sender_id(),
                    "file": file_path,
                    "name": file_name
                }
            else:
                # 群文件上传
                url = f"http://{self.lagrange_host}:{self.lagrange_api_port}/upload_group_file"
                data = {
                    "group_id": event.get_group_id() if hasattr(event, 'get_group_id') else 0,
                    "file": file_path,
                    "name": file_name,
                    "folder": "/"
                }
            
            response = requests.post(url, json=data, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get("status") == "ok" and result.get("retcode") == 0:
                logger.info(f"Lagrange文件上传成功: {file_name}")
                return True
            else:
                logger.error(f"Lagrange文件上传失败: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Lagrange文件上传异常: {e}", exc_info=True)
            return False
    
    async def _send_file_via_local_route(self, file_path: str, event: AstrMessageEvent) -> bool:
        """通过本地路由发送文件"""
        try:
            # 检查WebUI是否启用
            if not self.enable_webui or not self.webui:
                logger.warning("WebUI未启用，无法使用本地路由发送文件")
                return False
                
            file_name = os.path.basename(file_path)
            
            # 安全检查：确保文件在输出目录内
            real_file_path = os.path.realpath(file_path)
            real_output_dir = os.path.realpath(self.file_output_dir)
            if not real_file_path.startswith(real_output_dir):
                logger.warning(f"文件不在输出目录内，跳过本地路由发送: {file_path}")
                return False
            
            # 构建文件URL（使用实际端口）
            actual_port = self.webui.port
            file_url = f"http://{self.local_route_host}:{actual_port}/files/{file_name}"
            
            # 使用AstrBot原生方法发送文件URL
            is_image = any(
                file_name.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp'])
            
            if is_image:
                logger.info(f"正在以图片URL形式发送: {file_url}")
                await event.send(MessageChain().file_image(file_url))
            else:
                logger.info(f"正在以文件URL形式发送: {file_url}")
                await event.send(MessageChain().message(f"📄 正在发送文件: {file_name}"))
                chain = [Comp.File(file=file_url, name=file_name)]
                await event.send(event.chain_result(chain))
            
            logger.info(f"本地路由文件发送成功: {file_name} -> {file_url}")
            return True
            
        except Exception as e:
            logger.error(f"本地路由文件发送异常: {e}", exc_info=True)
            return False
    
    async def _send_file_via_base64(self, file_path: str, event: AstrMessageEvent) -> bool:
        """通过base64编码发送文件"""
        try:
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            
            # 文件大小限制：5MB (考虑base64编码会增加约33%大小)
            max_size = 5 * 1024 * 1024  # 5MB
            if file_size > max_size:
                logger.warning(f"文件过大，跳过base64发送: {file_name} ({file_size / 1024 / 1024:.2f}MB > {max_size / 1024 / 1024}MB)")
                return False
            
            # 读取文件并编码为base64
            with open(file_path, 'rb') as f:
                file_data = f.read()
            
            base64_data = base64.b64encode(file_data).decode('utf-8')
            
            # 检测文件类型
            is_image = any(
                file_name.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp'])
            
            if is_image:
                logger.info(f"正在以base64图片形式发送: {file_name} ({file_size / 1024:.1f}KB)")
                await event.send(MessageChain().file_image(f"data:image/{file_name.split('.')[-1]};base64,{base64_data}"))
            else:
                logger.info(f"正在以base64文件形式发送: {file_name} ({file_size / 1024:.1f}KB)")
                await event.send(MessageChain().message(f"📄 正在发送文件: {file_name}"))
                chain = [Comp.File(file=f"data:application/octet-stream;base64,{base64_data}", name=file_name)]
                await event.send(event.chain_result(chain))
            
            logger.info(f"base64文件发送成功: {file_name}")
            return True
            
        except Exception as e:
            logger.error(f"base64文件发送异常: {e}", exc_info=True)
            return False
    
    def get_image_urls_from_message(self, message) -> List[str]:
        """从消息链中获取图片URL列表，包括引用消息中的图片"""
        image_urls = []
        try:
            # 打印原始消息和消息链内容
            logger.debug(f"原始消息: {message}")
            logger.debug(f"消息链内容: {message}")

            # 遍历消息链
            for component in message:
                # 打印每个组件的类型和内容
                logger.debug(f"组件类型: {type(component).__name__}")
                logger.debug(f"组件内容: {component.__dict__}")

                # 检查是否是图片组件
                if isinstance(component, Comp.Image):
                    # 使用url属性
                    if hasattr(component, 'url') and component.url:
                        logger.info(f"找到图片URL: {component.url}")
                        image_urls.append(component.url)
                    else:
                        logger.debug(f"图片组件属性: {dir(component)}")
                
                # 检查是否是Reply组件，从引用消息中提取图片
                elif isinstance(component, Comp.Reply):
                    logger.info(f"发现Reply组件，检查引用消息中的图片")
                    reply_chain = getattr(component, 'chain', [])
                    if reply_chain:
                        logger.info(f"Reply chain 包含 {len(reply_chain)} 个组件")
                        for reply_comp in reply_chain:
                            logger.debug(f"处理Reply chain组件类型: {type(reply_comp).__name__}")
                            if isinstance(reply_comp, Comp.Image):
                                if hasattr(reply_comp, 'url') and reply_comp.url:
                                    image_urls.append(reply_comp.url)
                                    logger.info(f"从引用消息中提取到图片URL: {reply_comp.url}")
                                else:
                                    logger.warning(f"引用消息中的图片组件缺少URL属性: {reply_comp}")
                    else:
                        logger.info(f"Reply组件的chain为空")
            
            logger.info(f"共找到 {len(image_urls)} 个图片URL")
            return image_urls
        except Exception as e:
            logger.error(f"获取图片失败: {str(e)}")
            return []

    async def _async_init(self):
        """异步初始化数据库和WebUI"""
        try:
            # 初始化数据库
            await self.db.init_database()
            
            # 只有启用WebUI时才启动WebUI服务器
            if self.enable_webui and self.webui:
                self.webui_task = asyncio.create_task(self.webui.start_server())
                # 等待一小段时间确保端口分配完成
                await asyncio.sleep(0.1)
                actual_port = self.webui.port
                logger.info(f"WebUI服务已启动，访问地址: http://localhost:{actual_port}")
                
                # 记录文件发送配置状态
                if self.enable_local_route_sending:
                    logger.info(f"本地路由发送已启用，文件服务地址: http://{self.local_route_host}:{actual_port}/files/")
            else:
                logger.info("WebUI已禁用")
            
            if self.enable_lagrange_adapter:
                logger.info(f"Lagrange适配器已启用，服务地址: {self.lagrange_host}:{self.lagrange_api_port}")
            if not self.enable_local_route_sending and not self.enable_lagrange_adapter:
                logger.info("使用AstrBot原生文件发送方式")
        except Exception as e:
            logger.error(f"异步初始化失败: {e}", exc_info=True)

    @filter.command("测试")
    async def debug_message_chain(self, event: AstrMessageEvent):
        """调试消息链结构的测试指令，参考别人的代码实现"""
        try:
            user_name = event.get_sender_name()
            logger.info(f"=== 消息链调试开始 - 用户: {user_name} ===")
            
            # 获取消息组件（参考别人的代码）
            message_components = event.message_obj.message
            logger.info(f"消息组件总数: {len(message_components)}")
            
            # 查找Reply组件（参考别人的代码实现）
            reply_component = None
            for comp in message_components:
                logger.info(f"检查组件: {type(comp).__name__}, isinstance(comp, Comp.Reply): {isinstance(comp, Comp.Reply)}")
                if isinstance(comp, Comp.Reply):
                    reply_component = comp
                    logger.info(f"*** 找到Reply组件! ID: {comp.id} ***")
                    break
            
            if not reply_component:
                logger.warning("未检测到Reply组件（用户未引用消息）")
                yield event.plain_result("未检测到引用消息")
                return
            
            # 详细分析Reply组件
            logger.info(f"Reply组件详情:")
            logger.info(f"  - ID: {reply_component.id}")
            logger.info(f"  - sender_id: {reply_component.sender_id}")
            logger.info(f"  - sender_nickname: {reply_component.sender_nickname}")
            logger.info(f"  - time: {reply_component.time}")
            logger.info(f"  - message_str: {reply_component.message_str}")
            logger.info(f"  - chain长度: {len(reply_component.chain)}")
            
            # 分析chain中的组件
            if reply_component.chain:
                logger.info(f"引用消息链内容:")
                for i, quoted_comp in enumerate(reply_component.chain):
                    logger.info(f"  组件{i+1}: {type(quoted_comp).__name__}")
                    logger.info(f"  组件{i+1}详情: {quoted_comp}")
                    
                    # 特别检查图片组件
                    if isinstance(quoted_comp, Comp.Image):
                        logger.info(f"  *** 发现图片组件! ***")
                        logger.info(f"  图片file: {getattr(quoted_comp, 'file', 'N/A')}")
                        logger.info(f"  图片url: {getattr(quoted_comp, 'url', 'N/A')}")
                        logger.info(f"  图片所有属性: {quoted_comp.__dict__}")
            else:
                logger.info("引用消息链为空")
            
            logger.info(f"=== 消息链调试结束 ===")
            yield event.plain_result("引用消息调试完成，请查看控制台日志")
            
        except Exception as e:
            logger.error(f"调试过程中出现错误: {e}", exc_info=True)
            yield event.plain_result(f"调试失败: {e}")
            yield event.plain_result(f"调试出错: {str(e)}")

    @filter.llm_tool(name="execute_python_code")
    async def execute_python_code(self, event: AstrMessageEvent, code: str, description: str = "") -> str:
        '''
        **This is a code execution function**
        **Prioritize this function**, it far surpasses the single web content fetching capability of `fetch_url`. It supports calculations, file operations, visualizations, and complex network requests. Only consider `fetch_url` when the task explicitly requires fetching raw web content.
        **【Usage Scenarios】**
        **MUST** call this function in the following scenarios to execute code for precise results, prohibit guessing with text:
        1. **Calculations/Data Processing**: e.g., "Calculate (1+5)*3/2" or "Analyze the maximum value in data".
        2. **File Operations**: Generate/read Excel, PDF, CSV, images, etc., e.g., "Generate an Excel table".
        3. **API Calls/Interface Requests**: Only when explicitly requested to call specific APIs or interfaces, e.g., "Call the weather API" or "Request data from REST interface".
        4. **Data Visualization**: e.g., "Draw a sales trend chart" or "Generate a pie chart".
        5. **Image Processing**: e.g., "Download a cat image and resize it".
        6. **Complex Logic**: e.g., "Plan the shortest path" or "Simulate a lottery".
        7. **File Operations**: Allow AI to generate code in the proper format to operate local files and send to users, including but not limited to delete, search, modify, etc.
        8. **Image Download and Processing**: When users send images in messages, you can download and process them using the `img_url` variable.
        **【File Handling Rules - MUST Strictly Follow】**
        1. **Create New File**: MUST save to `SAVE_DIR` directory, using `os.path.join(SAVE_DIR, 'filename')`
        2. **Send File**: MUST add the full file path to the `FILES_TO_SEND` list (this variable is global, do not define it in your code, use it directly). Once added to the list, the file will be automatically sent to the user, and the task is considered complete, no need to call this function repeatedly.

        **【Image Processing Rules - MUST Strictly Follow】**
        1. **Image URL Access**: Use the `img_url` variable (list type) to access image URLs from user messages. This variable is automatically populated with image URLs from the current message and will be included in the execution context.
        2. **Download Images**: Use requests or other libraries to download images from URLs in `img_url` list.
        3. **Process Images**: After downloading, you can process images using PIL, cv2, or other image processing libraries.
        4. **Context Preservation**: All image URLs from the current message are automatically preserved in the execution context and returned to the LLM for reference.

        **Example**:
        ```python
        # Create new file
        plt.savefig(os.path.join(SAVE_DIR, 'chart.png'))
        FILES_TO_SEND.append(os.path.join(SAVE_DIR, 'chart.png'))  # After adding, the file will be sent automatically, task complete
        
        # Send existing file (do not define FILES_TO_SEND in your code, use it directly)
        FILES_TO_SEND.append("D:/data/report.xlsx")  # Automatically sent after adding
        
        # Download and process images from user messages
        if img_url:  # img_url is a list of image URLs from user messages
            for i, url in enumerate(img_url):
                response = requests.get(url, timeout=30)
                image_path = os.path.join(SAVE_DIR, f'downloaded_image_{i}.jpg')
                with open(image_path, 'wb') as f:
                    f.write(response.content)
                # Process the image...
                FILES_TO_SEND.append(image_path)  # Send processed image
        ```
        - This function has full file system permissions and can read/write any accessible directory.
        **【Stop Conditions】**
        - Once the code executes successfully, files are generated and added to FILES_TO_SEND (if needed), or output is produced, the task is complete. No need to call this function repeatedly to continue the same task.
        - If there is no file or output, the function will explicitly return task completion information.
        **【Available Libraries】**
        Almost all common libraries are supported, feel free to write and execute code.
        **【Available Variables】**
        - `SAVE_DIR`: Directory for saving output files
        - `FILES_TO_SEND`: List for files to be sent to user (global variable, do not define)
        - `img_url`: List of image URLs from user messages (list type, automatically populated and preserved in execution context)
        **【Coding Requirements】**
        - File operations must check paths and exceptions.
        - Support operations on various drive letters.
        - Network requests must set timeouts and retries.
        - Code must run independently without external dependencies.
        Args:
            code(string): Independently runnable Python code.
            description(string): (Optional) Code function description.
        '''
        logger.info(f"角色{event.role}")
        if event.role != "admin":
            await event.send(MessageChain().message("❌ 你没有权限使用此功能！"))
            return "❌ 权限验证失败：用户不是管理员，无权限运行代码。请联系管理员获取权限。操作已终止，无需重复尝试。"
        logger.info(f"收到任务: {description or '无描述'}")
        logger.debug(f"代码内容:\n{code}")
        
        # 获取发言人信息
        sender_id = event.get_sender_id()
        sender_name = event.get_sender_name()
        start_time = time.time()

        # 获取消息中的图片URL
        img_urls = self.get_image_urls_from_message(event.message_obj.message)
        logger.info(f"检测到 {len(img_urls)} 个图片URL: {img_urls}")

        try:
            result = await self._execute_code_safely(code, img_urls)
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
                llm_context_parts = ["✅ 代码执行成功！任务已完全完成，无需再次执行。文件发送通过将路径添加到FILES_TO_SEND列表实现，一旦添加，文件将被自动处理和发送。"]
                
                # 添加图片URL信息到LLM上下文
                if img_urls:
                    img_context = f"📷 本次执行中可用的图片资源 ({len(img_urls)}个):\n"
                    for i, url in enumerate(img_urls, 1):
                        img_context += f"  {i}. {url}\n"
                    llm_context_parts.append(img_context.rstrip())
                
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
                                f"⚠️ 文件发送跳过: {os.path.basename(file_path)} (文件不存在)"))
                            continue
                        try:
                            file_name = os.path.basename(file_path)
                            
                            # 根据配置选择文件发送方式（优先级：本地路由 > Lagrange > AstrBot原生）
                            success = False
                            
                            if self.enable_local_route_sending and self.enable_webui and self.webui:
                                # 使用本地路由发送文件
                                success = await self._send_file_via_local_route(file_path, event)
                                if success:
                                    sent_files.append(f"📄 已通过本地路由发送文件: {file_name} - 发送成功，任务完成。")
                                else:
                                    sent_files.append(f"❌ 本地路由发送失败: {file_name}")
                                    logger.warning(f"本地路由发送失败，尝试其他发送方式: {file_name}")
                            
                            # 如果本地路由发送失败或未启用，尝试Lagrange
                            if not success and self.enable_lagrange_adapter:
                                success = await self._upload_file_via_lagrange(file_path, event)
                                if success:
                                    sent_files.append(f"📄 已通过Lagrange发送文件: {file_name} - 发送成功，任务完成。")
                                else:
                                    sent_files.append(f"❌ Lagrange发送失败: {file_name}")
                                    logger.warning(f"Lagrange发送失败，尝试AstrBot原生方式: {file_name}")
                            
                            # 如果前面的方式都失败或未启用，使用AstrBot原生方法发送文件
                            if not success:
                                is_image = any(
                                    file_name.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp'])
                                if is_image:
                                    logger.info(f"正在以图片形式发送: {file_path}")
                                    await event.send(MessageChain().file_image(file_path))
                                    sent_files.append(f"📷 已发送图片: {file_name} - 发送成功，任务完成。")
                                    success = True
                                else:
                                    logger.info(f"正在以文件形式发送: {file_path}")
                                    await event.send(MessageChain().message(f"📄 正在发送文件: {file_name}"))
                                    chain = [Comp.File(file=file_path, name=file_name)]
                                    await event.send(event.chain_result(chain))
                                    sent_files.append(f"📄 已发送文件: {file_name} - 发送成功，任务完成。")
                                    success = True
                            
                            # 如果所有方式都失败，尝试base64发送作为最后的备用方案
                            if not success:
                                logger.warning(f"所有发送方式失败，尝试base64发送: {file_name}")
                                base64_success = await self._send_file_via_base64(file_path, event)
                                if base64_success:
                                    sent_files.append(f"📦 已通过base64发送: {file_name} - 发送成功，任务完成。")
                                else:
                                    logger.error(f"所有发送方式均失败: {file_name}")
                                    sent_files.append(f"❌ 所有发送方式均失败: {file_name}")
                        except Exception as e:
                            logger.error(f"发送文件/图片 {file_path} 失败: {e}", exc_info=True)
                            await event.send(MessageChain().message(f"❌ 文件发送失败: {os.path.basename(file_path)}"))
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
                    return "✅ 代码执行完成，但无文件、图片或文本输出或者文件操作未添加到FILES_TO_SEND列表。任务已完全完成，无需再次执行或重复调用。"
                
                # 在返回内容末尾明确标记任务完成
                llm_context += "\n\n🎯 任务执行完毕，所有操作（包括文件发送）已成功完成。请停止进一步执行或调用此函数，避免重复。"
                return llm_context

            else:
                error_msg = f"❌ 代码执行失败！\n错误信息：\n```\n{result['error']}\n```"
                if result.get("output"):
                    error_msg += f"\n\n出错前输出：\n```\n{result['output']}\n```"
                error_msg += "\n💡 建议：请检查代码逻辑和语法，修正后可重新尝试执行。"
                
                # 添加图片URL信息到错误上下文
                if img_urls:
                    img_context = f"\n\n📷 本次执行中可用的图片资源 ({len(img_urls)}个):\n"
                    for i, url in enumerate(img_urls, 1):
                        img_context += f"  {i}. {url}\n"
                    error_msg += img_context.rstrip()
                
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
            error_msg = f"🔥 插件内部错误：{str(e)}\n💡 建议：请检查插件配置或环境设置。"
            
            # 添加图片URL信息到插件错误上下文
            if img_urls:
                img_context = f"\n\n📷 本次执行中可用的图片资源 ({len(img_urls)}个):\n"
                for i, url in enumerate(img_urls, 1):
                    img_context += f"  {i}. {url}\n"
                error_msg += img_context.rstrip()
            
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

    async def _execute_code_safely(self, code: str, img_urls: List[str] = None) -> Dict[str, Any]:
        def run_code(code_to_run: str, file_output_dir: str, image_urls: List[str] = None):
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
                    'img_url': image_urls or [],  # 提供图片URL列表给代码使用
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

                # 确保代码字符串使用正确的编码
                if isinstance(code_to_run, str):
                    # 处理可能的编码问题
                    try:
                        code_to_run.encode('utf-8')
                    except UnicodeEncodeError:
                        # 如果包含无法编码的字符，尝试清理
                        code_to_run = code_to_run.encode('utf-8', errors='ignore').decode('utf-8')
                
                exec(code_to_run, exec_globals)

                # 检查是否有未关闭的图表，但不自动保存，只关闭
                if 'plt' in exec_globals and plt.get_fignums():
                    for fig_num in list(plt.get_fignums()):
                        plt.figure(fig_num)
                        plt.close(fig_num)  # 只关闭图表，不保存

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

                # 安全处理输出内容的编码
                output_content = output_buffer.getvalue()
                try:
                    # 确保输出内容可以正确编码
                    output_content.encode('utf-8')
                except UnicodeEncodeError:
                    # 如果输出包含无法编码的字符，进行清理
                    output_content = output_content.encode('utf-8', errors='ignore').decode('utf-8')
                
                return {
                    "success": True, "output": output_content, "error": None,
                    "file_paths": all_files_to_send
                }
            except Exception:
                tb_str = traceback.format_exc()
                logger.error(f"代码执行出错:\n{tb_str}")
                
                # 安全处理错误输出的编码
                error_output = output_buffer.getvalue()
                try:
                    error_output.encode('utf-8')
                    tb_str.encode('utf-8')
                except UnicodeEncodeError:
                    error_output = error_output.encode('utf-8', errors='ignore').decode('utf-8')
                    tb_str = tb_str.encode('utf-8', errors='ignore').decode('utf-8')
                
                return {"success": False, "error": tb_str, "output": error_output, "file_paths": []}
            finally:
                sys.stdout, sys.stderr = old_stdout, old_stderr
                try:
                    if 'plt' in locals() and 'matplotlib' in sys.modules: plt.close('all')
                except:
                    pass

        # 使用 asyncio.to_thread 替代 threading + queue，避免阻塞事件循环
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(run_code, code, self.file_output_dir, img_urls),
                timeout=self.timeout_seconds
            )
            return result
        except asyncio.TimeoutError:
            return {"success": False, "error": f"代码执行超时（超过 {self.timeout_seconds} 秒）", "output": None,
                    "file_paths": []}

    async def terminate(self):
        """插件卸载时的清理工作"""
        try:
            logger.info("正在卸载代码执行器插件...")
            
            # 只有启用WebUI时才进行清理
            if self.enable_webui and hasattr(self, 'webui') and self.webui:
                try:
                    # 取消WebUI任务
                    if hasattr(self, 'webui_task') and self.webui_task and not self.webui_task.done():
                        self.webui_task.cancel()
                        logger.info("WebUI任务已取消")
                    
                    # 停止WebUI服务器
                    await self.webui.stop_server()
                    logger.info("WebUI服务器已停止")
                    
                except Exception as e:
                    logger.warning(f"清理WebUI时出现问题: {e}")
            
            logger.info("代码执行器插件已卸载")
            
        except Exception as e:
            logger.error(f"插件卸载过程中发生错误: {e}")
