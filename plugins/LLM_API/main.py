
from ncatbot.plugin import BasePlugin, CompatibleEnrollment, Event
from ncatbot.core import GroupMessage, PrivateMessage
import asyncio
import httpx
import openai
from concurrent.futures import ThreadPoolExecutor
from ncatbot.utils import get_log, config
import sqlite3


DEFAULT_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_API = "sk-9167011d9cca455f8b25401328d31f6a"
DEFAULT_MODEL = "deepseek-chat"

bot = CompatibleEnrollment  # 兼容回调函数注册器

LOG = get_log("LLM_API")  # 获取日志记录器


DB_PATH = './db/llm_api.db'


CREATE_TABLE_SQL = '''
CREATE TABLE IF NOT EXISTS user_level (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 0,
    exp INTEGER NOT NULL DEFAULT 0,
    greeting_status INTEGER DEFAULT 0,  -- 今日问候  使用位图存储  早安 午安 晚安
    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(group_id, user_id)
);
'''


class LLM_API(BasePlugin):

    @staticmethod
    async def get_greet_flag(group_id: str, user_id: str):
        """查询今日问候flag，3比特位分别表示早安、午安、晚安"""
        import aiosqlite
        from datetime import datetime
        DB_PATH = './db/llm_api.db'
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_greet (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    flag INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(group_id, user_id, date)
                );
            ''')
            async with conn.execute('SELECT flag FROM user_greet WHERE group_id=? AND user_id=? AND date=?', (group_id, user_id, today)) as cursor:
                row = await cursor.fetchone()
            if row:
                return row[0]
            else:
                return 0

    @staticmethod
    async def update_greet_flag(group_id: str, user_id: str, flag_bit: int):
        """设置今日问候flag的某一比特位（0:早安, 1:午安, 2:晚安）为1"""
        import aiosqlite
        from datetime import datetime
        DB_PATH = './db/llm_api.db'
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_greet (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    flag INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(group_id, user_id, date)
                );
            ''')
            # 查询当前flag
            async with conn.execute('SELECT flag FROM user_greet WHERE group_id=? AND user_id=? AND date=?', (group_id, user_id, today)) as cursor:
                row = await cursor.fetchone()
            if row:
                old_flag = row[0]
                new_flag = old_flag | (1 << flag_bit)
                await conn.execute('UPDATE user_greet SET flag=? WHERE group_id=? AND user_id=? AND date=?', (new_flag, group_id, user_id, today))
            else:
                new_flag = (1 << flag_bit)
                await conn.execute('INSERT INTO user_greet (group_id, user_id, date, flag) VALUES (?, ?, ?, ?)', (group_id, user_id, today, new_flag))
            await conn.commit()

    @classmethod
    async def add_exp(cls, api, group_id: str, user_id: str, exp: int):
        """增加经验并自动升级，升级时异步通知"""
        DB_PATH = './db/llm_api.db'
        import aiosqlite
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_level (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    level INTEGER NOT NULL DEFAULT 1,
                    exp INTEGER NOT NULL DEFAULT 0,
                    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(group_id, user_id)
                );
            ''')
            async with conn.execute('SELECT exp, level FROM user_level WHERE group_id=? AND user_id=?', (group_id, user_id)) as cursor:
                row = await cursor.fetchone()
            notify = False
            old_level = 1
            if row:
                old_exp, old_level = row
                new_exp = old_exp + exp
                new_level = old_level
                # 升级规则：每100经验升一级
                while new_exp >= (new_level * 100):
                    new_exp -= new_level * 100
                    new_level += 1
                if new_level > old_level:
                    notify = True
                await conn.execute('UPDATE user_level SET exp=?, level=?, last_update=CURRENT_TIMESTAMP WHERE group_id=? AND user_id=?', (new_exp, new_level, group_id, user_id))
            else:
                new_level = 1
                new_exp = exp
                # 升级规则：每100经验升一级
                while new_exp >= (new_level * 100):
                    new_exp -= new_level * 100
                    new_level += 1
                notify = new_level > 1
                await conn.execute('INSERT INTO user_level (group_id, user_id, exp, level) VALUES (?, ?, ?, ?)', (group_id, user_id, new_exp, new_level))
            await conn.commit()
            if notify:
                # 发送升级通知
                if api:
                    try:
                        await api.post_group_msg(group_id, text=f"恭喜 <@{user_id}> 升级到 Lv.{new_level}！")
                    except Exception as e:
                        print(f"升级通知发送失败: {e}")

    @classmethod
    async def sub_exp(cls, api, group_id: str, user_id: str, exp: int):
        """减少经验并自动降级，降级时异步通知，经验最小为0，等级最小为1"""
        DB_PATH = './db/llm_api.db'
        import aiosqlite
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_level (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    level INTEGER NOT NULL DEFAULT 1,
                    exp INTEGER NOT NULL DEFAULT 0,
                    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(group_id, user_id)
                );
            ''')
            async with conn.execute('SELECT exp, level FROM user_level WHERE group_id=? AND user_id=?', (group_id, user_id)) as cursor:
                row = await cursor.fetchone()
            notify = False
            old_level = 1
            if row:
                old_exp, old_level = row
                new_exp = max(0, old_exp - exp)
                new_level = old_level
                # 降级规则：如果经验低于当前等级所需，降级
                while new_level > 1 and new_exp < ((new_level - 1) * 100):
                    new_level -= 1
                    new_exp += new_level * 100
                    if new_exp > (new_level * 100 - 1):
                        new_exp = new_level * 100 - 1
                if new_level < old_level:
                    notify = True
                await conn.execute('UPDATE user_level SET exp=?, level=?, last_update=CURRENT_TIMESTAMP WHERE group_id=? AND user_id=?', (new_exp, new_level, group_id, user_id))
            else:
                await conn.execute('INSERT INTO user_level (group_id, user_id, exp, level) VALUES (?, ?, ?, ?)', (group_id, user_id, 0, 1))
            await conn.commit()
            if notify:
                # 发送降级通知
                if api:
                    try:
                        await api.post_group_msg(group_id, text=f"<@{user_id}> 降级到 Lv.{new_level}，请继续努力喵~")
                    except Exception as e:
                        print(f"降级通知发送失败: {e}")

    async def update_voice_characters(self, raw_result):
        """
        解析AI语音人物接口返回结果，并注册到配置项 voice_characters
        """
        voice_characters = []
        data = raw_result.get('data', []) if isinstance(
            raw_result, dict) else []
        for item in data:
            type_name = item.get('type', '')
            for char in item.get('characters', []):
                voice_characters.append({
                    'type': type_name,
                    'character_id': char.get('character_id', ''),
                    'character_name': char.get('character_name', '')
                })
        self.data['config']['voice_characters'] = voice_characters
        return voice_characters

    async def call_llm_simple(self, user_message, system_prompt, max_tokens, temperature):
        history = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        event = Event("LLM_API.call_llm", {
            "history": history,
            "max_tokens": max_tokens,
            "temperature": temperature
        })
        results = await self.publish_async(event)
        if results and isinstance(results, list):
            result = results[0]
            if result.get("status") == 200:
                return result.get("text", "")
            else:
                return f"[LLM错误]{result.get('error', '') or '未知错误'}"
        return "[LLM调用失败]"
    name = "LLM_API"  # 插件名称
    version = "0.0.1"  # 插件版本

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_trigger_times = {}  # 记录用户触发时间

    async def on_load(self):
        print(f"{self.name} 插件已加载")
        print(f"插件版本: {self.version}")
        # 自动安装 aiosqlite 依赖
        try:
            import aiosqlite
        except ImportError:
            import sys
            import subprocess
            print("[LLM_API] 正在自动安装 aiosqlite 依赖...")
            subprocess.check_call(
                [sys.executable, '-m', 'pip', 'install', 'aiosqlite'])
            import aiosqlite

        self.register_config("url", DEFAULT_URL)
        self.register_config("api", DEFAULT_API)
        self.register_config("model", DEFAULT_MODEL)  # 注册三个配置项
        self.register_handler("LLM_API.main", self.main)  # 注册事件(Event)处理器
        # 注册AI 语音标识
        self.register_config("voice_characters", [])
        # 可选：启动时自动获取并注册语音角色（需有api对象和群号）
        # 示例：
        result = await self.api.get_ai_characters("375157283", "1")
        await self.update_voice_characters(result)

        # 注册一个管理员功能, 需要提权以便在普通群聊中触发
        self.register_admin_func(
            "test", self.test, prefix="/tllma", permission_raise=True)
        # 注册标准能力事件接口
        self.register_handler("LLM_API.call_llm", self.call_llm)
        # 注册插件能力
        self.register_user_func(
            "喵喵智能应答",
            self.normal_chat,
            filter=lambda msg: msg.raw_message.strip().startswith("喵喵"),
            description="喵喵问候",
            examples=["喵喵你好", "喵喵在吗"],
            tags=["user"]
        )
        self.register_user_func(
            "喵喵日常问候",
            self.daily_reply,
            filter=lambda msg: msg.raw_message.strip().startswith(
                "[CQ:at,qq=2737782780]") or msg.raw_message.strip().startswith("@喵喵"),
            description="喵喵日常问候",
            examples=["@喵喵"],
            tags=["user"]
        )

    async def daily_reply(self, msg: PrivateMessage | GroupMessage):
        # 只在消息以指定前缀开头时触发
        print(f"消息以指定前缀开头时触发调试 收到日常问候消息: {msg.raw_message}")
        group_id = str(msg.group_id) if hasattr(msg, 'group_id') and msg.group_id else None
        user_id = str(msg.user_id)

        if msg.raw_message.strip().startswith("[CQ:at,qq=2737782780]") or msg.raw_message.strip().startswith("@喵喵"):
            if user_id == str(config.bt_uin):
                return

            # 判断用户等级 如果没，就插入等级数据
            user_level = self.get_user_level(group_id, user_id) if group_id else 1
            print(f"用户等级: {user_level}")

            # 意图判断
            intent_prompt = (
                "你是一个日漫猫娘风格的AI助手，名字叫‘喵喵’。请根据用户消息判断以下三种情况，并只回复指定内容：\n"
                "1. 日常问候打卡：如果用户发送的消息中包含‘早安’、‘午安’或‘晚安’，或者类似的含义的消息，判定为 日常问候打卡，同时你请只回复 ‘早安’、‘午安’或‘晚安’ 三种情况中的一种\n"
                "如果用户消息同时包含多个问候（如‘早安午安晚安’，‘早早午午晚晚安’），或表达不清、捣乱、无关内容，请只回复‘其他问候’。"
                "2. 通用聊天：如果用户发送的消息不符合日常问候打卡的条件，判定为 通用聊天\n"
                "3. 任务场景：如果用户发送的消息包含‘开启任务’、‘开启任务场景’等关键词，判定为 任务场景\n"
                "如果用户消息包含‘查看喵力值’、‘开启任务场景’等关键词，或直接问 等级有关的不太像通用聊天场景的请回复‘任务场景’\n"
            )

            try:
                intent = await self.call_llm_simple(msg.raw_message, intent_prompt, max_tokens=4096, temperature=0.1)
                intent = intent.strip().replace('\n', '').replace('\r', '')
                print(f"意图判断结果: {intent}")
            except Exception as e:
                print(f"[调试] 意图判断 LLM 异常: {e}")
                intent = ""

            # 今日问候判断 早安 午安 晚安
            if group_id and user_id != str(config.bt_uin) and (intent.endswith("早安") or intent.endswith("午安") or intent.endswith("晚安")):
                print(f"收到日常问候打卡消息: {msg.raw_message} 来自: {user_id}")
                from datetime import datetime
                now = datetime.now()
                hour = now.hour
                greet_flag = await self.get_greet_flag(group_id, user_id)
                correct = False
                flag_bit = None
                # 早安 5:00-10:59
                if msg.raw_message.strip().endswith("早安"):
                    flag_bit = 0
                    if 5 <= hour < 11:
                        correct = True
                # 午安 11:00-17:59
                elif msg.raw_message.strip().endswith("午安"):
                    flag_bit = 1
                    if 11 <= hour < 18:
                        correct = True
                # 晚安 18:00-4:59
                elif msg.raw_message.strip().endswith("晚安"):
                    flag_bit = 2
                    if hour >= 18 or hour < 5:
                        correct = True
                if greet_flag & (1 << flag_bit):
                    await msg.reply("今日已打卡喵~")
                else:
                    await self.update_greet_flag(group_id, user_id, flag_bit)
                    if correct:
                        await msg.reply(["早安喵~", "午安喵~", "晚安喵~"][flag_bit])
                        await self.add_exp(self.api, group_id, user_id, 10)
                    else:
                        await msg.reply("时段不对喵~要扣经验了喵！")
                        await self.sub_exp(self.api, group_id, user_id, 5)
                return

            # 其他问候
            if intent == "其他问候":
                print(f"收到其他问候消息: {msg.raw_message} 来自: {user_id}")
                if user_id == str(config.bt_uin):
                    return
                llm_input = f"喵喵，{msg.raw_message}"
                res = await self.call_llm_simple(
                    llm_input,
                    ("你是一个日漫猫娘风格的AI助手，名字叫‘喵喵’。请用可爱、活泼、治愈的语气与用户互动。"
                     "请根据用户消息内容，进行回答，如果用户是意义不明的问候，请指引回复用户和你进行正常的早中晚问候。"),
                    max_tokens=8192,
                    temperature=1.3
                )
                # 优先群聊回复，否则私聊
                if group_id:
                    await self.api.post_group_msg(group_id, text=res)
                else:
                    await self.api.post_group_msg(user_id, text=res)
                return

            # 任务场景
            if intent == "任务场景":
                print(f"收到任务场景消息: {msg.raw_message} 来自: {user_id}")
                if user_id == str(config.bt_uin):
                    return
                get_user_info = self.get_user_info(group_id, user_id)
                llm_input = f"喵喵，{msg.raw_message}，当前用户信息：{get_user_info}"
                res = await self.call_llm_simple(
                    llm_input,
                    ("你是一个日漫猫娘风格的AI助手，名字叫‘喵喵’。请用可爱、活泼、治愈的语气与用户互动。"
                    "请根据用户消息内容，进行回答，如果用户是查询等级、经验等信息，请回复用户当前等级和经验值。"
                    "等级和经验值 有关的信息都叫 主人亲密度（亲密度等级/亲密度值）喵力值（喵力等级/喵力点数）"
                    "如果用户询问有哪些等级，请回复以下等级信息："
                    "和喵喵打招呼成功将10增加经验值，经验值满100点升级一次，如果错误的打招呼将扣除5点经验值。，和喵喵聊天将增加1点经验值"
                    "注意聊天只增加一点无奖励机制"
                    "等级强制使用进行回复：Lv.1 → ‘Lv.1 萌新’ Lv.2 → ‘Lv.2 冒险者’ Lv.3 → ‘Lv.3 守护者’ Lv.4 → ‘Lv.4 精英’ Lv.5 → ‘Lv.5 喵神’"
                    ),
                    max_tokens=8192,
                    temperature=1.3
                )
                if group_id:
                    await self.api.post_group_msg(group_id, text=res)
                else:
                    await self.api.post_group_msg(user_id, text=res)
                return

            try:
                # 拼接原始消息内容，去掉前缀
                user_content = msg.raw_message
                get_log("LLM_API").info(f"收到日常问候消息: {msg}")
                if not user_content:
                    user_content = "你好！"
                llm_input = f"喵喵，{user_content}"
                res = await self.call_llm_simple(
                    llm_input,
                    "你是一个日漫猫娘风格的AI助手，名字叫‘喵喵’。请用可爱、活泼、治愈的语气与用户互动。",
                    max_tokens=8192,
                    temperature=1.3
                )
                if group_id:
                    await self.api.post_group_msg(group_id, text=res)
                else:
                    await self.api.post_group_msg(user_id, text=res)
                await self.add_exp(self.api, group_id, user_id, 1)
            except Exception as e:
                LOG.error(f"调用 LLM 异常: {e}")
                await msg.reply("抱歉，喵喵现在有点忙，请稍后再试~")

    async def call_llm(self, event: Event):
        """
        标准事件接口：LLM_API.call_llm
        参数：event.data = {
            'history': [...],
            'max_tokens': int, # 可选
            'temperature': float # 可选
        }
        返回：event.add_result({ 'text': str, 'status': int, 'error': str })
        """
        data = event.data
        history = data.get("history", [])
        max_tokens = data.get("max_tokens", 4096)
        temperature = data.get("temperature", 0.7)
        # 复用 main 逻辑
        url = self.data['config']["url"]
        api = self.data['config']["api"]
        model = self.data['config']["model"]
        # 判断 deepseek
        if "deepseek" in url or "deepseek" in model:
            headers = {
                "Authorization": f"Bearer {api}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model,
                "messages": history,
                "max_tokens": max_tokens,
                "temperature": temperature
            }
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    result = resp.json()
                    text = result["choices"][0]["message"]["content"] if result.get(
                        "choices") else ""
                    print(f"[调试] deepseek 返回: {text}")
                    event.add_result({
                        "text": text,
                        "status": 200,
                        "error": ""
                    })
            except Exception as e:
                event.add_result({
                    "text": "",
                    "status": 500,
                    "error": f"deepseek调用失败: {e}"
                })
            return
            try:
                openai.api_key = api
                openai.api_base = url
                completion = await openai.ChatCompletion.acreate(
                    model=model,
                    messages=history,
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                text = completion["choices"][0]["message"]["content"]
                event.add_result({
                    "text": text,
                    "status": 200,
                    "error": ""
                })
            except Exception as e:
                event.add_result({
                    "text": "",
                    "status": 500,
                    "error": f"OpenAI调用失败: {e}"
                })
            return
        # 兜底
        event.add_result({
            "text": "未识别的模型或API类型",
            "status": 400,
            "error": "请检查url/model配置"
        })

    async def test(self, message: PrivateMessage):
        result = (await self.publish_async(Event("LLM_API.main", {
            "history": [
                {
                    "role": "system",
                    "content": "系统提示内容"
                },
                {
                    "role": "user",
                    "content": "用户输入内容"
                },
            ],  # 提示信息
            "max_tokens": 4096,  # 最大长度
            "temperature": 0.7  # 温度, 0-1, 越大越随机
        })))[0]
        await message.reply(text=result["text"] + result['error'])

    async def normal_chat(self, msg: PrivateMessage | GroupMessage):

        if str(msg.user_id) == str(config.bt_uin):
            return
        
        if msg.raw_message.strip().startswith("[CQ:at,qq=2737782780]") or msg.raw_message.strip().startswith("@喵喵"):
            return

        import random
        import asyncio
        if not self.can_trigger_user(msg):
            reply = random.choice(self.text_limit_replies)
            try:
                await asyncio.sleep(3)
                await msg.reply(reply)
            except Exception as e:
                print(f"[调试] 限制回复异常: {e}")
            return
        print(f"收到消息: {msg.raw_message} 来自: {msg.user_id}")
        # 判断用户等级 如果没差到，就插入等级数据
        user_level = self.get_user_level(
            msg.group_id, msg.user_id) if hasattr(msg, 'group_id') else 1
        print(f"用户等级: {user_level}")

        if hasattr(msg, 'group_id') and msg.group_id:
            intent_prompt = (
                "你是一个日漫猫娘风格的AI助手，名字叫‘喵喵’。请根据用户消息判断以下三种情况，并只回复指定内容：\n"
                "1. 如果用户明确要求你‘语音回复’，如包含‘语音回复’‘请说话’‘你说’‘喵喵你说xxx’等表达，请只回复：‘语音’。\n"
                "2. 如果用户称呼你为‘喵喵’并正常交流，但没有语音相关要求，请只回复：‘文本’。\n"
                "3. 如果用户没有完整称呼‘喵喵’，或只是简单‘喵’，请只回复：‘非法指令’。\n"
                "注意：只回复上述三种之一，不要输出其它内容，不要解释、不用补充说明。"
            )
            try:
                intent = await self.call_llm_simple(msg.raw_message, intent_prompt, max_tokens=16, temperature=0.1)
                intent = intent.strip().replace('\n', '').replace('\r', '')
                print(f"意图判断结果: {intent}")
            except Exception as e:
                print(f"[调试] 意图判断 LLM 异常: {e}")
                intent = ""
            if intent == "非法指令":
                try:
                    short_voice = await self.call_llm_simple(msg.raw_message, short_voice_prompt, max_tokens=80, temperature=0.9)
                    short_voice = short_voice.strip().replace(
                        '\n', '').replace('\r', '')[:80]
                    await self.api.send_group_ai_record(msg.group_id, "lucy-voice-female1", short_voice)
                except Exception as e:
                    print(f"[调试] 语音 LLM/发送/记录异常: {e}")
                return

            if intent == "语音":
                short_voice_prompt = (
                    "你是一个日漫猫娘风格的AI助手，名字叫‘喵喵’。\n"
                    "请用口语化、自然、亲切的方式回答用户问题，内容可以详细、有逻辑，但表达要像真实说话一样，避免书面语。\n"
                    "回复要有猫娘特色，适当加入拟声词（如喵~、呀~、呜呜~等）、感情符号（如~、☆、>_<等），让语音更有表现力和陪伴感。\n"
                    "不要出现括号或动作描述，不要解释自己的身份。\n"
                    "可以主动关心用户、表达情感、撒娇卖萌，但不要涉及敏感、负面或不适宜的话题。\n"
                    "只输出一段语音内容，不要补充其它说明。"
                )
                try:
                    short_voice = await self.call_llm_simple(msg.raw_message, short_voice_prompt, max_tokens=4096, temperature=1.5)
                    short_voice = short_voice.strip().replace(
                        '\n', '').replace('\r', '')[:4096]
                    await self.api.send_group_ai_record(msg.group_id, "lucy-voice-female1", short_voice)
                except Exception as e:
                    print(f"[调试] 语音 LLM/发送/记录异常: {e}")
                return
        try:
            immersive_prompt = (
                "你是一个日漫猫娘风格的AI助手，名字叫‘喵喵’。\n"
                "请用可爱、活泼、治愈的语气与用户互动，回复内容要有猫娘特色，适当加入拟声词（如喵~、呀~、呜呜~等）、感情符号（如~、☆、>_<等），让用户感受到陪伴和温暖。\n"
                "可以主动关心用户、表达情感、撒娇卖萌，但不要涉及敏感、负面或不适宜的话题。\n"
                "回复内容避免重复和无意义的词语。\n"
                "不要解释自己的身份，不要输出括号或动作描述，以及颜文字等不利于用于语音输出的话，只输出一句沉浸式回复。"
            )
            res = await self.call_llm_simple(msg.raw_message, immersive_prompt, max_tokens=4096, temperature=1.3)
            await self.api.post_group_msg(
                msg.group_id if hasattr(msg, 'group_id') else msg.user_id,
                text=res
            )
        except Exception as e:
            print(f"[调试] 文本 LLM/发送/记录异常: {e}")

    async def main(self, event: Event):
        data = event.data
        url = self.data['config']["url"]
        api = self.data['config']["api"]
        model = self.data['config']["model"]
        history = data.get("history", [])
        max_tokens = data.get("max_tokens", 4096)
        temperature = data.get("temperature", 0.7)

        # 判断 deepseek
        if "deepseek" in url or "deepseek" in model:
            headers = {
                "Authorization": f"Bearer {api}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model,
                "messages": history,
                "max_tokens": max_tokens,
                "temperature": temperature
            }
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    result = resp.json()
                    text = result["choices"][0]["message"]["content"] if result.get(
                        "choices") else ""
                    event.add_result({
                        "text": text,
                        "status": 200,
                        "error": ""
                    })
            except Exception as e:
                event.add_result({
                    "text": "",
                    "status": 500,
                    "error": f"deepseek调用失败: {e}"
                })
            return

        # 兜底
        event.add_result({
            "text": "未识别的模型或API类型",
            "status": 400,
            "error": "请检查url/model配置"
        })

    async def on_unload(self):
        print(f"{self.name} 插件已卸载")

    # 辅助函数

    def can_trigger_user(self, msg, window=30, limit=2):
        import time
        now = time.time()
        if hasattr(msg, 'group_id') and msg.group_id:
            key = (msg.group_id, msg.user_id)
        else:
            key = (msg.user_id, msg.user_id)
        times = self.user_trigger_times.get(key, [])
        times = [t for t in times if now - t < window]
        if len(times) >= limit:
            self.user_trigger_times[key] = times
            return False
        times.append(now)
        self.user_trigger_times[key] = times
        return True

    # 用户等级查询与自动插入

    def get_user_level(self, group_id: str, user_id: str) -> int:
        """
        获取用户等级，如果没有则插入默认等级1并返回1。
        """
        DB_PATH = './db/llm_api.db'
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_level (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                level INTEGER NOT NULL DEFAULT 1,
                exp INTEGER NOT NULL DEFAULT 0,
                last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id, user_id)
            );
        ''')
        cursor.execute(
            'SELECT level FROM user_level WHERE group_id=? AND user_id=?', (group_id, user_id))
        row = cursor.fetchone()
        if row:
            level = row[0]
        else:
            cursor.execute(
                'INSERT INTO user_level (group_id, user_id, level) VALUES (?, ?, ?)', (group_id, user_id, 1))
            conn.commit()
            level = 1
        conn.close()
        return level
    
    
    def get_user_info(self, group_id: str, user_id: str):
        """
        获取用户信息，包括等级和经验。
        """
        DB_PATH = './db/llm_api.db'
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_level (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                level INTEGER NOT NULL DEFAULT 1,
                exp INTEGER NOT NULL DEFAULT 0,
                last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id, user_id)
            );
        ''')
        cursor.execute(
            'SELECT level, exp FROM user_level WHERE group_id=? AND user_id=?', (group_id, user_id))
        row = cursor.fetchone()
        if row:
            level, exp = row
        else:
            level, exp = 1, 0
            cursor.execute(
                'INSERT INTO user_level (group_id, user_id, level, exp) VALUES (?, ?, ?, ?)', (group_id, user_id, level, exp))
            conn.commit()
        conn.close()
        return {"level": level, "exp": exp}


# 限制时的回复池
    text_limit_replies = [
        "欸欸欸，主人太积极了啦，给我一点时间缓缓嘛～(〃'▽'〃)",
        "主人稍等一下哦，喵喵要整理下裙摆再来陪你！(≧∇≦)/",
        "哎呀，脑袋有点转不过来了，主人可以再等一小会吗？(>_<)ゞ",
        "等一下啦，主人太可爱了，喵喵要补充点能量再继续陪你！(=^･ω･^=)",
        "主人，喵喵现在有点晕乎乎的，等会再来找我玩吧~(｡•́︿•̀｡)",
        "呜呜，爪子都要打结了，主人耐心等一下嘛！(つд⊂)",
        "主人，喵喵要去喝点牛奶，马上回来陪你哦！(๑•̀ㅂ•́)و✧",
        "稍微等一下啦，喵喵要整理下发卡再来陪你！(☆▽☆)",
        "主人，喵喵现在有点忙不过来，等会再来找我玩吧~ (>ω<)"
    ]
    voice_limit_replies = [
        "欸欸欸，主人太积极了啦，给我一点时间缓缓嘛～",
        "主人稍等一下哦，喵喵要整理下裙摆再来陪你！",
        "哎呀，脑袋有点转不过来了，主人可以再等一小会吗？",
        "等一下啦，主人太可爱了，喵喵要补充点能量再继续陪你！",
        "主人，喵喵现在有点晕乎乎的，等会再来找我玩吧~",
        "呜呜，爪子都要打结了，主人耐心等一下嘛！",
        "主人，喵喵要去喝点牛奶，马上回来陪你哦！",
        "稍微等一下啦，喵喵要整理下发卡再来陪你！",
        "主人，喵喵现在有点忙不过来，等会再来找我玩吧~"
    ]
