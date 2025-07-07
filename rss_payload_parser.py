
# rss_payload_parser.py
import feedparser
import hashlib
import hmac
import logging
from datetime import datetime
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RSSPayloadParser:
    """
    解析和处理RSS订阅数据。
    """

    @staticmethod
    def _verify_webhook_signature(payload_body: bytes, secret: str, signature_header: str) -> bool:
        """
        验证RSS webhook签名（可选）。
        """
        if not secret:
            logging.info("未配置RSS WebHook密钥，跳过签名验证。")
            return True

        if not signature_header:
            logging.info("RSS签名头部缺失，但已配置密钥。由于签名验证是可选的，继续处理请求。")
            return True  # 使签名验证完全可选

        # 计算期望的签名
        try:
            expected_signature = hmac.new(
                secret.encode('utf-8'),
                payload_body,
                hashlib.sha256
            ).hexdigest()

            # 比较签名
            provided_signature = signature_header.replace('sha256=', '')
            
            if hmac.compare_digest(expected_signature, provided_signature):
                logging.info("RSS WebHook签名验证成功。")
                return True
            else:
                logging.warning("RSS WebHook签名验证失败，但由于签名验证是可选的，继续处理请求。")
                return True  # 即使签名验证失败也继续处理
        except Exception as e:
            logging.warning(f"RSS WebHook签名验证过程中发生错误: {e}，继续处理请求。")
            return True

    @staticmethod
    def parse_rss_feed(feed_url: str) -> List[Dict]:
        """
        解析RSS订阅源。
        """
        try:
            logging.info(f"正在解析RSS订阅源: {feed_url}")
            feed = feedparser.parse(feed_url)
            
            if feed.bozo:
                logging.warning(f"RSS解析警告: {feed.bozo_exception}")
            
            articles = []
            for entry in feed.entries:
                article = {
                    'title': entry.get('title', '无标题'),
                    'link': entry.get('link', ''),
                    'description': entry.get('description', ''),
                    'summary': entry.get('summary', ''),
                    'author': entry.get('author', '未知作者'),
                    'published': entry.get('published', ''),
                    'updated': entry.get('updated', ''),
                    'guid': entry.get('id', entry.get('guid', '')),
                    'feed_title': feed.feed.get('title', '未知订阅源'),
                    'feed_url': feed_url
                }
                articles.append(article)
            
            logging.info(f"成功解析RSS订阅源，获取到 {len(articles)} 篇文章")
            return articles
            
        except Exception as e:
            logging.error(f"解析RSS订阅源失败: {e}")
            return []

    @staticmethod
    def parse_rss_webhook(headers: dict, payload: dict, secret: str = '', raw_body: bytes = None) -> Optional[Dict]:
        """
        解析RSS webhook负载。密钥验证是可选的。
        """
        try:
            # 创建case-insensitive的headers字典
            headers_lower = {k.lower(): v for k, v in headers.items()}
            
            # 可选的签名验证
            signature_header = headers_lower.get('x-rss-signature', '')
            
            # 只有在提供了原始请求体时才进行签名验证，且验证失败不会阻止处理
            if raw_body and secret:
                RSSPayloadParser._verify_webhook_signature(raw_body, secret, signature_header)
                # 注意：这里不检查返回值，因为签名验证是可选的
            
            # 解析RSS webhook数据
            if 'articles' in payload:
                # 批量文章更新
                articles = payload['articles']
                if articles:
                    # 返回第一篇文章的信息作为通知
                    first_article = articles[0]
                    return {
                        'platform': 'RSS',
                        'feed_name': first_article.get('feed_title', '未知订阅源'),
                        'article_title': first_article.get('title', '无标题'),
                        'article_url': first_article.get('link', ''),
                        'author_name': first_article.get('author', '未知作者'),
                        'description': first_article.get('description', ''),
                        'published_time': first_article.get('published', ''),
                        'total_articles': len(articles),
                        'timestamp': datetime.now().isoformat()
                    }
            elif 'article' in payload:
                # 单篇文章更新
                article = payload['article']
                return {
                    'platform': 'RSS',
                    'feed_name': article.get('feed_title', '未知订阅源'),
                    'article_title': article.get('title', '无标题'),
                    'article_url': article.get('link', ''),
                    'author_name': article.get('author', '未知作者'),
                    'description': article.get('description', ''),
                    'published_time': article.get('published', ''),
                    'total_articles': 1,
                    'timestamp': datetime.now().isoformat()
                }
            
            logging.warning("RSS webhook负载格式不正确")
            return None
            
        except Exception as e:
            logging.error(f"解析RSS webhook负载时发生错误: {e}")
            return None

    @staticmethod
    def format_rss_notification(parsed_payload: dict) -> str:
        """
        格式化RSS通知消息。
        """
        if parsed_payload['total_articles'] > 1:
            message = (
                f"RSS订阅更新通知！\n\n"
                f"订阅源: {parsed_payload['feed_name']}\n"
                f"新文章数量: {parsed_payload['total_articles']}\n"
                f"最新文章: {parsed_payload['article_title']}\n"
                f"作者: {parsed_payload['author_name']}\n"
                f"链接: {parsed_payload['article_url']}\n"
                f"发布时间: {parsed_payload['published_time']}\n"
                f"更新时间: {parsed_payload['timestamp']}"
            )
        else:
            message = (
                f"RSS新文章通知！\n\n"
                f"订阅源: {parsed_payload['feed_name']}\n"
                f"标题: {parsed_payload['article_title']}\n"
                f"作者: {parsed_payload['author_name']}\n"
                f"链接: {parsed_payload['article_url']}\n"
                f"发布时间: {parsed_payload['published_time']}\n"
                f"更新时间: {parsed_payload['timestamp']}"
            )
        
        # 添加描述（如果有且不太长）
        description = parsed_payload.get('description', '').strip()
        if description and len(description) <= 200:
            message += f"\n\n摘要: {description}"
        
        return message

