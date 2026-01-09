import re
import json
import time
import base64
import imaplib
import email
import logging
import sys
import os
os.environ["OMP_NUM_THREADS"] = "1"  
os.environ["ONNX_RUNTIME_NUM_THREADS"] = "1" 
import ddddocr
import requests
from bs4 import BeautifulSoup
from email.header import decode_header
import datetime
from datetime import datetime, timedelta
import pytz
from telegram import Bot
import aiohttp
import asyncio
import signal
import psutil  # For CPU, memory, and disk monitoring
import platform  # For CPU model detection


logging.getLogger("ddddocr").setLevel(logging.WARNING)


# 修改日志文件路径，使其在Windows上正常工作
if platform.system() == "Windows":
    LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "euserv_renewal.log")
else:
    LOG_FILE = "/root/euserv_renewal.log"

def setup_logging():
    """设置日志文件，限制大小"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout)
        ]
    )
    if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 10 * 1024 * 1024:
        with open(LOG_FILE, "w") as f:
            f.truncate(0)


def log(info: str, tg_push: bool = True):
    """日志记录函数，支持控制是否推送到 Telegram"""
    emoji_map = {
        "正在续费": "🔄",
        "检测到": "🔍",
        "ServerID": "🔗",
        "无需更新": "✅",
        "续订错误": "⚠️",
        "已成功续订": "🎉",
        "所有 VPS 续期成功": "🏁",
        "续期失败": "❗",
        "无 VPS 需要续期": "ℹ️",
        "验证通过": "✔️",
        "验证失败": "❌",
        "验证码是": "🔢",
        "账号准备登录": "🔑",
        "[Gmail]": "📧",
        "[ddddocr]": "🧩",
        "[德鸡自动续期]": "🌐",
        "[查询续费时间]": "📅",
        "[更新续费时间]": "✅",
        "[续订 ServerID]": "⚠️",
        "[（德鸡壹号）德鸡拉德鸡]": "🐸",
        "开始查询第一个账号": "🔍",
        "账号用户名": "🌐",
    }
    
    # 在Windows上，不使用表情符号以避免编码问题
    if platform.system() == "Windows":
        emoji_info = info
    else:
        for key, emoji in emoji_map.items():
            if key in info:
                emoji_info = emoji + " " + info
                break
        else:
            emoji_info = info
            
    try:
        logging.info(emoji_info)
        print(info)  # 使用原始信息直接打印到控制台
    except UnicodeEncodeError:
        # 如果发生编码错误，打印不带表情符号的版本
        logging.info(info)
        print(info)
        
    if tg_push:
        global desp
        desp += info + "\n\n"


# 单账号配置
USERNAME = 'hey.04138714@gmail.com'
PASSWORD = 'Hy@24862486'
GMAIL_USER = 'hey.04138714@gmail.com'
GMAIL_APP_PASSWORD = 'rnjkqzadjvheohcl'

# Telegram配置
TELEGRAM_BOT_TOKEN = "7894414501:AAF87cb9Tj6t7hwEu6fE7gbrExOxn3_RjX8"
TELEGRAM_CHAT_ID = "6977085303"

# 其他配置
GMAIL_FOLDER = "INBOX"
IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993
LOGIN_MAX_RETRY_COUNT = 3
WAITING_TIME_OF_PIN = 15
ocr = ddddocr.DdddOcr()
user_agent = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

renewal_performed = False
desp = ""


def get_system_info():
    """获取 CPU 型号、总内存、CPU 使用率、内存使用率、磁盘信息"""
    try:
        cpu_model = "Unknown"
        if os.path.exists('/proc/cpuinfo'):
            try:
                with open('/proc/cpuinfo', 'r') as f:
                    for line in f:
                        if line.strip().startswith('model name'):
                            cpu_model = line.split(':', 1)[1].strip()
                            break
                if cpu_model == "Unknown" or not cpu_model:
                    log("[德鸡自动续期] /proc/cpuinfo 未找到有效的 CPU 型号")
            except Exception as e:
                log(f"[德鸡自动续期] 读取 /proc/cpuinfo 失败: {str(e)}")
        
        if cpu_model == "Unknown":
            cpu_model = platform.processor() or "Unknown"
            if cpu_model == "Unknown" or cpu_model.lower() in ["x86_64", "amd64"]:
                log("[德鸡自动续期] platform.processor() 返回架构信息而非 CPU 型号")
        
        total_memory = psutil.virtual_memory().total / (1024 ** 3)
        cpu_usage = psutil.cpu_percent(interval=1)
        memory_usage = psutil.virtual_memory().percent
        

        disk_usage = psutil.disk_usage('/')
        total_disk = disk_usage.total / (1024 ** 3)  # 转换为 GB
        used_disk = disk_usage.used / (1024 ** 3)   # 转换为 GB
        free_disk = disk_usage.free / (1024 ** 3)   # 转换为 GB

        return {
            "cpu_model": cpu_model,
            "total_memory": total_memory,
            "cpu_usage": cpu_usage,
            "memory_usage": memory_usage,
            "total_disk": total_disk,
            "used_disk": used_disk,
            "free_disk": free_disk,
            "valid": True
        }
    except Exception as e:
        log(f"[德鸡自动续期] 获取系统资源信息失败: {str(e)}")
        return {
            "cpu_model": "Unknown",
            "total_memory": 0,
            "cpu_usage": 0,
            "memory_usage": 0,
            "total_disk": 0,
            "used_disk": 0,
            "free_disk": 0,
            "valid": False
        }


def login_retry(max_retry=3):
    def wrapper(func):
        def inner(*args, **kwargs):
            ret, ret_session = func(*args, **kwargs)
            number = 0
            if ret == "-1":
                while number < max_retry:
                    number += 1
                    if number > 1:
                        log(f"[德鸡自动续期] 登录尝试第 {number} 次")
                    sess_id, session = func(*args, **kwargs)
                    if sess_id != "-1":
                        return sess_id, session
                    else:
                        if number == max_retry:
                            return sess_id, session
                    time.sleep(2)
            else:
                return ret, ret_session
        return inner
    return wrapper


def number_to_chinese(num):
    chinese_digits = ["一", "二", "三", "四", "五", "六", "七", "八", "九"]
    if 1 <= num <= 9:
        return chinese_digits[num - 1]
    else:
        return str(num)

@login_retry(max_retry=LOGIN_MAX_RETRY_COUNT)
def login(username: str, password: str) -> (str, requests.session):
    headers = {"user-agent": user_agent, "origin": "https://www.euserv.com"}
    url = "https://support.euserv.com/index.iphp"
    ddddocr_image_url = "https://support.euserv.com/securimage_show.php"
    session = requests.Session()
    sess = session.get(url, headers=headers)
    sess_id = re.findall("PHPSESSID=(\\w{10,100});", str(sess.headers))[0]
    log(f"[获取PHPSESSID] 获取到 PHPSESSID: {sess_id}", tg_push=False)
    session.get("https://support.euserv.com/pic/logo_small.png", headers=headers)
    time.sleep(1)
    login_data = {
        "email": username,
        "password": password,
        "form_selected_language": "en",
        "Submit": "Login",
        "subaction": "login",
        "sess_id": sess_id,
    }
    log(f"[账号准备登录] 正在提交登录请求...")
    f = session.post(url, headers=headers, data=login_data)
    f.raise_for_status()
    if "Hello" not in f.text and "Confirm or change your customer data here" not in f.text:
        if "To finish the login process please solve the following captcha." not in f.text:
            log(f"[登录状态] 登录失败，请检查用户名或密码: {username}")
            return "-1", session
        else:
            log("[验证码] 检测到验证码，请手动输入验证码...")
            captcha_code = ddddocr_solver(ddddocr_image_url, session)
            f2 = session.post(
                url,
                headers=headers,
                data={
                    "subaction": "login",
                    "sess_id": sess_id,
                    "captcha_code": captcha_code,
                },
            )
            if "To finish the login process please solve the following captcha." not in f2.text:
                log("[验证码] 验证通过")
                return sess_id, session
            else:
                log("[验证码] 验证失败，请重试")
                return "-1", session
    else:
        log("[登录状态] 登录成功")
        return sess_id, session

def ddddocr_solver(ddddocr_image_url: str, session: requests.session) -> str:
    log("[验证码] 正在下载验证码图片...")
    response = session.get(ddddocr_image_url)
    log("[验证码] 验证码图片下载完成")
    
    # 保存验证码图片到临时文件
    import tempfile
    temp_dir = tempfile.gettempdir()
    captcha_file = os.path.join(temp_dir, "euserv_captcha.png")
    
    with open(captcha_file, "wb") as f:
        f.write(response.content)
    
    log(f"[验证码] 验证码图片已保存到: {captcha_file}")
    
    # 打开验证码图片
    try:
        if platform.system() == "Windows":
            os.startfile(captcha_file)
        else:
            import subprocess
            subprocess.run(["xdg-open", captcha_file], check=False)
    except Exception as e:
        log(f"[验证码] 无法自动打开图片: {str(e)}")
        log(f"[验证码] 请手动打开图片文件: {captcha_file}")
    
    # 等待用户输入验证码
    log("[验证码] 请查看打开的验证码图片，然后输入验证码:")
    result = input().strip()
    log(f"[验证码] 您输入的验证码是: {result}")
    
    # 清理临时文件
    try:
        os.remove(captcha_file)
    except:
        pass
    
    return result

def get_pin_from_gmail(gmail_user: str, gmail_app_password: str) -> str:
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    try:
        mail.login(gmail_user, gmail_app_password)
    except Exception as e:
        log(f"[Gmail] Gmail 登录失败，请检查应用专用密码 for {gmail_user}: {str(e)}")
        return None
    mail.select(GMAIL_FOLDER)
    status, messages = mail.search(None, "ALL")
    if status != "OK":
        log(f"[Gmail] 无法检索邮件列表 for {gmail_user}")
        return None
    latest_email_id = messages[0].split()[-1]
    status, msg_data = mail.fetch(latest_email_id, "(RFC822)")
    if status != "OK":
        log(f"[Gmail] 无法检索邮件内容 for {gmail_user}")
        return None
    raw_email = msg_data[0][1]
    msg = email.message_from_bytes(raw_email)
    pin = None
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                body = part.get_payload(decode=True).decode()
                pin_match = re.search(r'PIN:\s*(\d{6})', body)
                if pin_match:
                    pin = pin_match.group(1)
                    break
    else:
        body = msg.get_payload(decode=True).decode()
        pin_match = re.search(r'PIN:\s*(\d{6})', body)
        if pin_match:
            pin = pin_match.group(1)
    mail.logout()
    if pin:
        log(f"[Gmail] 成功获取PIN: {pin} for {gmail_user}")
        return pin
    else:
        raise Exception(f"未能从邮件中提取PIN for {gmail_user}")

def get_servers(sess_id: str, session: requests.session) -> dict:
    d = {}
    url = "https://support.euserv.com/index.iphp?sess_id=" + sess_id
    headers = {"user-agent": user_agent, "origin": "https://www.euserv.com"}
    f = session.get(url=url, headers=headers)
    f.raise_for_status()
    soup = BeautifulSoup(f.text, "html.parser")
    
    for tr in soup.select(
        "#kc2_order_customer_orders_tab_content_1 .kc2_order_table.kc2_content_table tr"
    ):
        server_id = tr.select(".td-z1-sp1-kc")
        if not len(server_id) == 1:
            continue
        server_id_text = server_id[0].get_text().strip()
        

        action_container = tr.select(".td-z1-sp2-kc .kc2_order_action_container")
        if not action_container:
            continue
        action_text = action_container[0].get_text().strip()
        flag = True if action_text.find("Contract extension possible from") == -1 else False
        

        renewal_time = "Unknown"
        if "Contract extension possible from" in action_text:
            date_match = re.search(r"Contract extension possible from (\d{4}-\d{2}-\d{2})", action_text)
            if date_match:
                renewal_time = date_match.group(1)
        else:
            expiry_date = tr.select(".td-z1-sp3-kc")
            if expiry_date and len(expiry_date) > 0:
                expiry_text = expiry_date[0].get_text().strip()
                date_match = re.search(r"\d{4}-\d{2}-\d{2}", expiry_text)
                if date_match:
                    renewal_time = date_match.group(0)
        
        # 计算合同结束时间（续期时间加10天）
        end_of_contract = "Unknown"
        if renewal_time != "Unknown":
            try:
                renewal_date = datetime.strptime(renewal_time, "%Y-%m-%d")
                end_of_contract_date = renewal_date + timedelta(days=10)
                end_of_contract = end_of_contract_date.strftime("%Y-%m-%d")
            except Exception as e:
                log(f"[合同结束时间] ServerID: {server_id_text} 计算合同结束时间失败: {str(e)}")
        
        d[server_id_text] = {
            "can_renew": flag,
            "renewal_time": renewal_time,
            "end_of_contract": end_of_contract
        }
    
    return d

async def send_telegram_notification(message: str):
    try:
        if len(message) > 4000:
            message = message[-4000:]
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='HTML')
        log("[德鸡自动续期] 续期结果已推送至Telegram")
    except Exception as e:
        log(f"[德鸡自动续期] 发送Telegram通知时发生错误: {str(e)}")

def renew(sess_id: str, session: requests.session, order_id: str) -> bool:
    global renewal_performed
    url = "https://support.euserv.com/index.iphp"
    headers = {
        "user-agent": user_agent,
        "Host": "support.euserv.com",
        "origin": "https://support.euserv.com",
        "Referer": "https://support.euserv.com/index.iphp",
    }
    data = {
        "Submit": "Extend contract",
        "sess_id": sess_id,
        "ord_no": order_id,
        "subaction": "choose_order",
        "choose_order_subaction": "show_contract_details",
    }
    session.post(url, headers=headers, data=data)
    session.post(
        url,
        headers=headers,
        data={
            "sess_id": sess_id,
            "subaction": "show_kc2_security_password_dialog",
            "prefix": "kc2_customer_contract_details_extend_contract_",
            "type": "1",
        },
    )
    log("[Gmail] 等待PIN邮件到达...")
    time.sleep(WAITING_TIME_OF_PIN)
    retry_count = 3
    pin = None
    for i in range(retry_count):
        try:
            pin = get_pin_from_gmail(GMAIL_USER, GMAIL_APP_PASSWORD)
            if pin:
                break
        except Exception as e:
            if i < retry_count - 1:
                log(f"[Gmail] 第{i+1}次尝试获取PIN失败，等待后重试...")
                time.sleep(5)
            else:
                raise Exception(f"多次尝试获取PIN均失败: {str(e)}")
    if not pin:
        return False
    data = {
        "auth": pin,
        "sess_id": sess_id,
        "subaction": "kc2_security_password_get_token",
        "prefix": "kc2_customer_contract_details_extend_contract_",
        "type": 1,
        "ident": f"kc2_customer_contract_details_extend_contract_{order_id}",
    }
    f = session.post(url, headers=headers, data=data)
    f.raise_for_status()
    if not json.loads(f.text)["rs"] == "success":
        return False
    token = json.loads(f.text)["token"]["value"]
    data = {
        "sess_id": sess_id,
        "ord_id": order_id,
        "subaction": "kc2_customer_contract_details_extend_contract_term",
        "token": token,
    }
    response = session.post(url, headers=headers, data=data)
    if response.status_code == 200:
        renewal_performed = True
        return True
    return False

def check(sess_id: str, session: requests.session) -> bool:
    d = get_servers(sess_id, session)
    if not d:
        log("[查询续费时间] 未开通VPS")
        log("[更新续费时间] 未开通VPS")
        log(f"[德鸡自动续期] 账号 {USERNAME} 未开通VPS")
        return False
    failed_servers = []
    for key, val in d.items():
        if val["can_renew"]:
            failed_servers.append(f"ServerID: {key} (续期时间: {val['renewal_time']})")
    if failed_servers:
        log(f"[德鸡自动续期] 账号 {USERNAME} 的以下 VPS 续期失败：{', '.join(failed_servers)}")
        return False
    else:
        log(f"[德鸡自动续期] 账号 {USERNAME} 的所有 VPS 续期成功")
        return True

def format_date(date_str: str) -> str:
    """将日期格式化为 xxxx年x月x日"""
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{date_obj.year}年{date_obj.month}月{date_obj.day}日"
    except:
        return "未知"

async def process_renewal():
    global renewal_performed, desp
    renewal_performed = False
    desp = ""
    
    log(f"[德鸡自动续期] 账号用户名：{USERNAME}")
    log(f"[开始续费] 正在续费账号: {USERNAME}")
    
    # 获取系统信息
    system_info = get_system_info()
    if system_info["valid"]:
        desp += (
            f"[查询CPU型号] : {system_info['cpu_model']}\n\n"
            f"[查询总内存] : {system_info['total_memory']:.2f} GB\n\n"
            f"[当前CPU使用率] : {system_info['cpu_usage']:.2f}%\n\n"
            f"[当前内存使用率] : {system_info['memory_usage']:.2f}%\n\n"
            f"[总硬盘空间] : {system_info['total_disk']:.2f} GB\n\n"
            f"[已使用硬盘空间] : {system_info['used_disk']:.2f} GB\n\n"
            f"[剩余硬盘空间] : {system_info['free_disk']:.2f} GB\n\n"
        )
    
    # 登录
    sessid, s = login(USERNAME, PASSWORD)
    if sessid == "-1":
        log(f"[登录状态] 登录失败，请检查用户名、密码或 Gmail 配置: {USERNAME}")
        desp += "[登录状态] 登录失败，请检查用户名和密码\n\n"
        tg_message = f"<b>德鸡续期结果</b>\n\n{desp}"
        await send_telegram_notification(tg_message)
        return False
        
    # 获取服务器信息
    SERVERS = get_servers(sessid, s)
    if not SERVERS:
        log(f"[检测账号] 账号 {USERNAME} 有 0 台 VPS")
        log("[查询续费时间] 未开通VPS")
        log("[更新续费时间] 未开通VPS")
        log(f"[德鸡自动续期] 账号 {USERNAME} 未开通VPS")
        desp += "[账号状态] 未开通VPS\n\n"
        tg_message = f"<b>德鸡续期结果</b>\n\n{desp}"
        await send_telegram_notification(tg_message)
        return False
        
    # 显示VPS数量
    log(f"[检测账号] 账号 {USERNAME} 有 {len(SERVERS)} 台 VPS")
    desp += f"[检测账号] 发现 {len(SERVERS)} 台 VPS\n\n"
    
    # 处理每个服务器
    has_renewable = False
    success_count = 0
    failed_count = 0
    
    for server_id, server_info in SERVERS.items():
        end_of_contract_formatted = format_date(server_info['end_of_contract'])
        log(f"[查询续费时间] ServerID: {server_id} 续期时间: {server_info['renewal_time']}，合同期结束时间: {end_of_contract_formatted}")
        desp += f"[ServerID: {server_id}] 续期时间: {server_info['renewal_time']}，合同期结束时间: {end_of_contract_formatted}\n\n"
        
        if server_info["can_renew"]:
            has_renewable = True
            try:
                if renew(sessid, s, server_id):
                    log(f"[已成功续订] ServerID: {server_id} 已成功续订! (续期时间: {server_info['renewal_time']}，合同期结束时间: {end_of_contract_formatted})")
                    desp += f"[ServerID: {server_id}] 续订成功!\n\n"
                    success_count += 1
                else:
                    log(f"[续订错误] ServerID: {server_id} 续订错误! (续期时间: {server_info['renewal_time']}，合同期结束时间: {end_of_contract_formatted})")
                    desp += f"[ServerID: {server_id}] 续订失败!\n\n"
                    failed_count += 1
            except Exception as e:
                log(f"[续订 ServerID] 续订 ServerID: {server_id} 时发生错误: {str(e)} (续期时间: {server_info['renewal_time']}，合同期结束时间: {end_of_contract_formatted})")
                desp += f"[ServerID: {server_id}] 续订出错: {str(e)}\n\n"
                failed_count += 1
        else:
            log(f"[更新续费时间] ServerID: {server_id} 无需更新 (续期时间: {server_info['renewal_time']}，合同期结束时间: {end_of_contract_formatted})")
            desp += f"[ServerID: {server_id}] 无需续期\n\n"
    
    # 添加摘要信息
    if not has_renewable:
        log("[检测账号] 账号无 VPS 需要续期")
        desp += "[状态摘要] 无VPS需要续期\n\n"
    elif success_count > 0 and failed_count == 0:
        log("[德鸡自动续期] 所有需要续期的VPS都已成功续期")
        desp += f"[状态摘要] 所有需要续期的VPS ({success_count}台) 已成功续期\n\n"
    elif failed_count > 0:
        log(f"[德鸡自动续期] {success_count}台VPS成功续期，{failed_count}台VPS续期失败")
        desp += f"[状态摘要] {success_count}台VPS成功续期，{failed_count}台VPS续期失败\n\n"
    
    # 等待后再次检查
    time.sleep(15)
    check_result = check(sessid, s)
    
    # 发送通知
    tg_message = f"<b>德鸡续期结果</b>\n\n{desp}"
    await send_telegram_notification(tg_message)
    
    return check_result

async def main():
    log("[德鸡自动续期] 脚本启动")
    log(f"[德鸡自动续期] Python executable: {sys.executable}")
    
    log("[德鸡自动续期] 开始执行续期流程")
    await process_renewal()
    log("[德鸡自动续期] 续期流程执行完成")

def handle_exit(signum, frame):
    log("[德鸡自动续期] 收到退出信号，正在关闭...")
    sys.exit(0)

if __name__ == "__main__":
    try:
        print("开始初始化...")
        setup_logging()
        print("日志设置完成，日志路径:", LOG_FILE)
        
        if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN" or TELEGRAM_CHAT_ID == "YOUR_TELEGRAM_CHAT_ID":
            log("[德鸡自动续期] 请配置 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID")
            print("请配置 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID")
            sys.exit(1)
            
        required_modules = ['pytz', 'requests', 'bs4', 'ddddocr', 'telegram', 'aiohttp', 'psutil']
        missing_modules = []
        for module in required_modules:
            try:
                __import__(module)
            except ImportError:
                missing_modules.append(module)
        if missing_modules:
            log(f"[德鸡自动续期] 缺少以下依赖: {', '.join(missing_modules)}")
            print(f"缺少以下依赖: {', '.join(missing_modules)}")
            print("请安装依赖: pip install " + " ".join(missing_modules))
            sys.exit(1)
            
        print("依赖检查完成，所有必需模块已安装")
            
        # 在Windows上处理信号
        if platform.system() != "Windows":
            signal.signal(signal.SIGINT, handle_exit)
            signal.signal(signal.SIGTERM, handle_exit)
        
        print("开始执行主函数...")
        asyncio.run(main())
        print("主函数执行完成")
    except Exception as e:
        error_message = f"[德鸡自动续期] 程序异常退出: {str(e)}"
        log(error_message)
        print("错误:", error_message)
        import traceback
        print("详细错误信息:", traceback.format_exc())
        sys.exit(1)
