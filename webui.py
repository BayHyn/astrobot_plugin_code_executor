import asyncio
from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
from typing import Optional
import os
from datetime import datetime
from .database import ExecutionHistoryDB
from astrbot.api import logger


class CodeExecutorWebUI:
    """代码执行器WebUI服务"""
    
    def __init__(self, db: ExecutionHistoryDB, port: int = 22334, file_output_dir: str = None, enable_file_serving: bool = False):
        self.db = db
        self.port = port
        self.file_output_dir = file_output_dir
        self.enable_file_serving = enable_file_serving
        self.app = FastAPI(title="代码执行器历史记录", description="查看AI代码执行历史记录")
        self.server = None
        self.setup_routes()
    
    def setup_routes(self):
        """设置路由"""
        
        @self.app.get("/", response_class=HTMLResponse)
        async def index(request: Request):
            """主页"""
            return HTMLResponse(content=self.get_index_html())
        
        @self.app.get("/api/history")
        async def get_history(
            page: int = Query(1, ge=1),
            page_size: int = Query(20, ge=1, le=100),
            sender_id: Optional[str] = Query(None),
            search: Optional[str] = Query(None),
            success_filter: Optional[bool] = Query(None)
        ):
            """获取历史记录API"""
            try:
                result = await self.db.get_execution_history(
                    page=page,
                    page_size=page_size,
                    sender_id=sender_id,
                    search_keyword=search,
                    success_filter=success_filter
                )
                return JSONResponse(content=result)
            except Exception as e:
                logger.error(f"获取历史记录失败: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/detail/{record_id}")
        async def get_detail(record_id: int):
            """获取执行详情API"""
            try:
                result = await self.db.get_execution_detail(record_id)
                if not result:
                    raise HTTPException(status_code=404, detail="记录不存在")
                return JSONResponse(content=result)
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"获取执行详情失败: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/statistics")
        async def get_statistics():
            """获取统计信息API"""
            try:
                result = await self.db.get_statistics()
                return JSONResponse(content=result)
            except Exception as e:
                logger.error(f"获取统计信息失败: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
        
        # 文件服务路由（用于本地路由发送）
        if self.enable_file_serving and self.file_output_dir:
            @self.app.get("/files/{file_name}")
            async def serve_file(file_name: str):
                """提供文件下载服务"""
                try:
                    file_path = os.path.join(self.file_output_dir, file_name)
                    if not os.path.exists(file_path) or not os.path.isfile(file_path):
                        raise HTTPException(status_code=404, detail="文件不存在")
                    
                    # 安全检查：确保文件在指定目录内
                    real_file_path = os.path.realpath(file_path)
                    real_output_dir = os.path.realpath(self.file_output_dir)
                    if not real_file_path.startswith(real_output_dir):
                        raise HTTPException(status_code=403, detail="访问被拒绝")
                    
                    return FileResponse(file_path, filename=file_name)
                except HTTPException:
                    raise
                except Exception as e:
                    logger.error(f"文件服务失败: {e}", exc_info=True)
                    raise HTTPException(status_code=500, detail=str(e))
    
    def get_index_html(self) -> str:
        """获取主页HTML"""
        return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>代码执行器历史记录</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background-color: #f8f9fa;
            color: #333;
            line-height: 1.6;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        .header {
            background: white;
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 30px;
            text-align: center;
        }
        
        .header h1 {
            color: #2c3e50;
            font-size: 2.5em;
            margin-bottom: 10px;
            font-weight: 300;
        }
        
        .header p {
            color: #7f8c8d;
            font-size: 1.1em;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: white;
            padding: 25px;
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            text-align: center;
            transition: transform 0.2s ease;
        }
        
        .stat-card:hover {
            transform: translateY(-2px);
        }
        
        .stat-number {
            font-size: 2.5em;
            font-weight: bold;
            color: #3498db;
            margin-bottom: 5px;
        }
        
        .stat-label {
            color: #7f8c8d;
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .controls {
            background: white;
            padding: 25px;
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }
        
        .controls-row {
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            align-items: center;
        }
        
        .form-group {
            display: flex;
            flex-direction: column;
            min-width: 150px;
        }
        
        .form-group label {
            margin-bottom: 5px;
            font-weight: 500;
            color: #555;
        }
        
        .form-group input, .form-group select {
            padding: 10px;
            border: 2px solid #e1e8ed;
            border-radius: 8px;
            font-size: 14px;
            transition: border-color 0.2s ease;
        }
        
        .form-group input:focus, .form-group select:focus {
            outline: none;
            border-color: #3498db;
        }
        
        .btn {
            padding: 10px 20px;
            background: #3498db;
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            transition: background-color 0.2s ease;
            align-self: flex-end;
        }
        
        .btn:hover {
            background: #2980b9;
        }
        
        .btn-secondary {
            background: #95a5a6;
        }
        
        .btn-secondary:hover {
            background: #7f8c8d;
        }
        
        .records-container {
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        
        .records-header {
            padding: 20px 25px;
            border-bottom: 1px solid #e1e8ed;
            background: #f8f9fa;
        }
        
        .records-header h2 {
            color: #2c3e50;
            font-size: 1.5em;
            font-weight: 500;
        }
        
        .record-item {
            padding: 20px 25px;
            border-bottom: 1px solid #e1e8ed;
            transition: background-color 0.2s ease;
            cursor: pointer;
        }
        
        .record-item:hover {
            background: #f8f9fa;
        }
        
        .record-item:last-child {
            border-bottom: none;
        }
        
        .record-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        
        .record-user {
            font-weight: 600;
            color: #2c3e50;
        }
        
        .record-time {
            color: #7f8c8d;
            font-size: 0.9em;
        }
        
        .record-status {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .status-success {
            background: #d4edda;
            color: #155724;
        }
        
        .status-error {
            background: #f8d7da;
            color: #721c24;
        }
        
        .record-description {
            color: #555;
            margin-bottom: 10px;
            font-style: italic;
        }
        
        .record-code {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #3498db;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 0.9em;
            overflow-x: auto;
            white-space: pre-wrap;
            max-height: none;
            overflow-y: visible;
        }
        
        .pagination {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 10px;
            padding: 25px;
            background: white;
            margin-top: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        
        .pagination button {
            padding: 8px 16px;
            border: 2px solid #e1e8ed;
            background: white;
            color: #555;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        
        .pagination button:hover:not(:disabled) {
            border-color: #3498db;
            color: #3498db;
        }
        
        .pagination button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .pagination .current-page {
            background: #3498db;
            color: white;
            border-color: #3498db;
        }
        
        .loading {
            text-align: center;
            padding: 50px;
            color: #7f8c8d;
        }
        
        .error {
            background: #f8d7da;
            color: #721c24;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
            text-align: center;
        }
        
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.5);
            z-index: 1000;
        }
        
        .modal-content {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: white;
            border-radius: 12px;
            max-width: 90%;
            max-height: 90%;
            overflow-y: auto;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }
        
        .modal-header {
            padding: 20px 25px;
            border-bottom: 1px solid #e1e8ed;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .modal-title {
            font-size: 1.3em;
            font-weight: 600;
            color: #2c3e50;
        }
        
        .close-btn {
            background: none;
            border: none;
            font-size: 1.5em;
            cursor: pointer;
            color: #7f8c8d;
            padding: 0;
            width: 30px;
            height: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .close-btn:hover {
            color: #333;
        }
        
        .modal-body {
            padding: 25px;
        }
        
        .detail-section {
            margin-bottom: 25px;
        }
        
        .detail-label {
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 8px;
            display: block;
        }
        
        .detail-content {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #3498db;
            white-space: pre-wrap;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 0.9em;
            max-height: 500px;
            overflow-y: auto;
        }
        
        .file-list {
            list-style: none;
            padding: 0;
        }
        
        .file-item {
            background: #e8f4fd;
            padding: 8px 12px;
            margin: 5px 0;
            border-radius: 6px;
            font-family: monospace;
            font-size: 0.9em;
        }
        
        @media (max-width: 768px) {
            .container {
                padding: 10px;
            }
            
            .controls-row {
                flex-direction: column;
                align-items: stretch;
            }
            
            .form-group {
                min-width: auto;
            }
            
            .record-header {
                flex-direction: column;
                align-items: flex-start;
                gap: 10px;
            }
            
            .modal-content {
                max-width: 95%;
                max-height: 95%;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 代码执行器历史记录</h1>
            <p>查看AI代码执行的历史记录和详细信息</p>
        </div>
        
        <div class="stats-grid" id="statsGrid">
            <!-- 统计信息将在这里动态加载 -->
        </div>
        
        <div class="controls">
            <div class="controls-row">
                <div class="form-group">
                    <label for="searchInput">搜索关键词</label>
                    <input type="text" id="searchInput" placeholder="搜索代码、描述或用户名...">
                </div>
                <div class="form-group">
                    <label for="senderIdInput">用户ID</label>
                    <input type="text" id="senderIdInput" placeholder="筛选特定用户...">
                </div>
                <div class="form-group">
                    <label for="successFilter">执行状态</label>
                    <select id="successFilter">
                        <option value="">全部</option>
                        <option value="true">成功</option>
                        <option value="false">失败</option>
                    </select>
                </div>
                <button class="btn" onclick="searchRecords()">搜索</button>
                <button class="btn btn-secondary" onclick="resetFilters()">重置</button>
            </div>
        </div>
        
        <div class="records-container">
            <div class="records-header">
                <h2>执行记录</h2>
            </div>
            <div id="recordsList">
                <div class="loading">正在加载...</div>
            </div>
        </div>
        
        <div class="pagination" id="pagination" style="display: none;">
            <!-- 分页控件将在这里动态生成 -->
        </div>
    </div>
    
    <!-- 详情模态框 -->
    <div class="modal" id="detailModal">
        <div class="modal-content">
            <div class="modal-header">
                <div class="modal-title">执行详情</div>
                <button class="close-btn" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body" id="modalBody">
                <!-- 详情内容将在这里动态加载 -->
            </div>
        </div>
    </div>
    
    <script>
        let currentPage = 1;
        let currentFilters = {};
        
        // 页面加载时初始化
        document.addEventListener('DOMContentLoaded', function() {
            loadStatistics();
            loadRecords();
            
            // 搜索框回车事件
            document.getElementById('searchInput').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    searchRecords();
                }
            });
        });
        
        // 加载统计信息
        async function loadStatistics() {
            try {
                const response = await fetch('/api/statistics');
                const stats = await response.json();
                
                const statsGrid = document.getElementById('statsGrid');
                statsGrid.innerHTML = `
                    <div class="stat-card">
                        <div class="stat-number">${stats.total_executions}</div>
                        <div class="stat-label">总执行次数</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">${stats.successful_executions}</div>
                        <div class="stat-label">成功执行</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">${stats.failed_executions}</div>
                        <div class="stat-label">失败执行</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">${stats.success_rate}%</div>
                        <div class="stat-label">成功率</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">${stats.unique_users}</div>
                        <div class="stat-label">用户数量</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">${stats.recent_executions}</div>
                        <div class="stat-label">近7天执行</div>
                    </div>
                `;
            } catch (error) {
                console.error('加载统计信息失败:', error);
            }
        }
        
        // 加载记录列表
        async function loadRecords(page = 1) {
            try {
                const params = new URLSearchParams({
                    page: page,
                    page_size: 20,
                    ...currentFilters
                });
                
                const response = await fetch(`/api/history?${params}`);
                const data = await response.json();
                
                displayRecords(data.records);
                displayPagination(data);
                currentPage = page;
            } catch (error) {
                console.error('加载记录失败:', error);
                document.getElementById('recordsList').innerHTML = 
                    '<div class="error">加载失败，请稍后重试</div>';
            }
        }
        
        // 显示记录列表
        function displayRecords(records) {
            const recordsList = document.getElementById('recordsList');
            
            if (records.length === 0) {
                recordsList.innerHTML = '<div class="loading">暂无记录</div>';
                return;
            }
            
            recordsList.innerHTML = records.map(record => `
                <div class="record-item" onclick="showDetail(${record.id})">
                    <div class="record-header">
                        <div>
                            <span class="record-user">${escapeHtml(record.sender_name)}</span>
                            <span class="record-status ${record.success ? 'status-success' : 'status-error'}">
                                ${record.success ? '成功' : '失败'}
                            </span>
                        </div>
                        <div class="record-time">${formatTime(record.created_at)}</div>
                    </div>
                    ${record.description ? `<div class="record-description">${escapeHtml(record.description)}</div>` : ''}
                    <div class="record-code">${escapeHtml(record.code)}</div>
                </div>
            `).join('');
        }
        
        // 显示分页
        function displayPagination(data) {
            const pagination = document.getElementById('pagination');
            
            if (data.total_pages <= 1) {
                pagination.style.display = 'none';
                return;
            }
            
            pagination.style.display = 'flex';
            
            let paginationHtml = '';
            
            // 上一页
            paginationHtml += `<button ${data.page <= 1 ? 'disabled' : ''} onclick="loadRecords(${data.page - 1})">上一页</button>`;
            
            // 页码
            const startPage = Math.max(1, data.page - 2);
            const endPage = Math.min(data.total_pages, data.page + 2);
            
            for (let i = startPage; i <= endPage; i++) {
                paginationHtml += `<button class="${i === data.page ? 'current-page' : ''}" onclick="loadRecords(${i})">${i}</button>`;
            }
            
            // 下一页
            paginationHtml += `<button ${data.page >= data.total_pages ? 'disabled' : ''} onclick="loadRecords(${data.page + 1})">下一页</button>`;
            
            pagination.innerHTML = paginationHtml;
        }
        
        // 搜索记录
        function searchRecords() {
            const search = document.getElementById('searchInput').value.trim();
            const senderId = document.getElementById('senderIdInput').value.trim();
            const successFilter = document.getElementById('successFilter').value;
            
            currentFilters = {};
            if (search) currentFilters.search = search;
            if (senderId) currentFilters.sender_id = senderId;
            if (successFilter) currentFilters.success_filter = successFilter === 'true';
            
            loadRecords(1);
        }
        
        // 重置筛选
        function resetFilters() {
            document.getElementById('searchInput').value = '';
            document.getElementById('senderIdInput').value = '';
            document.getElementById('successFilter').value = '';
            currentFilters = {};
            loadRecords(1);
        }
        
        // 显示详情
        async function showDetail(recordId) {
            try {
                const response = await fetch(`/api/detail/${recordId}`);
                const record = await response.json();
                
                const modalBody = document.getElementById('modalBody');
                modalBody.innerHTML = `
                    <div class="detail-section">
                        <span class="detail-label">用户信息</span>
                        <div>${escapeHtml(record.sender_name)} (ID: ${escapeHtml(record.sender_id)})</div>
                    </div>
                    
                    <div class="detail-section">
                        <span class="detail-label">执行时间</span>
                        <div>${formatTime(record.created_at)}</div>
                    </div>
                    
                    <div class="detail-section">
                        <span class="detail-label">执行状态</span>
                        <div>
                            <span class="record-status ${record.success ? 'status-success' : 'status-error'}">
                                ${record.success ? '成功' : '失败'}
                            </span>
                            ${record.execution_time ? ` (耗时: ${record.execution_time.toFixed(2)}秒)` : ''}
                        </div>
                    </div>
                    
                    ${record.description ? `
                    <div class="detail-section">
                        <span class="detail-label">任务描述</span>
                        <div class="detail-content">${escapeHtml(record.description)}</div>
                    </div>
                    ` : ''}
                    
                    <div class="detail-section">
                        <span class="detail-label">执行代码</span>
                        <div class="detail-content">${escapeHtml(record.code)}</div>
                    </div>
                    
                    ${record.output ? `
                    <div class="detail-section">
                        <span class="detail-label">执行输出</span>
                        <div class="detail-content">${escapeHtml(record.output)}</div>
                    </div>
                    ` : ''}
                    
                    ${record.error_msg ? `
                    <div class="detail-section">
                        <span class="detail-label">错误信息</span>
                        <div class="detail-content">${escapeHtml(record.error_msg)}</div>
                    </div>
                    ` : ''}
                    
                    ${record.file_paths && record.file_paths.length > 0 ? `
                    <div class="detail-section">
                        <span class="detail-label">生成文件</span>
                        <ul class="file-list">
                            ${record.file_paths.map(path => `<li class="file-item">${escapeHtml(path)}</li>`).join('')}
                        </ul>
                    </div>
                    ` : ''}
                `;
                
                document.getElementById('detailModal').style.display = 'block';
            } catch (error) {
                console.error('加载详情失败:', error);
                alert('加载详情失败，请稍后重试');
            }
        }
        
        // 关闭模态框
        function closeModal() {
            document.getElementById('detailModal').style.display = 'none';
        }
        
        // 点击模态框外部关闭
        document.getElementById('detailModal').addEventListener('click', function(e) {
            if (e.target === this) {
                closeModal();
            }
        });
        
        // 工具函数
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        function formatTime(timeStr) {
            const date = new Date(timeStr);
            return date.toLocaleString('zh-CN', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
        }
    </script>
</body>
</html>
        """
    
    async def start_server(self):
        """启动WebUI服务器"""
        try:
            config = uvicorn.Config(
                app=self.app,
                host="0.0.0.0",
                port=self.port,
                log_level="info",
                access_log=False
            )
            self.server = uvicorn.Server(config)
            
            logger.info(f"WebUI服务器启动中，端口: {self.port}")
            logger.info(f"访问地址: http://localhost:{self.port}")
            
            # 在后台运行服务器
            await self.server.serve()
        except Exception as e:
            logger.error(f"WebUI服务器启动失败: {e}", exc_info=True)
            raise
    
    async def stop_server(self):
        """停止WebUI服务器"""
        if self.server:
            logger.info("正在停止WebUI服务器...")
            self.server.should_exit = True
            await asyncio.sleep(1)  # 给服务器一些时间来优雅关闭
            logger.info("WebUI服务器已停止")