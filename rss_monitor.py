# rss_monitor.py
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Set
import hashlib
import json
import os
from rss_payload_parser import RSSPayloadParser
from notification_dispatcher import NotificationDispatcher

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RSSMonitor:
    """
    RSS订阅监控服务。
    """
    
    def __init__(self, config: dict, dispatcher: NotificationDispatcher):
        self.config = config
        self.dispatcher = dispatcher
        self.seen_articles: Set[str] = set()
        self.last_check_file = "rss_last_check.json"
        self.load_seen_articles()
    
    def load_seen_articles(self):
        """
        从文件加载已见过的文章ID。
        """
        try:
            if os.path.exists(self.last_check_file):
                with open(self.last_check_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.seen_articles = set(data.get('seen_articles', []))
                    logging.info(f"加载了 {len(self.seen_articles)} 个已见文章ID")
        except Exception as e:
            logging.error(f"加载已见文章ID失败: {e}")
    
    def save_seen_articles(self):
        """
        保存已见过的文章ID到文件。
        """
        try:
            data = {
                'seen_articles': list(self.seen_articles),
                'last_update': datetime.now().isoformat()
            }
            with open(self.last_check_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"保存已见文章ID失败: {e}")
    
    def get_article_id(self, article: dict) -> str:
        """
        生成文章的唯一ID。
        """
        # 使用GUID、链接或标题+发布时间的组合生成唯一ID
        if article.get('guid'):
            return hashlib.md5(article['guid'].encode('utf-8')).hexdigest()
        elif article.get('link'):
            return hashlib.md5(article['link'].encode('utf-8')).hexdigest()
        else:
            # 使用标题+发布时间作为备选
            content = f"{article.get('title', '')}{article.get('published', '')}"
            return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    async def check_feed(self, feed_config: dict) -> List[dict]:
        """
        检查单个RSS订阅源的更新。
        """
        if not feed_config.get('enabled', True):
            return []
        
        feed_name = feed_config.get('name', '未知订阅源')
        feed_url = feed_config.get('url')
        
        if not feed_url:
            logging.warning(f"RSS订阅源 '{feed_name}' 缺少URL配置")
            return []
        
        try:
            logging.info(f"检查RSS订阅源: {feed_name}")
            articles = RSSPayloadParser.parse_rss_feed(feed_url)
            
            new_articles = []
            for article in articles:
                article_id = self.get_article_id(article)
                if article_id not in self.seen_articles:
                    new_articles.append(article)
                    self.seen_articles.add(article_id)
            
            if new_articles:
                logging.info(f"RSS订阅源 '{feed_name}' 发现 {len(new_articles)} 篇新文章")
            
            return new_articles
            
        except Exception as e:
            logging.error(f"检查RSS订阅源 '{feed_name}' 时发生错误: {e}")
            return []
    
    async def check_all_feeds(self):
        """
        检查所有启用的RSS订阅源。
        """
        rss_config = self.config.get('rss', {})
        if not rss_config.get('enabled', False):
            logging.info("RSS监控未启用")
            return
        
        feeds = rss_config.get('feeds', [])
        if not feeds:
            logging.warning("未配置RSS订阅源")
            return
        
        logging.info("开始检查RSS订阅源更新...")
        
        all_new_articles = []
        for feed_config in feeds:
            new_articles = await self.check_feed(feed_config)
            all_new_articles.extend(new_articles)
        
        # 发送通知
        if all_new_articles:
            await self.send_notifications(all_new_articles)
        
        # 保存已见文章ID
        self.save_seen_articles()
        
        logging.info(f"RSS检查完成，共发现 {len(all_new_articles)} 篇新文章")
    
    async def send_notifications(self, articles: List[dict]):
        """
        发送RSS更新通知。
        """
        delay_seconds = self.config.get('global', {}).get('notification_delay_seconds', 0)
        
        for article in articles:
            # 构造标准化的负载
            parsed_payload = {
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
            
            # 格式化消息
            message = RSSPayloadParser.format_rss_notification(parsed_payload)
            
            # 延迟发送（如果配置了延迟）
            if delay_seconds > 0:
                logging.info(f"将在 {delay_seconds} 秒后发送RSS通知...")
                await asyncio.sleep(delay_seconds)
            
            logging.info(f"发送RSS通知: {article.get('title', '无标题')}")
            
            # 发送到各个平台
            if self.config.get('telegram', {}).get('enabled'):
                await self.dispatcher.send_telegram_message(message)
            
            if self.config.get('email', {}).get('enabled'):
                self.dispatcher.send_email(
                    f"RSS新文章: {article.get('title', '无标题')}", 
                    message
                )
            
            if self.config.get('napcat', {}).get('enabled'):
                await self.dispatcher.send_napcat_message(message)
    
    async def start_monitoring(self):
        """
        启动RSS监控服务。
        """
        rss_config = self.config.get('rss', {})
        if not rss_config.get('enabled', False):
            logging.info("RSS监控未启用，跳过启动")
            return
        
        check_interval = rss_config.get('check_interval_minutes', 30)
        logging.info(f"启动RSS监控服务，检查间隔: {check_interval} 分钟")
        
        while True:
            try:
                await self.check_all_feeds()
                await asyncio.sleep(check_interval * 60)  # 转换为秒
            except Exception as e:
                logging.error(f"RSS监控服务发生错误: {e}")
                await asyncio.sleep(60)  # 出错时等待1分钟后重试