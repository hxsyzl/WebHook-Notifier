import logging
import hmac
import hashlib
from typing import Dict, Any, Optional

class GenericPayloadParser:
    """
    通用WebHook负载解析器。
    """

    @staticmethod
    def parse_payload(headers: Dict[str, str], payload: Dict[str, Any], secret: str, body: bytes) -> Optional[Dict[str, Any]]:
        """
        解析来自通用WebHook的负载。

        Args:
            headers (Dict[str, str]): 请求头。
            payload (Dict[str, Any]): JSON负载。
            secret (str): 用于验证签名的密钥。
            body (bytes): 原始请求体。

        Returns:
            Optional[Dict[str, Any]]: 解析后的负载，如果验证失败则返回None。
        """
        # 如果配置了secret，则验证签名
        if secret:
            signature = headers.get('x-hub-signature-256') or headers.get('x-signature')
            if not signature:
                logging.warning("通用WebHook缺少签名头。")
                return None
            
            # 签名格式通常是 sha256=<signature>
            if not signature.startswith('sha256='):
                logging.warning(f"不支持的签名格式: {signature}")
                return None
            
            expected_signature = 'sha256=' + hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
            
            if not hmac.compare_digest(signature, expected_signature):
                logging.warning("通用WebHook签名验证失败。")
                return None
            logging.info("通用WebHook签名验证成功。")

        # 直接将整个payload作为数据
        return {
            'platform': 'Generic',
            'data': payload
        }

    @staticmethod
    def format_notification(parsed_payload: Dict[str, Any]) -> str:
        """
        格式化通用WebHook的通知消息。

        Args:
            parsed_payload (Dict[str, Any]): 解析后的负载。

        Returns:
            str: 格式化后的通知消息。
        """
        message = "收到新的通用WebHook通知！\n\n"
        
        data = parsed_payload.get('data', {})
        
        for key, value in data.items():
            # 如果值是字典或列表，将其转换为JSON字符串以便更好地显示
            if isinstance(value, (dict, list)):
                import json
                value_str = json.dumps(value, indent=2, ensure_ascii=False)
                message += f"**{key}**:\n```json\n{value_str}\n```\n"
            else:
                message += f"**{key}**: {value}\n"
                
        return message.strip()
