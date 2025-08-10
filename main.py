
# main.py
import json
import urllib.parse
from fastapi import FastAPI, Request, HTTPException
import asyncio
import yaml
import logging
from typing import Dict, Any

from git_payload_parser import GitPayloadParser
from rss_payload_parser import RSSPayloadParser
from generic_payload_parser import GenericPayloadParser
from netlify_payload_parser import NetlifyPayloadParser
from rss_monitor import RSSMonitor
from notification_dispatcher import NotificationDispatcher
from generic_webhook_handler import handle_generic_webhook

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI(
    title="WebHook Notifier",
    description="一个用于接收=WebHook和RSS订阅更新的HTTP服务器。",
    version="1.2.0"
)

# 加载配置
CONFIG: Dict[str, Any] = {}
try:
    with open("config.yaml", "r", encoding="utf-8") as f:
        CONFIG = yaml.safe_load(f)
    logging.info("配置加载成功。")
except FileNotFoundError:
    logging.error("config.yaml 文件未找到。请确保它存在于应用程序根目录。")
    exit(1)
except yaml.YAMLError as e:
    logging.error(f"解析config.yaml时发生错误: {e}")
    exit(1)

# 初始化通知分发器
dispatcher = NotificationDispatcher(CONFIG)

# 初始化RSS监控器
rss_monitor = RSSMonitor(CONFIG, dispatcher)

async def delayed_notification_task(parsed_payload: dict):
    """
    延迟发送通知的异步任务。
    """
    delay_seconds = CONFIG['global']['notification_delay_seconds']
    logging.info(f"将在 {delay_seconds} 秒后发送通知...")
    await asyncio.sleep(delay_seconds)

    # 根据平台类型格式化消息
    platform = parsed_payload.get('platform', 'Unknown')
    message = ""
    subject = "收到新的 WebHook 通知"

    if platform == 'RSS':
        message = RSSPayloadParser.format_rss_notification(parsed_payload)
        subject = f"RSS新文章: {parsed_payload.get('article_title', '无标题')}"
    elif platform == 'Generic':
        message = GenericPayloadParser.format_notification(parsed_payload)
        # For generic webhooks, the subject can be more generic or customized if needed
        subject = "收到新的通用 WebHook 通知"
    elif platform in ['GitHub', 'GitLab', 'Gitea', 'Gogs']:
        message = GitPayloadParser.format_notification(parsed_payload)
        subject = f"文章更新: {parsed_payload.get('repository_name', '未知仓库')}"
    elif platform == 'Netlify':
        message = NetlifyPayloadParser.format_notification(parsed_payload)
        subject = f"Netlify站点更新: {parsed_payload.get('site_name', '未知站点')}"
    else:
        logging.warning(f"未知的平台类型: {platform}")
        return

    logging.info(f"正在发送通知：\n{message}")

    # 发送通知
    if CONFIG.get('telegram', {}).get('enabled'):
        await dispatcher.send_telegram_message(message)
    if CONFIG.get('email', {}).get('enabled'):
        dispatcher.send_email(subject, message)
    if CONFIG.get('napcat', {}).get('enabled'):
        await dispatcher.send_napcat_message(message)

    logging.info("通知发送完成。")


@app.post("/webhook/git")
async def handle_git_webhook(request: Request):
    """
    处理来自Git平台的WebHook请求。
    """
    try:
        # 获取原始请求体用于签名验证
        body = await request.body()
        
        # 检查请求体是否为空
        if not body:
            logging.error("请求体为空。")
            raise HTTPException(status_code=400, detail="请求体为空。")
        
        headers = dict(request.headers)
        content_type = headers.get('content-type', '').lower()
        
        logging.info(f"收到Git WebHook请求体长度: {len(body)} 字节")
        logging.info(f"Content-Type: {content_type}")
        logging.info(f"收到Git WebHook请求。Headers: {list(headers.keys())}")
        
        # 根据Content-Type解析payload
        payload = None
        try:
            if 'application/json' in content_type:
                # JSON格式
                payload = json.loads(body.decode('utf-8'))
                logging.info("解析为JSON格式")
            elif 'application/x-www-form-urlencoded' in content_type:
                # 表单编码格式 (GitHub常用)
                body_str = body.decode('utf-8')
                if body_str.startswith('payload='):
                    # GitHub webhook格式: payload=<url_encoded_json>
                    payload_data = body_str[8:]  # 移除 'payload=' 前缀
                    decoded_payload = urllib.parse.unquote(payload_data)
                    payload = json.loads(decoded_payload)
                    logging.info("解析为GitHub表单编码格式")
                else:
                    # 标准表单编码
                    form_data = urllib.parse.parse_qs(body_str)
                    if 'payload' in form_data:
                        payload = json.loads(form_data['payload'][0])
                        logging.info("解析为标准表单编码格式")
                    else:
                        raise ValueError("表单数据中未找到payload字段")
            else:
                # 尝试直接解析为JSON
                payload = json.loads(body.decode('utf-8'))
                logging.info("尝试直接解析为JSON格式")
                
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
            logging.error(f"无法解析请求体: {e}")
            logging.error(f"Content-Type: {content_type}")
            logging.error(f"请求体前100字符: {body.decode('utf-8', errors='replace')[:100]}")
            raise HTTPException(status_code=400, detail="无法解析请求体数据。")

        if not payload:
            logging.error("解析后的payload为空")
            raise HTTPException(status_code=400, detail="解析后的payload为空。")

        # 创建一个case-insensitive的headers字典用于查找
        headers_lower = {k.lower(): v for k, v in headers.items()}
        
        parsed_payload = None

        # 根据X-Git-Event头部识别平台并解析负载 (case-insensitive)
        if 'x-github-event' in headers_lower:
            secret = CONFIG.get('github', {}).get('secret', '') 
            # 传递原始请求体用于签名验证
            parsed_payload = GitPayloadParser.parse_github_payload(headers, payload, secret, body)
        elif 'x-gitlab-event' in headers_lower:
            secret = CONFIG.get('gitlab', {}).get('secret', '') 
            parsed_payload = GitPayloadParser.parse_gitlab_payload(headers, payload, secret)
        elif 'x-gitea-event' in headers_lower:
            secret = CONFIG.get('gitea', {}).get('secret', '') 
            parsed_payload = GitPayloadParser.parse_gitea_payload(headers, payload, secret, body)
        elif 'x-gogs-event' in headers_lower:
            secret = CONFIG.get('gogs', {}).get('secret', '')
            parsed_payload = GitPayloadParser.parse_gogs_payload(headers, payload, secret)
        else:
            logging.warning(f"无法识别的Git WebHook平台。可用headers: {list(headers_lower.keys())}")
            raise HTTPException(status_code=400, detail="无法识别的Git WebHook平台。")

        if not parsed_payload:
            logging.warning("Git WebHook负载解析失败或签名验证失败。")
            raise HTTPException(status_code=400, detail="Git WebHook负载解析失败或签名验证失败。")

        logging.info(f"成功解析Git WebHook负载：{parsed_payload['platform']} - {parsed_payload['repository_name']}")

        # 调度延迟通知任务，不阻塞主请求
        asyncio.create_task(delayed_notification_task(parsed_payload))

        return {"message": "Git WebHook接收成功，通知已调度。"}

    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"处理Git WebHook时发生内部服务器错误: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"内部服务器错误: {e}")


@app.post("/webhook/generic")
async def webhook_generic(request: Request):
    """
    处理通用WebHook请求。
    """
    parsed_payload = await handle_generic_webhook(request, CONFIG)
    if parsed_payload:
        asyncio.create_task(delayed_notification_task(parsed_payload))
        return {"message": "通用 WebHook 接收成功，通知已调度。"}
    else:
        # The handler already raises HTTPException, but as a fallback:
        raise HTTPException(status_code=400, detail="通用 WebHook 负载处理失败。")


@app.post("/webhook/rss")
async def handle_rss_webhook(request: Request):
    """
    处理RSS WebHook请求。密钥验证是可选的。
    """
    try:
        # 获取原始请求体用于签名验证
        body = await request.body()
        
        # 检查请求体是否为空
        if not body:
            logging.error("RSS WebHook请求体为空。")
            raise HTTPException(status_code=400, detail="请求体为空。")
        
        headers = dict(request.headers)
        content_type = headers.get('content-type', '').lower()
        
        logging.info(f"收到RSS WebHook请求体长度: {len(body)} 字节")
        logging.info(f"Content-Type: {content_type}")
        logging.info(f"收到RSS WebHook请求。Headers: {list(headers.keys())}")
        
        # 解析JSON payload
        try:
            payload = json.loads(body.decode('utf-8'))
            logging.info("RSS WebHook解析为JSON格式")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logging.error(f"无法解析RSS WebHook请求体: {e}")
            logging.error(f"请求体前100字符: {body.decode('utf-8', errors='replace')[:100]}")
            raise HTTPException(status_code=400, detail="无法解析RSS WebHook请求体数据。")

        if not payload:
            logging.error("RSS WebHook解析后的payload为空")
            raise HTTPException(status_code=400, detail="解析后的payload为空。")

        # 解析RSS webhook负载（密钥验证是可选的）
        secret = CONFIG.get('rss', {}).get('webhook', {}).get('secret', '')
        parsed_payload = RSSPayloadParser.parse_rss_webhook(headers, payload, secret, body)

        if not parsed_payload:
            logging.warning("RSS WebHook负载解析失败。")
            raise HTTPException(status_code=400, detail="RSS WebHook负载解析失败。")

        logging.info(f"成功解析RSS WebHook负载：{parsed_payload['feed_name']} - {parsed_payload['article_title']}")

        # 调度延迟通知任务，不阻塞主请求
        asyncio.create_task(delayed_notification_task(parsed_payload))

        return {"message": "RSS WebHook接收成功，通知已调度。"}

    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"处理RSS WebHook时发生内部服务器错误: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"内部服务器错误: {e}")


@app.post("/webhook/netlify")
async def handle_netlify_webhook(request: Request):
    """
    处理来自Netlify的WebHook请求。
    """
    try:
        # 获取原始请求体用于签名验证
        body = await request.body()
        
        # 检查请求体是否为空
        if not body:
            logging.error("Netlify WebHook请求体为空。")
            raise HTTPException(status_code=400, detail="请求体为空。")
        
        headers = dict(request.headers)
        content_type = headers.get('content-type', '').lower()
        
        logging.info(f"收到Netlify WebHook请求体长度: {len(body)} 字节")
        logging.info(f"Content-Type: {content_type}")
        logging.info(f"收到Netlify WebHook请求。Headers: {list(headers.keys())}")
        
        # 解析JSON payload
        try:
            payload = json.loads(body.decode('utf-8'))
            logging.info("Netlify WebHook解析为JSON格式")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logging.error(f"无法解析Netlify WebHook请求体: {e}")
            logging.error(f"请求体前100字符: {body.decode('utf-8', errors='replace')[:100]}")
            raise HTTPException(status_code=400, detail="无法解析Netlify WebHook请求体数据。")

        if not payload:
            logging.error("Netlify WebHook解析后的payload为空")
            raise HTTPException(status_code=400, detail="解析后的payload为空。")

        # 解析Netlify webhook负载
        secret = CONFIG.get('netlify', {}).get('secret', '')
        parsed_payload = NetlifyPayloadParser.parse_payload(headers, payload, secret, body)

        if not parsed_payload:
            logging.warning("Netlify WebHook负载解析失败或签名验证失败。")
            raise HTTPException(status_code=400, detail="Netlify WebHook负载解析失败或签名验证失败。")

        logging.info(f"成功解析Netlify WebHook负载：{parsed_payload['site_name']} - {parsed_payload['state']}")

        # 调度延迟通知任务，不阻塞主请求
        asyncio.create_task(delayed_notification_task(parsed_payload))

        return {"message": "Netlify WebHook接收成功，通知已调度。"}

    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"处理Netlify WebHook时发生内部服务器错误: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"内部服务器错误: {e}")


@app.get("/")
async def root():
    """
    根路径，返回服务状态。
    """
    return {
        "message": "Git & RSS WebHook Notifier 服务正在运行",
        "version": "1.2.0",
        "endpoints": {
            "git_webhook": "/webhook/git",
            "rss_webhook": "/webhook/rss",
            "generic_webhook": "/webhook/generic",
            "netlify_webhook": "/webhook/netlify"
        }
    }


@app.on_event("startup")
async def startup_event():
    """
    应用启动时的事件处理。
    """
    logging.info("启动 Git & RSS WebHook Notifier 服务...")
    
    # 启动RSS监控服务（在后台运行）
    asyncio.create_task(rss_monitor.start_monitoring())
    
    logging.info("服务启动完成。")


@app.on_event("shutdown")
async def shutdown_event():
    """
    应用关闭时的事件处理。
    """
    logging.info("正在关闭 Git & RSS WebHook Notifier 服务...")
    
    # 保存RSS监控状态
    rss_monitor.save_seen_articles()
