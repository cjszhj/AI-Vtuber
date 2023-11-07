import logging, os
import threading
import schedule
import random
import asyncio
import traceback
import re

from functools import partial

import pytchat

from utils.common import Common
from utils.config import Config
from utils.logger import Configure_logger
from utils.my_handle import My_handle

"""
	___ _                       
	|_ _| | ____ _ _ __ ___  ___ 
	 | || |/ / _` | '__/ _ \/ __|
	 | ||   < (_| | | | (_) \__ \
	|___|_|\_\__,_|_|  \___/|___/

"""

config = None
common = None
my_handle = None
# last_liveroom_data = None
last_username_list = None

# 点火起飞
def start_server():
    global config, common, my_handle, last_username_list

    config_path = "config.json"

    common = Common()
    config = Config(config_path)
    # 日志文件路径
    log_path = "./log/log-" + common.get_bj_time(1) + ".txt"
    Configure_logger(log_path)

    # 获取 httpx 库的日志记录器
    httpx_logger = logging.getLogger("httpx")
    # 设置 httpx 日志记录器的级别为 WARNING
    httpx_logger.setLevel(logging.WARNING)

    # 最新入场的用户名列表
    last_username_list = [""]

    my_handle = My_handle(config_path)
    if my_handle is None:
        logging.error("程序初始化失败！")
        os._exit(0)


    # 添加用户名到最新的用户名列表
    def add_username_to_last_username_list(data):
        global last_username_list

        # 添加数据到 最新入场的用户名列表
        last_username_list.append(data)
        
        # 保留最新的3个数据
        last_username_list = last_username_list[-3:]


    # 定时任务
    def schedule_task(index):
        logging.debug("定时任务执行中...")
        hour, min = common.get_bj_time(6)

        if 0 <= hour and hour < 6:
            time = f"凌晨{hour}点{min}分"
        elif 6 <= hour and hour < 9:
            time = f"早晨{hour}点{min}分"
        elif 9 <= hour and hour < 12:
            time = f"上午{hour}点{min}分"
        elif hour == 12:
            time = f"中午{hour}点{min}分"
        elif 13 <= hour and hour < 18:
            time = f"下午{hour - 12}点{min}分"
        elif 18 <= hour and hour < 20:
            time = f"傍晚{hour - 12}点{min}分"
        elif 20 <= hour and hour < 24:
            time = f"晚上{hour - 12}点{min}分"


        # 根据对应索引从列表中随机获取一个值
        random_copy = random.choice(config.get("schedule")[index]["copy"])

        # 假设有多个未知变量，用户可以在此处定义动态变量
        variables = {
            'time': time,
            'user_num': "N",
            'last_username': last_username_list[-1],
        }

        # 使用字典进行字符串替换
        if any(var in random_copy for var in variables):
            content = random_copy.format(**{var: value for var, value in variables.items() if var in random_copy})
        else:
            content = random_copy

        data = {
            "platform": "YouTube",
            "username": None,
            "content": content
        }

        logging.info(f"定时任务：{content}")

        my_handle.process_data(data, "schedule")


    # 启动定时任务
    def run_schedule():
        global config

        try:
            for index, task in enumerate(config.get("schedule")):
                if task["enable"]:
                    # logging.info(task)
                    # 设置定时任务，每隔n秒执行一次
                    schedule.every(task["time"]).seconds.do(partial(schedule_task, index))
        except Exception as e:
            logging.error(traceback.format_exc())

        while True:
            schedule.run_pending()
            # time.sleep(1)  # 控制每次循环的间隔时间，避免过多占用 CPU 资源


    # 创建定时任务子线程并启动
    schedule_thread = threading.Thread(target=run_schedule)
    schedule_thread.start()


    # 启动动态文案
    async def run_trends_copywriting():
        global config

        try:
            if False == config.get("trends_copywriting", "enable"):
                return
            
            logging.info(f"动态文案任务线程运行中...")

            while True:
                # 文案文件路径列表
                copywriting_file_path_list = []

                # 获取动态文案列表
                for copywriting in config.get("trends_copywriting", "copywriting"):
                    # 获取文件夹内所有文件的文件绝对路径，包括文件扩展名
                    for tmp in common.get_all_file_paths(copywriting["folder_path"]):
                        copywriting_file_path_list.append(tmp)

                    # 是否开启随机播放
                    if config.get("trends_copywriting", "random_play"):
                        random.shuffle(copywriting_file_path_list)

                    # 遍历文案文件路径列表  
                    for copywriting_file_path in copywriting_file_path_list:
                        # 获取文案文件内容
                        copywriting_file_content = common.read_file_return_content(copywriting_file_path)
                        # 是否启用提示词对文案内容进行转换
                        if copywriting["prompt_change_enable"]:
                            data_json = {
                                "user_name": "trends_copywriting",
                                "content": copywriting["prompt_change_content"] + copywriting_file_content
                            }

                            # 调用函数进行LLM处理，以及生成回复内容，进行音频合成，需要好好考虑考虑实现
                            data_json["content"] = my_handle.llm_handle(config.get("chat_type"), data_json)
                        else:
                            data_json = {
                                "user_name": "trends_copywriting",
                                "content": copywriting_file_content
                            }

                        # 空数据判断
                        if data_json["content"] != None and data_json["content"] != "":
                            # 发给直接复读进行处理
                            my_handle.reread_handle(data_json)

                            await asyncio.sleep(config.get("trends_copywriting", "play_interval"))
        except Exception as e:
            logging.error(traceback.format_exc())


    # 创建动态文案子线程并启动
    threading.Thread(target=lambda: asyncio.run(run_trends_copywriting())).start()

    try:
        try:
            video_id = config.get("room_display_id")
        except Exception as e:
            logging.error("获取直播间号失败！\n{0}".format(e))

        live = pytchat.create(video_id=video_id)
        while live.is_alive():
            try:
                for c in live.get().sync_items():
                    # 过滤表情包
                    chat_raw = re.sub(r':[^\s]+:', '', c.message)
                    chat_raw = chat_raw.replace('#', '')
                    if chat_raw != '':
                        # chat_author makes the chat look like this: "Nightbot: Hello". So the assistant can respond to the user's name
                        # chat = '[' + c.author.name + ']: ' + chat_raw
                        # logging.info(chat)

                        content = chat_raw  # 获取弹幕内容
                        user_name = c.author.name  # 获取发送弹幕的用户昵称

                        logging.info(f"[{user_name}]: {content}")

                        data = {
                            "platform": "YouTube",
                            "username": user_name,
                            "content": content
                        }

                        my_handle.process_data(data, "comment")
                        
                    # time.sleep(1)
            except Exception as e:
                logging.error("Error receiving chat: {0}".format(e))
    except KeyboardInterrupt:
        logging.warning('程序被强行退出')
    finally:
        logging.warning('关闭连接...')
        os._exit(0)


if __name__ == '__main__':
    start_server()