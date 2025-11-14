import os

from ncatbot.plugin import BasePlugin, CompatibleEnrollment
from ncatbot.core import GroupMessage, PrivateMessage, BaseMessage
import requests
from bs4 import BeautifulSoup
import time
import sqlite3
from datetime import datetime

bot = CompatibleEnrollment  # 兼容回调函数注册器

    # --- 配置区 ---
TARGET_URL = "https://tushare.pro/news/fenghuang"
DB_FILE = "./db/tushare_news.db"  # 数据库文件路径
SCRAPE_INTERVAL_MINUTES = 10  # 抓取间隔时间（分钟）


class SystemTask(BasePlugin):
    name = "SystemTask"  # 插件名称
    version = "0.0.1"  # 插件版本
    author = "Your Name"  # 插件作者
    info = "这是一个示例插件，用于演示插件系统的基本功能"  # 插件描述
    dependencies = {}  # 插件依赖，格式: {"插件名": "版本要求"}
    
    
    group_command_map = {
        
        
    }
    
    private_command_map = {
        
    }
    
    

    # @bot.group_event()
    # async def on_group_event(self, msg: GroupMessage):
    #     # 群消息事件处理
        
        
        
        
        
        
    #     handler_name = self.group_command_map.get(msg.raw_message)
    #     if handler_name:
    #         handler = getattr(self, handler_name, None)
    #         if handler:
    #             await handler(msg)

    # @bot.private_event()
    # async def on_private_event(self, msg: PrivateMessage):
    #      # 好友消息事件处理
        
        
        
       
    #     handler_name = self.private_command_map.get(msg.raw_message)
    #     if handler_name:
    #         handler = getattr(self, handler_name, None)
    #         if handler:
    #             await handler(msg)


    async def on_load(self):
        # 插件加载时执行的操作
        print(f"{self.name} 插件已加载")
        print(f"插件版本: {self.version}")

        # 注册功能示例
        self.register_user_func(
            name="test",
            handler=self.test_handler,
            prefix="/test",
            description="测试功能",
            usage="/test",
            examples=["/test"],
            tags=["test", "example"],
            metadata={"category": "utility"}
        )

        # 注册配置项示例
        self.register_config(
            key="greeting",
            default="你好",
            on_change=lambda value, msg, _: self.on_greeting_change(msg, value),
            description="问候语",
            value_type="str",
            allowed_values=["你好", "Hello", "Hi"],
            metadata={"category": "greeting", "max_length": 20}
        )

        # TODO: Uncomment when register_task is implemented
        # # 注册定时任务
        self.add_scheduled_task(
            name="news_scraper",
            interval=SCRAPE_INTERVAL_MINUTES * 10,
            job_func=self.scrape_and_save
        )

    async def test_handler(self, msg: BaseMessage):
        # 测试功能处理函数
        await msg.reply_text(f"测试功能调用成功！当前问候语: {self.config["greeting"]}")

    async def on_greeting_change(self, msg: BaseMessage, value):
        # 配置变更回调函数
        await msg.reply_text(f"问候语已修改为: {value}")
        
        


    # --- 数据库操作 ---

    def setup_database(self):
        """初始化数据库和数据表"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # 创建用于存放消息热点数据的表
        # **主要改动点**: 将 UNIQUE 约束调整为只针对 record_date 和 hour_minute_key
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS message_hotspots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_date DATE NOT NULL,
                hour_minute_key TEXT NOT NULL,
                message_content TEXT NOT NULL,
                message_type TEXT,
                UNIQUE(record_date, hour_minute_key) -- 确保每个时间点只有一条记录
            );
        ''')
        conn.commit()
        conn.close()
        print(f"数据库 '{DB_FILE}' 初始化完成。")

    def insert_news(self, news_item):
        """将单条新闻插入数据库，如果已存在则忽略"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        try:
            # 尝试插入，如果违反了上面定义的 UNIQUE(record_date, hour_minute_key) 约束，则会抛出异常
            cursor.execute(
                "INSERT INTO message_hotspots (record_date, hour_minute_key, message_content, message_type) VALUES (?, ?, ?, ?)",
                (news_item['date'], news_item['time_key'], news_item['content'], news_item['type'])
            )
            conn.commit()
            print(f"  [+] 新闻已入库: {news_item['time_key']} {news_item['content'][:30]}...")
            return True
        except sqlite3.IntegrityError:
            # 捕获到这个异常意味着 (record_date, hour_minute_key) 的组合已存在，直接跳过即可
            # print(f"  [-] 时间点 {news_item['date']} {news_item['time_key']} 的新闻已存在，跳过。")
            return False
        finally:
            conn.close()

    # --- 爬虫核心逻辑 ---

    async def scrape_and_save(self):
        self.setup_database()
        """
        执行一次新闻抓取和存储操作。
        """
        print(f"\n--- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 开始抓取最新新闻 ---")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        cookies = {
            'uid': '2|1:0|10:1755752882|3:uid|8:ODI5NjU2|61a169cac94d89fdddba24651dae8a9e701b7577ae66b71ae723516388ced713',
            'username': '2|1:0|10:1755752882|8:username|8:d2FuZ3l1|a740192736300eeb1ed6bb63b558a6e4b7eb687bb5f5c781006c4fbe6b9164a8'
        }
        
        css_selector = "#news_全部 > div"

        try:
            response = requests.get(TARGET_URL, cookies=cookies, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            news_elements = soup.select(css_selector)
            
            if not news_elements:
                print("错误: 未找到任何新闻条目，请检查选择器或网站结构。")
                return

            new_items_count = 0
            # 只处理最新的10条
            for element in news_elements[:10]:
                full_text = element.get_text(strip=True)
                
                time_key = "未知时间"
                content = full_text
                if len(full_text) > 5 and full_text[2] == ':':
                    time_key = full_text[:5]
                    content = full_text[5:].strip()

                news_item = {
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'time_key': time_key,
                    'content': content,
                    'type': '凤凰新闻' # 消息类型
                }
                
                # insert_news 函数现在会根据新的 UNIQUE 约束来判断重复
                if self.insert_news(news_item):
                    new_items_count += 1
            
            print(f"抓取完成，共找到 {len(news_elements)} 条，处理了前 10 条，新增 {new_items_count} 条。")

        except requests.exceptions.RequestException as e:
            print(f"错误: 请求网址时发生错误: {e}")
        except Exception as e:
            print(f"发生未知错误: {e}")
