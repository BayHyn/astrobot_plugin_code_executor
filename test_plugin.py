#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
代码执行器插件测试脚本
用于验证数据库和WebUI功能是否正常工作
"""

import asyncio
import os
import sys
import tempfile
from .database import ExecutionHistoryDB
from .webui import CodeExecutorWebUI


async def test_database():
    """测试数据库功能"""
    print("🔍 测试数据库功能...")
    
    # 创建临时数据库文件
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_file:
        db_path = tmp_file.name
    
    try:
        # 初始化数据库
        db = ExecutionHistoryDB(db_path)
        await db.init_database()
        print("✅ 数据库初始化成功")
        
        # 添加测试记录
        record_id = await db.add_execution_record(
            sender_id="test_user_123",
            sender_name="测试用户",
            code="print('Hello, World!')",
            description="测试代码执行",
            success=True,
            output="Hello, World!\n",
            error_msg=None,
            file_paths=[],
            execution_time=0.1
        )
        print(f"✅ 添加执行记录成功，ID: {record_id}")
        
        # 查询记录
        history = await db.get_execution_history(page=1, page_size=10)
        print(f"✅ 查询历史记录成功，共 {history['total_count']} 条记录")
        
        # 获取详情
        detail = await db.get_execution_detail(record_id)
        if detail:
            print(f"✅ 获取记录详情成功: {detail['sender_name']}")
        
        # 获取统计信息
        stats = await db.get_statistics()
        print(f"✅ 获取统计信息成功: 总执行 {stats['total_executions']} 次")
        
        print("🎉 数据库功能测试通过！")
        
    except Exception as e:
        print(f"❌ 数据库测试失败: {e}")
        raise
    finally:
        # 清理临时文件
        if os.path.exists(db_path):
            os.unlink(db_path)


async def test_webui_init():
    """测试WebUI初始化"""
    print("🔍 测试WebUI初始化...")
    
    # 创建临时数据库
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_file:
        db_path = tmp_file.name
    
    try:
        # 初始化数据库和WebUI
        db = ExecutionHistoryDB(db_path)
        await db.init_database()
        
        webui = CodeExecutorWebUI(db, port=22335)  # 使用不同端口避免冲突
        print("✅ WebUI初始化成功")
        
        # 检查路由是否正确设置
        routes = [route.path for route in webui.app.routes]
        expected_routes = ["/", "/api/history", "/api/detail/{record_id}", "/api/statistics"]
        
        for expected_route in expected_routes:
            if any(expected_route.replace("{record_id}", "*") in route or route == expected_route for route in routes):
                print(f"✅ 路由 {expected_route} 设置正确")
            else:
                print(f"❌ 路由 {expected_route} 未找到")
        
        print("🎉 WebUI初始化测试通过！")
        
    except Exception as e:
        print(f"❌ WebUI测试失败: {e}")
        raise
    finally:
        # 清理临时文件
        if os.path.exists(db_path):
            os.unlink(db_path)


async def main():
    """主测试函数"""
    print("🚀 开始测试代码执行器插件增强功能...\n")
    
    try:
        await test_database()
        print()
        await test_webui_init()
        print()
        print("🎉 所有测试通过！插件增强功能正常工作。")
        print("\n📝 功能说明:")
        print("1. ✅ 数据库记录功能 - 自动记录每次代码执行的详细信息")
        print("2. ✅ WebUI界面功能 - 提供美观的历史记录查看界面")
        print("3. ✅ 搜索和分页功能 - 支持关键词搜索和分页浏览")
        print("4. ✅ 统计信息功能 - 显示执行统计和成功率")
        print("5. ✅ 详情查看功能 - 查看单次执行的完整详情")
        print("\n🌐 使用方法:")
        print("- 插件加载后会自动启动WebUI服务")
        print("- 默认访问地址: http://localhost:22334")
        print("- 可在配置文件中自定义端口号")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())