import logging
import hmac
import hashlib
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class NetlifyPayloadParser:
    """
    解析并标准化来自Netlify的WebHook负载。
    """

    @staticmethod
    def parse_payload(headers: Dict[str, str], payload: Dict[str, Any], secret: str, body: bytes) -> Optional[Dict[str, Any]]:
        """
        解析来自Netlify的WebHook负载。

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
            signature = headers.get('X-Webhook-Signature')
            if not signature:
                logging.warning("Netlify WebHook缺少签名头。")
                return None
            
            # 验证签名
            expected_signature = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
            
            if not hmac.compare_digest(signature, expected_signature):
                logging.warning("Netlify WebHook签名验证失败。")
                return None
            logging.info("Netlify WebHook签名验证成功。")

        # 解析Netlify Webhook事件数据
        # Netlify webhooks通常包含site_id, site_name, and state (ready, building, etc.)
        site_id = payload.get('site_id', '')
        site_name = payload.get('site_name', '')
        state = payload.get('state', 'unknown')
        deploy_id = payload.get('deploy_id', '')
        deploy_url = payload.get('deploy_url', '')
        build_id = payload.get('build_id', '')
        
        # 通常我们只对部署完成的事件感兴趣
        if state not in ['ready', 'error']:
            logging.info(f"Netlify事件状态为 {state}，跳过通知。")
            return None

        return {
            'platform': 'Netlify',
            'site_id': site_id,
            'site_name': site_name,
            'state': state,
            'deploy_id': deploy_id,
            'deploy_url': deploy_url,
            'build_id': build_id
        }

    @staticmethod
    def format_notification(parsed_payload: Dict[str, Any]) -> str:
        """
        格式化Netlify WebHook的通知消息。

        Args:
            parsed_payload (Dict[str, Any]): 解析后的负载。

        Returns:
            str: 格式化后的通知消息。
        """
        state = parsed_payload.get('state', 'unknown')
        status_text = "部署成功" if state == 'ready' else "部署失败" if state == 'error' else "状态未知"
        
        message = f"Netlify站点更新通知！\n\n"
        message += f"站点名称: {parsed_payload.get('site_name', '未知')}\n"
        message += f"状态: {status_text}\n"
        
        if parsed_payload.get('deploy_url'):
            message += f"部署地址: {parsed_payload['deploy_url']}\n"
            
        if parsed_payload.get('deploy_id'):
            message += f"部署ID: {parsed_payload['deploy_id']}\n"
            
        return message.strip()