# from ncatbot.core import BotClient

# bot = BotClient()
# api = bot.run_blocking(
#     bt_uin="2737782780",
#     root="512256763",
#     webui_token="wy12345^",
#     enable_webui_interaction=False
# )
# bot.add_private_event_handler(lambda e: e.reply_sync("你好"))
# # bot.exit_()
# # run_blocking 会自动阻塞主线程，无需 sleep 和 exit
# print("Bot 已退出")


# ========= 导入必要模块 ==========
from ncatbot.core import BotClient, GroupMessage, PrivateMessage
from ncatbot.utils import get_log

# ========== 创建 BotClient ==========
bot = BotClient()
_log = get_log()

# ========== 启动 BotClient==========
if __name__ == "__main__":
    bot.run( bt_uin="2212914045",
    root="512256763",
    webui_token="wy12345^",
    enable_webui_interaction=False)
