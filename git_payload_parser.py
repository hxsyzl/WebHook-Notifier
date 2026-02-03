
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
        解析GitHub WebHook事件负载并标准化。
        支持的事件类型: push, workflow_run, pull_request, release, create, delete, issues, issue_comment
        GitHub: X-GitHub-Event: <event_type> [6]
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
        repo_name = payload.get('repository', {}).get('full_name')
        
        # 根据不同事件类型解析负载
        if github_event == 'push':
            if not payload.get('commits'):
                logging.info("GitHub推送事件中没有新的提交。")
                return None
            
            branch = payload.get('ref', '').replace('refs/heads/', '')
            latest_commit = payload.get('head_commit', {})
            commit_message = latest_commit.get('message', '').split('\n')[0] if latest_commit.get('message') else ''
            author_name = latest_commit.get('author', {}).get('name')
            commit_url = latest_commit.get('url')
            timestamp = latest_commit.get('timestamp')
            
            return {
                "platform": "GitHub",
                "event_type": "push",
                "repository_name": repo_name,
                "branch": branch,
                "commit_message": commit_message,
                "author_name": author_name,
                "commit_url": commit_url,
                "timestamp": timestamp
            }
        
        elif github_event == 'workflow_run':
            # GitHub Actions工作流运行事件
            workflow = payload.get('workflow', {})
            workflow_run = payload.get('workflow_run', {})
            sender = payload.get('sender', {})
            
            return {
                "platform": "GitHub",
                "event_type": "workflow_run",
                "repository_name": repo_name,
                "workflow_name": workflow.get('name', 'Unknown'),
                "workflow_status": workflow_run.get('conclusion', workflow_run.get('status', 'Unknown')),
                "workflow_url": workflow_run.get('html_url', ''),
                "branch": workflow_run.get('head_branch', ''),
                "commit_message": workflow_run.get('head_commit', {}).get('message', '').split('\n')[0] if workflow_run.get('head_commit', {}).get('message') else '',
                "author_name": sender.get('login', ''),
                "timestamp": workflow_run.get('created_at', '')
            }
        
        elif github_event == 'pull_request':
            # Pull Request事件
            pr = payload.get('pull_request', {})
            sender = payload.get('sender', {})
            
            return {
                "platform": "GitHub",
                "event_type": "pull_request",
                "repository_name": repo_name,
                "pr_number": pr.get('number'),
                "pr_title": pr.get('title', ''),
                "pr_state": pr.get('state', ''),
                "pr_url": pr.get('html_url', ''),
                "branch": pr.get('head', {}).get('ref', ''),
                "author_name": sender.get('login', ''),
                "timestamp": pr.get('updated_at', '')
            }
        
        elif github_event == 'release':
            # Release事件
            release = payload.get('release', {})
            sender = payload.get('sender', {})
            
            return {
                "platform": "GitHub",
                "event_type": "release",
                "repository_name": repo_name,
                "release_tag": release.get('tag_name', ''),
                "release_name": release.get('name', ''),
                "release_url": release.get('html_url', ''),
                "author_name": sender.get('login', ''),
                "timestamp": release.get('published_at', '')
            }
        
        elif github_event == 'create':
            # 创建分支/标签事件
            ref_type = payload.get('ref_type', '')
            ref = payload.get('ref', '')
            sender = payload.get('sender', {})
            
            return {
                "platform": "GitHub",
                "event_type": "create",
                "repository_name": repo_name,
                "ref_type": ref_type,
                "ref": ref,
                "branch": ref if ref_type == 'branch' else '',
                "author_name": sender.get('login', ''),
                "timestamp": payload.get('repository', {}).get('updated_at', '')
            }
        
        elif github_event == 'delete':
            # 删除分支/标签事件
            ref_type = payload.get('ref_type', '')
            ref = payload.get('ref', '')
            sender = payload.get('sender', {})
            
            return {
                "platform": "GitHub",
                "event_type": "delete",
                "repository_name": repo_name,
                "ref_type": ref_type,
                "ref": ref,
                "branch": ref if ref_type == 'branch' else '',
                "author_name": sender.get('login', ''),
                "timestamp": payload.get('repository', {}).get('updated_at', '')
            }
        
        elif github_event == 'issues':
            # Issue事件
            issue = payload.get('issue', {})
            sender = payload.get('sender', {})
            action = payload.get('action', '')
            
            return {
                "platform": "GitHub",
                "event_type": "issues",
                "repository_name": repo_name,
                "action": action,
                "issue_number": issue.get('number'),
                "issue_title": issue.get('title', ''),
                "issue_url": issue.get('html_url', ''),
                "author_name": sender.get('login', ''),
                "timestamp": issue.get('updated_at', '')
            }
        
        elif github_event == 'issue_comment':
            # Issue评论事件
            issue = payload.get('issue', {})
            comment = payload.get('comment', {})
            sender = payload.get('sender', {})
            action = payload.get('action', '')
            
            return {
                "platform": "GitHub",
                "event_type": "issue_comment",
                "repository_name": repo_name,
                "action": action,
                "issue_number": issue.get('number'),
                "issue_title": issue.get('title', ''),
                "comment_body": comment.get('body', '')[:200] + '...' if len(comment.get('body', '')) > 200 else comment.get('body', ''),
                "comment_url": comment.get('html_url', ''),
                "author_name": sender.get('login', ''),
                "timestamp": comment.get('updated_at', '')
            }
        
        else:
            logging.info(f"收到未处理的GitHub事件: {github_event}")
            return None

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
    def format_notification(parsed_payload: dict, custom_titles: dict = None) -> str:
        """
        格式化Git WebHook的通知消息。
        
        Args:
            parsed_payload: 解析后的payload字典
            custom_titles: 自定义标题配置字典，包含各种事件类型的标题
        """
        event_type = parsed_payload.get('event_type', 'unknown')
        platform = parsed_payload['platform']
        repo_name = parsed_payload['repository_name']
        
        # 默认标题
        default_titles = {
            'push': "📦 新提交推送通知",
            'workflow_run': "🔄 GitHub Actions 工作流通知",
            'pull_request': "🔀 Pull Request 通知",
            'release': "🎉 Release 发布通知",
            'create': "➕ 创建通知",
            'delete': "🗑️ 删除通知",
            'issues': "📋 Issue 通知",
            'issue_comment': "💬 Issue 评论通知",
            'unknown': "📢 GitHub 事件通知"
        }
        
        # 使用自定义标题或默认标题
        titles = custom_titles if custom_titles else {}
        title = titles.get(f'{event_type}_title', default_titles.get(event_type, default_titles['unknown']))
        
        if event_type == 'push':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"分支: {parsed_payload['branch']}\n"
                f"提交信息: {parsed_payload['commit_message']}\n"
                f"作者: {parsed_payload['author_name']}\n"
                f"提交链接: {parsed_payload['commit_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'workflow_run':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"工作流: {parsed_payload['workflow_name']}\n"
                f"状态: {parsed_payload['workflow_status']}\n"
                f"分支: {parsed_payload['branch']}\n"
                f"提交信息: {parsed_payload['commit_message']}\n"
                f"触发者: {parsed_payload['author_name']}\n"
                f"详情链接: {parsed_payload['workflow_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'pull_request':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"PR编号: #{parsed_payload['pr_number']}\n"
                f"标题: {parsed_payload['pr_title']}\n"
                f"状态: {parsed_payload['pr_state']}\n"
                f"分支: {parsed_payload['branch']}\n"
                f"作者: {parsed_payload['author_name']}\n"
                f"链接: {parsed_payload['pr_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'release':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"标签: {parsed_payload['release_tag']}\n"
                f"名称: {parsed_payload['release_name']}\n"
                f"发布者: {parsed_payload['author_name']}\n"
                f"链接: {parsed_payload['release_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'create':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"类型: {parsed_payload['ref_type']}\n"
                f"名称: {parsed_payload['ref']}\n"
                f"操作者: {parsed_payload['author_name']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'delete':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"类型: {parsed_payload['ref_type']}\n"
                f"名称: {parsed_payload['ref']}\n"
                f"操作者: {parsed_payload['author_name']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'issues':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"操作: {parsed_payload['action']}\n"
                f"Issue编号: #{parsed_payload['issue_number']}\n"
                f"标题: {parsed_payload['issue_title']}\n"
                f"操作者: {parsed_payload['author_name']}\n"
                f"链接: {parsed_payload['issue_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'issue_comment':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"操作: {parsed_payload['action']}\n"
                f"Issue编号: #{parsed_payload['issue_number']}\n"
                f"Issue标题: {parsed_payload['issue_title']}\n"
                f"评论内容: {parsed_payload['comment_body']}\n"
                f"评论者: {parsed_payload['author_name']}\n"
                f"链接: {parsed_payload['comment_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        else:
            # 默认格式（兼容旧版本）
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"事件类型: {event_type}\n"
                f"时间: {parsed_payload.get('timestamp', '')}"
            )
