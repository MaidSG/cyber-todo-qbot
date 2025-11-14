import requests
from bs4 import BeautifulSoup
import time
import sqlite3
from datetime import datetime

# --- 配置区 ---
TARGET_URL = "https://tushare.pro/news/fenghuang"
DB_FILE = "./db/tushare_news.db"  # 数据库文件路径
SCRAPE_INTERVAL_MINUTES = 10  # 抓取间隔时间（分钟）

# --- 数据库操作 ---

def setup_database():
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

def insert_news(news_item):
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

def scrape_and_save():
    """
    执行一次新闻抓取和存储操作。
    """
    print(f"\n--- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 开始抓取最新新闻 ---")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    cookies = {
        'uid': '2|1:0|10:1754984931|3:uid|8:ODI5NjU2|078218cb30a6e0ee27bd782ac1a392a47f72507e41aa6453504df0d8d7d2eeeb',
        'username': '2|1:0|10:1754984931|8:username|8:d2FuZ3l1|d464d8a61c8806d7e9416e54d8e185f257dc84b32cf59c2e650a8dbb58e55de0'
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
            if insert_news(news_item):
                new_items_count += 1
        
        print(f"抓取完成，共找到 {len(news_elements)} 条，处理了前 10 条，新增 {new_items_count} 条。")

    except requests.exceptions.RequestException as e:
        print(f"错误: 请求网址时发生错误: {e}")
    except Exception as e:
        print(f"发生未知错误: {e}")

# --- 主程序入口 ---

if __name__ == "__main__":
    # 1. 启动时，先初始化数据库
    setup_database()
    
    # 2. 进入无限循环，定时执行任务
    while True:
        try:
            scrape_and_save()
            sleep_seconds = SCRAPE_INTERVAL_MINUTES * 60
            print(f"--- 本轮任务结束，休眠 {SCRAPE_INTERVAL_MINUTES} 分钟... (按 Ctrl+C 停止) ---")
            time.sleep(sleep_seconds)
        except KeyboardInterrupt:
            print("\n程序被用户手动停止。")
            break
        except Exception as e:
            print(f"主循环发生严重错误: {e}")
            print("将在 60 秒后重试...")
            time.sleep(60)