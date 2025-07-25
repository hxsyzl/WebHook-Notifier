
# notification_dispatcher.py
import httpx # 用于异步HTTP请求
import smtplib
from email.message import EmailMessage
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class NotificationDispatcher:
    """
    负责向不同平台分发通知。
    """

    def __init__(self, config: dict):
        self.config = config

    def _get_async_client(self) -> httpx.AsyncClient:
        """根据配置创建并返回一个httpx.AsyncClient实例。"""
        proxy_config = self.config.get('global', {}).get('proxy', {})
        
        if not proxy_config.get('enabled', False):
            # 代理被禁用
            logging.info("代理已禁用，将直接进行网络连接。")
            return httpx.AsyncClient(proxy=None)

        proxy_url = proxy_config.get('url')
        if proxy_url:
            # 清理代理URL，移除可能的空格
            proxy_url = proxy_url.strip()
            if proxy_url:  # 确保清理后不是空字符串
                # 使用指定的代理URL
                logging.info(f"正在使用指定代理: {proxy_url}")
                return httpx.AsyncClient(proxy=proxy_url)
            else:
                logging.warning("代理URL配置为空字符串，使用系统代理。")
                return httpx.AsyncClient()
        else:
            # 启用代理但未指定URL，使用系统代理
            logging.info("正在使用系统代理。")
            return httpx.AsyncClient()

    async def send_telegram_message(self, message: str):
        """
        向Telegram发送消息，如果消息过长则分段发送。
        """
        if not self.config.get('telegram', {}).get('enabled'):
            logging.info("Telegram通知未启用。")
            return

        bot_token = self.config['telegram']['bot_token']
        chat_id = self.config['telegram']['chat_id']
        if not bot_token or not chat_id:
            logging.error("Telegram配置不完整（bot_token或chat_id缺失）。")
            return

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        max_length = 4000  # Telegram API限制为4096，留一些余量

        async def _send_chunk(text_chunk: str):
            """发送单个消息块。"""
            payload = {
                "chat_id": chat_id,
                "text": text_chunk,
                "parse_mode": "Markdown"
            }
            try:
                async with self._get_async_client() as client:
                    response = await client.post(url, json=payload, timeout=10)
                    response.raise_for_status()
                    logging.info(f"Telegram消息块发送成功。")
            except httpx.RequestError as e:
                logging.error(f"Telegram消息块发送请求失败: {e}")
            except httpx.HTTPStatusError as e:
                logging.error(f"Telegram消息块发送HTTP错误: {e.response.status_code} - {e.response.text}")
            except Exception as e:
                logging.error(f"发送Telegram消息块时发生未知错误: {e}")

        if len(message) <= max_length:
            # 消息长度在限制内，直接发送
            await _send_chunk(message)
        else:
            # 消息过长，进行分段发送
            logging.warning("消息过长，将进行分段发送。")
            parts = []
            current_part = ""
            # 优先按换行符分割，以保持格式
            lines = message.split('\n')
            for line in lines:
                # 如果当前部分加上新的一行超过了长度限制
                if len(current_part) + len(line) + 1 > max_length:
                    if current_part:
                        parts.append(current_part)
                    # 如果单行就超过了长度，需要强制分割
                    while len(line) > max_length:
                        parts.append(line[:max_length])
                        line = line[max_length:]
                    current_part = line
                else:
                    if current_part:
                        current_part += "\n" + line
                    else:
                        current_part = line
            
            if current_part:
                parts.append(current_part)

            for i, part in enumerate(parts):
                logging.info(f"正在发送消息块 {i+1}/{len(parts)}...")
                await _send_chunk(part)

    def send_email(self, subject: str, body: str):
        """
        通过SMTP发送电子邮件。
        """
        if not self.config.get('email', {}).get('enabled'):
            logging.info("Email通知未启用。")
            return

        email_config = self.config.get('email', {})
        smtp_server = email_config.get('smtp_server')
        smtp_port = email_config.get('smtp_port')
        smtp_username = email_config.get('smtp_username')
        smtp_password = email_config.get('smtp_password')
        sender_email = email_config.get('sender_email')
        recipient_emails = email_config.get('recipient_emails')
        use_ssl = email_config.get('use_ssl', False)  # 新增：是否使用SSL
        use_tls = email_config.get('use_tls', True)   # 新增：是否使用TLS

        if not all([smtp_server, smtp_port, smtp_username, smtp_password, sender_email, recipient_emails]):
            logging.error("Email配置不完整。")
            return

        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = ", ".join(recipient_emails)
        msg.set_content(body)

        try:
            # 根据配置选择连接方式
            if use_ssl:
                # 使用SSL连接（通常端口465）
                logging.info(f"使用SSL连接到SMTP服务器: {smtp_server}:{smtp_port}")
                with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                    server.login(smtp_username, smtp_password)
                    server.send_message(msg)
            else:
                # 使用普通连接，可选择STARTTLS（通常端口587）
                logging.info(f"连接到SMTP服务器: {smtp_server}:{smtp_port}")
                with smtplib.SMTP(smtp_server, smtp_port) as server:
                    if use_tls:
                        logging.info("启用STARTTLS加密")
                        server.starttls()
                    server.login(smtp_username, smtp_password)
                    server.send_message(msg)
            
            logging.info("Email发送成功。")
            
        except smtplib.SMTPAuthenticationError as e:
            logging.error(f"Email认证失败: {e}")
        except smtplib.SMTPConnectError as e:
            logging.error(f"Email连接失败: {e}")
        except smtplib.SMTPRecipientsRefused as e:
            logging.error(f"收件人被拒绝: {e}")
        except smtplib.SMTPSenderRefused as e:
            logging.error(f"发件人被拒绝: {e}")
        except smtplib.SMTPDataError as e:
            logging.error(f"SMTP数据错误: {e}")
        except smtplib.SMTPServerDisconnected as e:
            logging.error(f"SMTP服务器断开连接: {e}")
        except Exception as e:
            logging.error(f"发送Email时发生未知错误: {e}")

    async def send_napcat_message(self, message: str):
        """
        根据配置文件中的 send_mode 向Napcat发送消息。
        """
        napcat_config = self.config.get('napcat', {})
        if not napcat_config.get('enabled'):
            logging.info("Napcat通知未启用。")
            return

        base_url = napcat_config.get('base_url')
        if not base_url:
            logging.error("Napcat配置不完整 (base_url 缺失)。")
            return

        send_mode = napcat_config.get('send_mode', 'all')
        user_id = napcat_config.get('user_id')
        group_id = napcat_config.get('group_id')

        async def _send(endpoint: str, payload: dict):
            """辅助函数，用于发送请求并处理通用逻辑。"""
            url = f"{base_url}{endpoint}"
            target_name = endpoint.strip('/').replace('_', ' ')
            try:
                async with self._get_async_client() as client:
                    response = await client.post(url, json=payload, timeout=10)
                    response.raise_for_status()
                    logging.info(f"Napcat消息发送成功 ({target_name}): {response.json()}")
            except httpx.RequestError as e:
                logging.error(f"Napcat消息发送请求失败 ({target_name}): {e}")
            except httpx.HTTPStatusError as e:
                logging.error(f"Napcat消息发送HTTP错误 ({target_name}): {e.response.status_code} - {e.response.text}")
            except Exception as e:
                logging.error(f"发送Napcat消息时发生未知错误 ({target_name}): {e}")

        # 发送到私聊
        if send_mode in ['private', 'all']:
            if user_id:
                await _send("/send_private_msg", {"user_id": user_id, "message": message})
            elif send_mode == 'private':
                logging.warning("Napcat send_mode 设置为 'private'，但 user_id 未配置。")

        # 发送到群聊
        if send_mode in ['group', 'all']:
            if group_id:
                await _send("/send_group_msg", {"group_id": group_id, "message": message})
            elif send_mode == 'group':
                logging.warning("Napcat send_mode 设置为 'group'，但 group_id 未配置。")
