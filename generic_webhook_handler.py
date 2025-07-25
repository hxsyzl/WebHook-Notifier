import logging
import json
from fastapi import Request, HTTPException
from typing import Dict, Any
import asyncio

from notification_dispatcher import NotificationDispatcher
from generic_payload_parser import GenericPayloadParser

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def handle_generic_webhook(request: Request, config: Dict[str, Any]):
    """
    处理通用 WebHook 请求并返回解析后的负载。
    """
    try:
        body = await request.body()
        if not body:
            logging.error("通用 WebHook 请求体为空。")
            raise HTTPException(status_code=400, detail="请求体为空。")

        headers = dict(request.headers)
        
        try:
            payload = json.loads(body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logging.error(f"无法解析通用 WebHook 请求体: {e}")
            raise HTTPException(status_code=400, detail="无法解析通用 WebHook 请求体数据。")

        # 使用通用解析器解析负载
        secret = config.get('generic', {}).get('secret', '')
        parsed_payload = GenericPayloadParser.parse_payload(headers, payload, secret, body)

        if not parsed_payload:
            logging.warning("通用 WebHook 负载解析失败或签名验证失败。")
            raise HTTPException(status_code=400, detail="通用 WebHook 负载解析失败或签名验证失败。")

        logging.info("成功解析通用 WebHook 负载。")
        return parsed_payload

    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"处理通用 WebHook 时发生内部服务器错误: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"内部服务器错误: {e}")
