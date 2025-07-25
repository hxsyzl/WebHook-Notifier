
# git_payload_parser.py
import hmac
import hashlib
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GitPayloadParser:
    """
    解析并标准化来自不同Git平台（GitHub, GitLab, Gitea）的WebHook负载。
    """

    @staticmethod
    def _verify_signature(payload_body: bytes, secret: str, signature_header: str, algo: str) -> bool:
        """
        验证WebHook签名。
        """
        if not secret:
            logging.warning("未配置WebHook密钥，跳过签名验证。这在生产环境中不安全。")
            return True # 如果没有密钥，则不进行验证 (不推荐用于生产环境)

        if not signature_header:
            logging.error("签名头部缺失。")
            return False

        try:
            if algo == "sha1":
                # GitHub: X-Hub-Signature: sha1=<signature> [6]
                expected_signature = hmac.new(secret.encode(), payload_body, hashlib.sha1).hexdigest()
                return hmac.compare_digest(f"sha1={expected_signature}", signature_header)
            elif algo == "sha256":
                # Gitea: X-Gitea-Signature: <signature> [7, 8]
                expected_signature = hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
                return hmac.compare_digest(expected_signature, signature_header)
            else:
                logging.error(f"不支持的签名算法: {algo}")
                return False
        except Exception as e:
            logging.error(f"签名验证失败: {e}")
            return False

    @staticmethod
    def parse_github_payload(headers: dict, payload: dict, secret: str, raw_body: bytes = None) -> dict or None:
        """
        解析GitHub推送事件负载并标准化。
        GitHub: X-GitHub-Event: push [6]
        """
        # 创建case-insensitive的headers字典
        headers_lower = {k.lower(): v for k, v in headers.items()}
        
        # 使用原始请求体进行签名验证
        if raw_body is not None:
            if not GitPayloadParser._verify_signature(
                raw_body,
                secret,
                headers_lower.get('x-hub-signature', ''),
                "sha1"
            ):
                logging.error("GitHub签名验证失败。")
                return None
        else:
            # 向后兼容：如果没有提供原始请求体，使用旧方法
            if not GitPayloadParser._verify_signature(
                json.dumps(payload, separators=(',', ':')).encode(),
                secret,
                headers_lower.get('x-hub-signature', ''),
                "sha1"
            ):
                logging.error("GitHub签名验证失败。")
                return None

        github_event = headers_lower.get('x-github-event')
        if github_event != 'push':
            logging.info(f"收到非推送的GitHub事件: {github_event}")
            return None

        if not payload.get('commits'):
            logging.info("GitHub推送事件中没有新的提交。")
            return None

        repo_name = payload.get('repository', {}).get('full_name')
        branch = payload.get('ref', '').replace('refs/heads/', '')
        latest_commit = payload.get('head_commit', {}) # [9]
        commit_message = latest_commit.get('message', '').split('\n')[0] if latest_commit.get('message') else '' # 取第一行
        author_name = latest_commit.get('author', {}).get('name')
        commit_url = latest_commit.get('url')
        timestamp = latest_commit.get('timestamp')

        return {
            "platform": "GitHub",
            "repository_name": repo_name,
            "branch": branch,
            "commit_message": commit_message,
            "author_name": author_name,
            "commit_url": commit_url,
            "timestamp": timestamp
        }

    @staticmethod
    def parse_gitlab_payload(headers: dict, payload: dict, secret: str) -> dict or None:
        """
        解析GitLab推送事件负载并标准化。
        GitLab: X-Gitlab-Event: Push Hook [10, 11, 12]
        GitLab通常通过共享密钥验证，这里简化为仅检查密钥是否存在。
        """
        # 创建case-insensitive的headers字典
        headers_lower = {k.lower(): v for k, v in headers.items()}
        
        # GitLab的签名验证通常是基于共享密钥的，这里简化处理，如果配置了secret，则要求secret匹配
        # 实际生产中需要更复杂的验证逻辑，例如检查X-Gitlab-Token头部
        if secret and headers_lower.get('x-gitlab-token') != secret:
            logging.error("GitLab密钥验证失败。")
            return None
        elif secret and not headers_lower.get('x-gitlab-token'):
            logging.error("GitLab密钥未提供，但配置中要求。")
            return None

        gitlab_event = headers_lower.get('x-gitlab-event')
        if gitlab_event != 'Push Hook':
            logging.info(f"收到非推送的GitLab事件: {gitlab_event}")
            return None

        if not payload.get('commits'):
            logging.info("GitLab推送事件中没有新的提交。")
            return None

        repo_name = payload.get('project', {}).get('name')
        branch = payload.get('ref', '').replace('refs/heads/', '')
        latest_commit = payload.get('commits')[-1] if payload.get('commits') else {} # 取最新提交 [11]
        commit_message = latest_commit.get('message', '').split('\n')[0] if latest_commit.get('message') else '' # 取第一行
        author_name = latest_commit.get('author', {}).get('name')
        commit_url = latest_commit.get('url')
        timestamp = latest_commit.get('timestamp')

        return {
            "platform": "GitLab",
            "repository_name": repo_name,
            "branch": branch,
            "commit_message": commit_message,
            "author_name": author_name,
            "commit_url": commit_url,
            "timestamp": timestamp
        }

    @staticmethod
    def parse_gitea_payload(headers: dict, payload: dict, secret: str, raw_body: bytes = None) -> dict or None:
        """
        解析Gitea推送事件负载并标准化。
        Gitea: X-Gitea-Event: push [7, 8]
        """
        # 创建case-insensitive的headers字典
        headers_lower = {k.lower(): v for k, v in headers.items()}
        
        # 使用原始请求体进行签名验证
        if raw_body is not None:
            if not GitPayloadParser._verify_signature(
                raw_body,
                secret,
                headers_lower.get('x-gitea-signature', ''),
                "sha256"
            ):
                logging.error("Gitea签名验证失败。")
                return None
        else:
            # 向后兼容：如果没有提供原始请求体，使用旧方法
            if not GitPayloadParser._verify_signature(
                json.dumps(payload, separators=(',', ':')).encode(),
                secret,
                headers_lower.get('x-gitea-signature', ''),
                "sha256"
            ):
                logging.error("Gitea签名验证失败。")
                return None

        gitea_event = headers_lower.get('x-gitea-event')
        if gitea_event != 'push':
            logging.info(f"收到非推送的Gitea事件: {gitea_event}")
            return None

        if not payload.get('commits'):
            logging.info("Gitea推送事件中没有新的提交。")
            return None

        repo_name = payload.get('repository', {}).get('name')
        branch = payload.get('ref', '').replace('refs/heads/', '')
        latest_commit = payload.get('commits')[-1] if payload.get('commits') else {} # 取最新提交 [8]
        commit_message = latest_commit.get('message', '').split('\n')[0] if latest_commit.get('message') else '' # 取第一行
        author_name = latest_commit.get('author', {}).get('name')
        commit_url = latest_commit.get('url')
        timestamp = latest_commit.get('timestamp')

        return {
            "platform": "Gitea",
            "repository_name": repo_name,
            "branch": branch,
            "commit_message": commit_message,
            "author_name": author_name,
            "commit_url": commit_url,
            "timestamp": timestamp
        }

    @staticmethod
    def parse_gogs_payload(headers: dict, payload: dict, secret: str) -> dict or None:
        """
        解析Gogs推送事件负载并标准化。
        Gogs: X-Gogs-Event: push
        """
        # 创建case-insensitive的headers字典
        headers_lower = {k.lower(): v for k, v in headers.items()}

        # Gogs的签名验证
        if secret:
            signature = headers_lower.get('x-gogs-signature')
            if not signature:
                logging.error("Gogs密钥已配置，但请求中缺少 x-gogs-signature 头部。")
                return None
            
            expected_signature = hmac.new(secret.encode('utf-8'), json.dumps(payload, separators=(',', ':')).encode('utf-8'), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected_signature):
                logging.error("Gogs签名验证失败。")
                return None

        gogs_event = headers_lower.get('x-gogs-event')
        if gogs_event != 'push':
            logging.info(f"收到非推送的Gogs事件: {gogs_event}")
            return None

        if not payload.get('commits'):
            logging.info("Gogs推送事件中没有新的提交。")
            return None

        repo_name = payload.get('repository', {}).get('full_name')
        branch = payload.get('ref', '').replace('refs/heads/', '')
        latest_commit = payload.get('commits')[-1] if payload.get('commits') else {}
        commit_message = latest_commit.get('message', '').split('\n')[0] if latest_commit.get('message') else ''
        author_name = latest_commit.get('author', {}).get('name')
        commit_url = latest_commit.get('url')
        timestamp = latest_commit.get('timestamp')

        return {
            "platform": "Gogs",
            "repository_name": repo_name,
            "branch": branch,
            "commit_message": commit_message,
            "author_name": author_name,
            "commit_url": commit_url,
            "timestamp": timestamp
        }

    @staticmethod
    def format_notification(parsed_payload: dict) -> str:
        """
        格式化Git WebHook的通知消息。
        """
        return (
            f"文章更新通知！\n\n"
            f"平台: {parsed_payload['platform']}\n"
            f"仓库: {parsed_payload['repository_name']}\n"
            f"分支: {parsed_payload['branch']}\n"
            f"提交信息: {parsed_payload['commit_message']}\n"
            f"作者: {parsed_payload['author_name']}\n"
            f"提交链接: {parsed_payload['commit_url']}\n"
            f"时间: {parsed_payload['timestamp']}"
        )
