from ncatbot.plugin import BasePlugin, CompatibleEnrollment
from ncatbot.core.message import GroupMessage, PrivateMessage
from ncatbot.utils.logger import get_log

bot = CompatibleEnrollment  # 兼容回调函数注册器
_log = get_log()


class TestPlugin(BasePlugin):
    name = "TestPlugin"  # 插件名称
    version = "0.0.7"  # 插件版本

    @bot.group_event()
    async def on_group_event(self, msg: GroupMessage):
        # 定义的回调函数
        _log.info(f"收到群聊消息: {msg.raw_message}")
        
        if msg.raw_message == "测试ocr":
            _log.info("测试OCR功能")
            url = "https://i0.hdslb.com/bfs/archive/c8fd97a40bf79f03e7b76cbc87236f612caef7b2.png"
            res = await self.api.ocr_image(url)
            _log.info(f"OCR 结果: {res}")
            msg.reply(f"OCR 结果: {res}")
            
        
        if msg.raw_message == "测试禁言功能":
            res = await self.api.set_group_ban(msg.group_id, msg.user_id, duration=60)
            _log.info(f"禁言结果: {res}") 
            # 禁言成功后回复消息  {'status': 'failed', 'retcode': 1200, 'data': None, 'message': 'cannot ban owner', 'wording': 'cannot ban owner', 'echo': 1752566982}
            if res.get('status') == 'failed':
                await msg.reply("禁言失败: 狗管理太厉害了喵，哈气哈气哇～")
                return
            await msg.reply("测试禁言功能已触发，用户将被禁言 60 秒哦喵～")        
        if msg.raw_message == "测试@功能":
            await msg.reply("测试@功能已触发，功能正常运行！")
            await self.api.post_group_msg(msg.group_id, text="测试成功喵~", at="all")
        if msg.raw_message == "测试":
            await self.api.post_group_msg(msg.group_id, text="Ncatbot 插件(3.8.x)群聊测试成功喵~")
        if msg.raw_message == "获取群 @全体成员 剩余次数":
            _log.info(f"获取群 {msg.group_id} @全体成员 剩余次数")
            print("获取群 @全体成员 剩余次数")
            result =  await self.api.get_group_at_all_remain(msg.group_id)
            if result:
                await msg.reply(f"获取群 @全体成员 剩余次数: {result}")
        if msg.raw_message == "发送群公告":
            await self.api.send_group_notice(msg.group_id, content="这是群公告的内容喵～")
        if msg.raw_message == "测试获取头像":
            _log.info(f"获取头像: {msg.user_id}")
            print("获取头像")
            url = "https://q1.qlogo.cn/g?b=qq&nk={}&s=640".format(msg.user_id)
            result = url
            if result:
                await msg.reply(f"获取头像成功, 头像链接: {result}")
                await self.api.post_group_msg(msg.group_id, at=msg.user_id,text="[CQ:image,summary=[图片],url={}]".format(result))
                
                
                
            else:
                await msg.reply("获取头像失败喵～")
        if msg.raw_message == "获取AI语音人物":
            result = await self.api.get_ai_characters(msg.group_id, "1")
            # 解析并保存数据结构
            voice_characters = []
            data = result.get('data', []) if isinstance(result, dict) else []
            for item in data:
                type_name = item.get('type', '')
                for char in item.get('characters', []):
                    voice_characters.append({
                        'type': type_name,
                        'character_id': char.get('character_id', ''),
                        'character_name': char.get('character_name', '')
                    })
            # 格式化输出
            if voice_characters:
                output = '\n'.join([
                    f"{c['type']} | {c['character_id']} | {c['character_name']}" for c in voice_characters
                ])
            else:
                output = "未获取到语音人物数据"
            print("格式化AI语音人物:", output)
            await msg.reply(output)

    @bot.private_event()
    async def on_private_message(self, msg: PrivateMessage):
        _log.info(f"收到私聊消息: {msg.raw_message}")
        if msg.raw_message == "测试":
            await msg.reply("NcatBot 插件私聊测试成功喵~")

    async def on_load(self):
        # 插件加载时执行的操作, 可缺省
        print(f"{self.name} 插件已加载")
        print(f"插件版本: {self.version}")
        self.register_config("info", "测试配置项")
        self.register_user_func("测试用户功能", self.test_user_func, prefix="/tu")
        self.register_admin_func("测试管理员功能", self.test_admin_func, prefix="/ta")

    def test_user_func(self, msg: PrivateMessage):
        msg.reply_sync(text="用户功能:" + self.data['config']['info'])

    async def test_admin_func(self, msg: GroupMessage):
        await msg.reply(text="管理员功能(测试热重载):" + self.data['config']['info'])

    async def on_unload(self):
        print(f"{self.name} 插件已卸载")
