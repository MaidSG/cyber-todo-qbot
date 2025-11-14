import os

from ncatbot.plugin import BasePlugin, CompatibleEnrollment
from ncatbot.core import GroupMessage, PrivateMessage, BaseMessage
from ncatbot.utils import config
from collections import defaultdict, deque
import time
import sqlite3

bot = CompatibleEnrollment  # 兼容回调函数注册器

DB_PATH = './db/groupchatting_config.db'

CREATE_TABLE_SQL = '''
CREATE TABLE IF NOT EXISTS group_config (
    group_id TEXT PRIMARY KEY,
    enabled INTEGER DEFAULT 0,
    note TEXT DEFAULT ''
);
'''




class GroupChatting(BasePlugin):
    # 复读机功能：记录每个群的上一条消息内容

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_config = {}
        self.last_message = {}
        # {group_id: {user_id: deque([timestamp, ...])}}
        self.user_messages = defaultdict(lambda: defaultdict(deque))

        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.create_table()
        self.load_group_config_from_db()
        import asyncio
        self.sync_task = asyncio.create_task(self.periodic_sync())

    def load_group_config_from_db(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT group_id, enabled, note FROM group_config')
        rows = cursor.fetchall()
        self.group_config = {}
        for group_id, enabled, note in rows:
            self.group_config[group_id] = {"enabled": bool(enabled), "note": note}

    def save_group_config_to_db(self):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM group_config')
        # print("正在同步群聊配置到数据库...")
        # print(f"当前群聊配置: {self.group_config}")
        for group_id, cfg in self.group_config.items():
            cursor.execute(
                'INSERT INTO group_config (group_id, enabled, note) VALUES (?, ?, ?)',
                (group_id, int(cfg.get('enabled', 0)), cfg.get('note', ''))
            )
        self.conn.commit()

    async def periodic_sync(self):
        import asyncio
        while True:
            self.save_group_config_to_db()
            await asyncio.sleep(10)  # 每10秒同步一次
            

    def create_table(self):
        cursor = self.conn.cursor()
        cursor.execute(CREATE_TABLE_SQL)
        self.conn.commit()

    name = "GroupChatting"  # 插件名称
    version = "0.0.1"  # 插件版本
    author = "Your Name"  # 插件作者
    info = "这是一个示例插件，用于演示插件系统的基本功能"  # 插件描述
    dependencies = {}  # 插件依赖，格式: {"插件名": "版本要求"}

    @bot.group_event()
    async def on_group_event(self, msg: GroupMessage):
        group_id = str(msg.group_id)
        
        # 跳过其他插件指令
        if msg.raw_message.startswith('/'):
            return
        
        # 自动记录群号和配置
        if group_id not in self.group_config:
            # 自动添加并保存默认配置，默认不开启监听
            self.group_config[group_id] = {
                "enabled": False, "note": "自动添加，默认不监听"}
            print(f"已自动添加群 {group_id} 到监听配置，默认不监听")
        # 仅监听配置中 enabled 为 True 的群才输出日志
        group_cfg = self.group_config[group_id]
        if group_cfg.get("enabled"):
            print(f"群 {group_id} 配置: {group_cfg}")

            group_id = str(msg.group_id)
            user_id = str(msg.user_id)
            now = time.time()
            window = 10  # 时间窗口（秒）
            max_msgs = 5  # 阈值：10秒内超过5条判为刷屏

            # 记录消息时间
            msgs = self.user_messages[group_id][user_id]
            msgs.append(now)
            while msgs and now - msgs[0] > window:
                msgs.popleft()

            if len(msgs) >= max_msgs:
                if str(msg.user_id) != str(config.bt_uin):
                    # 禁言60秒
                    res = await self.api.set_group_ban(msg.group_id, msg.user_id, 60)
                    print(f"禁言结果: {res}")
                    print(f"检测到 {user_id} 在群 {group_id} 刷屏，已禁言 1 分钟")
                    if res.get('status') == 'failed':
                        print(f"禁言失败: {res.get('message', '未知错误')}")
                        await self.api.post_group_msg(
                            msg.group_id, text=f"禁言失败: {res.get('message', '未知错误')}")
                    else:
                        # 发送禁言通知
                        await self.api.post_group_msg(msg.group_id, text=f"检测到刷屏，已禁言 {msg.user_id} 1分钟")
                    msgs.clear()  # 清空，避免重复禁言

            # 复读机逻辑
            last = self.last_message.get(group_id)
            print(f"上条消息: {last}")
            print(f"当前消息: {msg.raw_message}")
            print(f"用户ID: {msg.user_id}, 机器人ID: {config.bt_uin}")
            # 统一类型为字符串再比较，避免类型不一致导致判断失效
            if last is not None and last == msg.raw_message and str(msg.user_id) != str(config.bt_uin):
                await self.api.post_group_msg(msg.group_id, text=msg.raw_message)
            # 记录最新消息
            self.last_message[group_id] = msg.raw_message

            # 意图判断逻辑

    async def add_group(self, msg: GroupMessage):
        args = msg.raw_message.strip().split()
        group_id = args[1] if len(args) >= 2 else str(msg.group_id)
        self.group_config[group_id] = {"enabled": True, "note": "管理员添加"}
        self.save_group_config_to_db()
        await msg.reply(f"已添加群 {group_id} 到监听配置")

    async def remove_group(self, msg: GroupMessage):
        args = msg.raw_message.strip().split()
        group_id = args[1] if len(args) >= 2 else str(msg.group_id)
        if group_id in self.group_config:
            del self.group_config[group_id]
            self.save_group_config_to_db()
            await msg.reply(f"已移除群 {group_id} 的监听配置")
        else:
            await msg.reply(f"群 {group_id} 不在监听配置中")

    @bot.private_event()
    async def on_private_event(self, msg: PrivateMessage):
        # 好友消息事件处理
        if msg.raw_message == "测试":
            await self.api.post_private_msg(msg.user_id, text="GroupChatting 插件测试成功喵")

    async def on_load(self):
        # 插件加载时执行的操作
        print(f"{self.name} 插件已加载")
        print(f"插件版本: {self.version}")

        # 注册动态添加/移除监听群聊的命令
        self.register_admin_func("添加监听群", self.add_group, prefix="/add_group")
        self.register_admin_func(
            "移除监听群", self.remove_group, prefix="/remove_group")
        
        # 注册配置项
        self.register_config("group_config", "群聊监听配置")


