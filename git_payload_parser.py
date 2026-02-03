
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
    def _parse_generic_github_event(github_event: str, payload: dict) -> dict:
        """
        通用回退处理器，用于处理未适配的 GitHub 事件。
        自动提取 payload 中的常见字段并返回标准化格式。
        """
        sender = payload.get('sender', {})
        repository = payload.get('repository', {})
        action = payload.get('action', '')
        
        # 提取常见字段
        result = {
            "platform": "GitHub",
            "event_type": github_event,
            "repository_name": repository.get('full_name', repository.get('name', 'Unknown')),
            "action": action,
            "author_name": sender.get('login', 'Unknown'),
            "timestamp": payload.get('updated_at') or payload.get('created_at') or repository.get('updated_at', ''),
            "repository_url": repository.get('html_url', ''),
            "repository_description": repository.get('description', ''),
        }
        
        # 尝试提取更多有用的字段
        if 'pull_request' in payload:
            pr = payload['pull_request']
            result.update({
                "pr_number": pr.get('number'),
                "pr_title": pr.get('title', ''),
                "pr_url": pr.get('html_url', ''),
            })
        
        if 'issue' in payload:
            issue = payload['issue']
            result.update({
                "issue_number": issue.get('number'),
                "issue_title": issue.get('title', ''),
                "issue_url": issue.get('html_url', ''),
            })
        
        if 'comment' in payload:
            comment = payload['comment']
            body = comment.get('body', '')
            result.update({
                "comment_body": body[:200] + '...' if len(body) > 200 else body,
                "comment_url": comment.get('html_url', ''),
            })
        
        if 'release' in payload:
            release = payload['release']
            result.update({
                "release_tag": release.get('tag_name', ''),
                "release_name": release.get('name', ''),
                "release_url": release.get('html_url', ''),
            })
        
        if 'check_suite' in payload:
            check_suite = payload['check_suite']
            result.update({
                "head_branch": check_suite.get('head_branch', ''),
                "head_sha": check_suite.get('head_sha', ''),
                "status": check_suite.get('status', ''),
                "conclusion": check_suite.get('conclusion', ''),
            })
        
        if 'check_run' in payload:
            check_run = payload['check_run']
            result.update({
                "head_branch": check_run.get('head_branch', ''),
                "head_sha": check_run.get('head_sha', ''),
                "status": check_run.get('status', ''),
                "conclusion": check_run.get('conclusion', ''),
            })
        
        if 'deployment' in payload:
            deployment = payload['deployment']
            result.update({
                "environment": deployment.get('environment', ''),
                "state": deployment.get('status', ''),
                "head_branch": deployment.get('ref', ''),
                "head_sha": deployment.get('sha', '')[:7] if deployment.get('sha') else '',
            })
        
        if 'milestone' in payload:
            milestone = payload['milestone']
            result.update({
                "milestone_number": milestone.get('number'),
                "milestone_title": milestone.get('title', ''),
                "milestone_state": milestone.get('state', ''),
            })
        
        if 'label' in payload:
            label = payload['label']
            result.update({
                "label_name": label.get('name', ''),
                "label_color": label.get('color', ''),
            })
        
        if 'member' in payload:
            member = payload['member']
            result.update({
                "member_name": member.get('login', ''),
                "member_url": member.get('html_url', ''),
            })
        
        if 'forkee' in payload:
            forkee = payload['forkee']
            result.update({
                "fork_name": forkee.get('full_name', ''),
                "fork_url": forkee.get('html_url', ''),
            })
        
        # 记录日志
        logging.info(f"使用通用处理器处理未适配的 GitHub 事件: {github_event}")
        
        return result

    @staticmethod
    def parse_github_payload(headers: dict, payload: dict, secret: str, raw_body: bytes = None) -> dict or None:
        """
        解析GitHub WebHook事件负载并标准化。
        支持的事件类型: push, workflow_run, pull_request, release, create, delete, issues, issue_comment,
                        check_suite, check_run, fork, watch, commit_comment, pull_request_review,
                        pull_request_review_comment, deployment, status, repository, member, milestone, label
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
                "artifacts_url": workflow_run.get('artifacts_url', ''),
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
            
            # 解析 assets 文件信息
            assets = release.get('assets', [])
            asset_info = []
            for asset in assets:
                asset_info.append({
                    'name': asset.get('name', ''),
                    'size': asset.get('size', 0),
                    'download_url': asset.get('browser_download_url', ''),
                    'content_type': asset.get('content_type', '')
                })
            
            return {
                "platform": "GitHub",
                "event_type": "release",
                "repository_name": repo_name,
                "release_tag": release.get('tag_name', ''),
                "release_name": release.get('name', ''),
                "release_url": release.get('html_url', ''),
                "author_name": sender.get('login', ''),
                "timestamp": release.get('published_at', ''),
                "assets": asset_info
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
        
        elif github_event == 'check_suite':
            # Check Suite事件（GitHub Actions检查套件）
            check_suite = payload.get('check_suite', {})
            sender = payload.get('sender', {})
            action = payload.get('action', '')
            
            return {
                "platform": "GitHub",
                "event_type": "check_suite",
                "repository_name": repo_name,
                "action": action,
                "check_suite_id": check_suite.get('id'),
                "head_branch": check_suite.get('head_branch', ''),
                "head_sha": check_suite.get('head_sha', ''),
                "conclusion": check_suite.get('conclusion', ''),
                "status": check_suite.get('status', ''),
                "check_suite_url": check_suite.get('html_url', ''),
                "author_name": sender.get('login', ''),
                "timestamp": check_suite.get('created_at', '')
            }
        
        elif github_event == 'check_run':
            # Check Run事件（GitHub Actions检查运行）
            check_run = payload.get('check_run', {})
            sender = payload.get('sender', {})
            action = payload.get('action', '')
            
            return {
                "platform": "GitHub",
                "event_type": "check_run",
                "repository_name": repo_name,
                "action": action,
                "check_run_id": check_run.get('id'),
                "name": check_run.get('name', ''),
                "head_branch": check_run.get('head_branch', ''),
                "head_sha": check_run.get('head_sha', ''),
                "conclusion": check_run.get('conclusion', ''),
                "status": check_run.get('status', ''),
                "check_run_url": check_run.get('html_url', ''),
                "author_name": sender.get('login', ''),
                "timestamp": check_run.get('started_at', '')
            }
        
        elif github_event == 'fork':
            # Fork事件
            forkee = payload.get('forkee', {})
            sender = payload.get('sender', {})
            
            return {
                "platform": "GitHub",
                "event_type": "fork",
                "repository_name": repo_name,
                "fork_name": forkee.get('full_name', ''),
                "fork_url": forkee.get('html_url', ''),
                "author_name": sender.get('login', ''),
                "timestamp": payload.get('repository', {}).get('updated_at', '')
            }
        
        elif github_event == 'watch':
            # Watch/Star事件
            sender = payload.get('sender', {})
            action = payload.get('action', '')
            
            return {
                "platform": "GitHub",
                "event_type": "watch",
                "repository_name": repo_name,
                "action": action,
                "author_name": sender.get('login', ''),
                "timestamp": payload.get('repository', {}).get('updated_at', '')
            }
        
        elif github_event == 'commit_comment':
            # Commit评论事件
            comment = payload.get('comment', {})
            sender = payload.get('sender', {})
            action = payload.get('action', '')
            
            return {
                "platform": "GitHub",
                "event_type": "commit_comment",
                "repository_name": repo_name,
                "action": action,
                "commit_id": comment.get('commit_id', '')[:7],
                "comment_body": comment.get('body', '')[:200] + '...' if len(comment.get('body', '')) > 200 else comment.get('body', ''),
                "comment_url": comment.get('html_url', ''),
                "author_name": sender.get('login', ''),
                "timestamp": comment.get('created_at', '')
            }
        
        elif github_event == 'pull_request_review':
            # Pull Request Review事件
            review = payload.get('review', {})
            pr = payload.get('pull_request', {})
            sender = payload.get('sender', {})
            action = payload.get('action', '')
            
            return {
                "platform": "GitHub",
                "event_type": "pull_request_review",
                "repository_name": repo_name,
                "action": action,
                "pr_number": pr.get('number'),
                "pr_title": pr.get('title', ''),
                "review_state": review.get('state', ''),
                "review_body": review.get('body', '')[:200] + '...' if len(review.get('body', '')) > 200 else review.get('body', ''),
                "review_url": review.get('html_url', ''),
                "author_name": sender.get('login', ''),
                "timestamp": review.get('submitted_at', '')
            }
        
        elif github_event == 'pull_request_review_comment':
            # Pull Request Review评论事件
            comment = payload.get('comment', {})
            pr = payload.get('pull_request', {})
            sender = payload.get('sender', {})
            action = payload.get('action', '')
            
            return {
                "platform": "GitHub",
                "event_type": "pull_request_review_comment",
                "repository_name": repo_name,
                "action": action,
                "pr_number": pr.get('number'),
                "pr_title": pr.get('title', ''),
                "comment_body": comment.get('body', '')[:200] + '...' if len(comment.get('body', '')) > 200 else comment.get('body', ''),
                "comment_url": comment.get('html_url', ''),
                "author_name": sender.get('login', ''),
                "timestamp": comment.get('created_at', '')
            }
        
        elif github_event == 'deployment':
            # Deployment事件
            deployment = payload.get('deployment', {})
            sender = payload.get('sender', {})
            
            return {
                "platform": "GitHub",
                "event_type": "deployment",
                "repository_name": repo_name,
                "deployment_id": deployment.get('id'),
                "environment": deployment.get('environment', ''),
                "task": deployment.get('task', ''),
                "state": deployment.get('status', ''),
                "deployment_url": deployment.get('url', ''),
                "head_branch": deployment.get('ref', ''),
                "head_sha": deployment.get('sha', '')[:7],
                "author_name": sender.get('login', ''),
                "timestamp": deployment.get('created_at', '')
            }
        
        elif github_event == 'status':
            # Status事件（提交状态更新）
            sender = payload.get('sender', {})
            
            return {
                "platform": "GitHub",
                "event_type": "status",
                "repository_name": repo_name,
                "state": payload.get('state', ''),
                "target_url": payload.get('target_url', ''),
                "description": payload.get('description', ''),
                "context": payload.get('context', ''),
                "sha": payload.get('sha', '')[:7],
                "branches": [b.get('name', '') for b in payload.get('branches', [])],
                "author_name": sender.get('login', ''),
                "timestamp": payload.get('updated_at', '')
            }
        
        elif github_event == 'repository':
            # Repository事件（仓库创建/删除/归档等）
            sender = payload.get('sender', {})
            action = payload.get('action', '')
            
            return {
                "platform": "GitHub",
                "event_type": "repository",
                "repository_name": repo_name,
                "action": action,
                "repository_url": payload.get('repository', {}).get('html_url', ''),
                "repository_description": payload.get('repository', {}).get('description', ''),
                "author_name": sender.get('login', ''),
                "timestamp": payload.get('repository', {}).get('updated_at', '')
            }
        
        elif github_event == 'member':
            # Member事件（成员添加/删除）
            member = payload.get('member', {})
            sender = payload.get('sender', {})
            action = payload.get('action', '')
            
            return {
                "platform": "GitHub",
                "event_type": "member",
                "repository_name": repo_name,
                "action": action,
                "member_name": member.get('login', ''),
                "member_url": member.get('html_url', ''),
                "author_name": sender.get('login', ''),
                "timestamp": payload.get('repository', {}).get('updated_at', '')
            }
        
        elif github_event == 'milestone':
            # Milestone事件
            milestone = payload.get('milestone', {})
            sender = payload.get('sender', {})
            action = payload.get('action', '')
            
            return {
                "platform": "GitHub",
                "event_type": "milestone",
                "repository_name": repo_name,
                "action": action,
                "milestone_number": milestone.get('number'),
                "milestone_title": milestone.get('title', ''),
                "milestone_state": milestone.get('state', ''),
                "milestone_url": milestone.get('html_url', ''),
                "author_name": sender.get('login', ''),
                "timestamp": milestone.get('updated_at', '')
            }
        
        elif github_event == 'label':
            # Label事件
            label = payload.get('label', {})
            sender = payload.get('sender', {})
            action = payload.get('action', '')
            
            return {
                "platform": "GitHub",
                "event_type": "label",
                "repository_name": repo_name,
                "action": action,
                "label_name": label.get('name', ''),
                "label_color": label.get('color', ''),
                "label_url": label.get('url', ''),
                "author_name": sender.get('login', ''),
                "timestamp": payload.get('repository', {}).get('updated_at', '')
            }
        
        else:
            # 使用通用回退处理器处理未适配的事件
            return GitPayloadParser._parse_generic_github_event(github_event, payload)

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
            'check_suite': "✅ 检查套件通知",
            'check_run': "🔍 检查运行通知",
            'fork': "🍴 Fork 通知",
            'watch': "⭐ Star 通知",
            'commit_comment': "💭 提交评论通知",
            'pull_request_review': "👀 PR 评审通知",
            'pull_request_review_comment': "💬 PR 评审评论通知",
            'deployment': "🚀 部署通知",
            'status': "📊 状态更新通知",
            'repository': "📁 仓库通知",
            'member': "👥 成员通知",
            'milestone': "🎯 里程碑通知",
            'label': "🏷️ 标签通知",
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
            message = (
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
            
            # 添加工件链接
            artifacts_url = parsed_payload.get('artifacts_url', '')
            if artifacts_url:
                message += f"\n\n📦 工件链接: {artifacts_url}"
            
            return message
        
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
            message = (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"标签: {parsed_payload['release_tag']}\n"
                f"名称: {parsed_payload['release_name']}\n"
                f"发布者: {parsed_payload['author_name']}\n"
                f"链接: {parsed_payload['release_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
            
            # 添加附件文件信息
            assets = parsed_payload.get('assets', [])
            if assets:
                message += "\n\n📎 附件文件:"
                for i, asset in enumerate(assets, 1):
                    size_mb = asset['size'] / (1024 * 1024) if asset['size'] else 0
                    size_str = f"{size_mb:.2f} MB" if size_mb >= 1 else f"{asset['size']} B"
                    message += f"\n  {i}. {asset['name']} ({size_str})"
                    message += f"\n     下载: {asset['download_url']}"
            
            return message
        
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
        
        elif event_type == 'check_suite':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"操作: {parsed_payload['action']}\n"
                f"分支: {parsed_payload['head_branch']}\n"
                f"提交SHA: {parsed_payload['head_sha'][:7]}\n"
                f"状态: {parsed_payload['status']}\n"
                f"结论: {parsed_payload['conclusion'] or '进行中'}\n"
                f"触发者: {parsed_payload['author_name']}\n"
                f"链接: {parsed_payload['check_suite_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'check_run':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"操作: {parsed_payload['action']}\n"
                f"检查名称: {parsed_payload['name']}\n"
                f"分支: {parsed_payload['head_branch']}\n"
                f"提交SHA: {parsed_payload['head_sha'][:7]}\n"
                f"状态: {parsed_payload['status']}\n"
                f"结论: {parsed_payload['conclusion'] or '进行中'}\n"
                f"触发者: {parsed_payload['author_name']}\n"
                f"链接: {parsed_payload['check_run_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'fork':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"Fork仓库: {parsed_payload['fork_name']}\n"
                f"Fork链接: {parsed_payload['fork_url']}\n"
                f"操作者: {parsed_payload['author_name']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'watch':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"操作: {parsed_payload['action']}\n"
                f"操作者: {parsed_payload['author_name']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'commit_comment':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"操作: {parsed_payload['action']}\n"
                f"提交SHA: {parsed_payload['commit_id']}\n"
                f"评论内容: {parsed_payload['comment_body']}\n"
                f"评论者: {parsed_payload['author_name']}\n"
                f"链接: {parsed_payload['comment_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'pull_request_review':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"操作: {parsed_payload['action']}\n"
                f"PR编号: #{parsed_payload['pr_number']}\n"
                f"PR标题: {parsed_payload['pr_title']}\n"
                f"评审状态: {parsed_payload['review_state']}\n"
                f"评审内容: {parsed_payload['review_body']}\n"
                f"评审者: {parsed_payload['author_name']}\n"
                f"链接: {parsed_payload['review_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'pull_request_review_comment':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"操作: {parsed_payload['action']}\n"
                f"PR编号: #{parsed_payload['pr_number']}\n"
                f"PR标题: {parsed_payload['pr_title']}\n"
                f"评论内容: {parsed_payload['comment_body']}\n"
                f"评论者: {parsed_payload['author_name']}\n"
                f"链接: {parsed_payload['comment_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'deployment':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"部署ID: {parsed_payload['deployment_id']}\n"
                f"环境: {parsed_payload['environment']}\n"
                f"任务: {parsed_payload['task']}\n"
                f"状态: {parsed_payload['state']}\n"
                f"分支: {parsed_payload['head_branch']}\n"
                f"提交SHA: {parsed_payload['head_sha']}\n"
                f"操作者: {parsed_payload['author_name']}\n"
                f"链接: {parsed_payload['deployment_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'status':
            branches = ', '.join(parsed_payload.get('branches', []))
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"状态: {parsed_payload['state']}\n"
                f"上下文: {parsed_payload['context']}\n"
                f"描述: {parsed_payload['description']}\n"
                f"提交SHA: {parsed_payload['sha']}\n"
                f"分支: {branches}\n"
                f"链接: {parsed_payload['target_url']}\n"
                f"操作者: {parsed_payload['author_name']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'repository':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"操作: {parsed_payload['action']}\n"
                f"描述: {parsed_payload['repository_description']}\n"
                f"操作者: {parsed_payload['author_name']}\n"
                f"链接: {parsed_payload['repository_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'member':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"操作: {parsed_payload['action']}\n"
                f"成员: {parsed_payload['member_name']}\n"
                f"操作者: {parsed_payload['author_name']}\n"
                f"成员链接: {parsed_payload['member_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'milestone':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"操作: {parsed_payload['action']}\n"
                f"里程碑编号: #{parsed_payload['milestone_number']}\n"
                f"里程碑标题: {parsed_payload['milestone_title']}\n"
                f"状态: {parsed_payload['milestone_state']}\n"
                f"操作者: {parsed_payload['author_name']}\n"
                f"链接: {parsed_payload['milestone_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        elif event_type == 'label':
            return (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"操作: {parsed_payload['action']}\n"
                f"标签名称: {parsed_payload['label_name']}\n"
                f"标签颜色: #{parsed_payload['label_color']}\n"
                f"操作者: {parsed_payload['author_name']}\n"
                f"链接: {parsed_payload['label_url']}\n"
                f"时间: {parsed_payload['timestamp']}"
            )
        
        else:
            # 通用事件格式（用于未适配的事件类型）
            message = (
                f"{title}\n\n"
                f"平台: {platform}\n"
                f"仓库: {repo_name}\n"
                f"事件类型: {event_type}\n"
            )
            
            # 添加操作信息
            if parsed_payload.get('action'):
                message += f"操作: {parsed_payload['action']}\n"
            
            # 添加操作者
            if parsed_payload.get('author_name'):
                message += f"操作者: {parsed_payload['author_name']}\n"
            
            # 根据可用字段添加更多信息
            if parsed_payload.get('pr_number'):
                message += f"PR编号: #{parsed_payload['pr_number']}\n"
                if parsed_payload.get('pr_title'):
                    message += f"PR标题: {parsed_payload['pr_title']}\n"
            
            if parsed_payload.get('issue_number'):
                message += f"Issue编号: #{parsed_payload['issue_number']}\n"
                if parsed_payload.get('issue_title'):
                    message += f"Issue标题: {parsed_payload['issue_title']}\n"
            
            if parsed_payload.get('comment_body'):
                message += f"评论内容: {parsed_payload['comment_body']}\n"
            
            if parsed_payload.get('release_tag'):
                message += f"发布标签: {parsed_payload['release_tag']}\n"
            
            if parsed_payload.get('head_branch'):
                message += f"分支: {parsed_payload['head_branch']}\n"
            
            if parsed_payload.get('head_sha'):
                message += f"提交SHA: {parsed_payload['head_sha'][:7]}\n"
            
            if parsed_payload.get('status'):
                message += f"状态: {parsed_payload['status']}\n"
            
            if parsed_payload.get('conclusion'):
                message += f"结论: {parsed_payload['conclusion']}\n"
            
            if parsed_payload.get('environment'):
                message += f"环境: {parsed_payload['environment']}\n"
            
            if parsed_payload.get('milestone_title'):
                message += f"里程碑: {parsed_payload['milestone_title']}\n"
            
            if parsed_payload.get('label_name'):
                message += f"标签: {parsed_payload['label_name']}\n"
            
            if parsed_payload.get('member_name'):
                message += f"成员: {parsed_payload['member_name']}\n"
            
            if parsed_payload.get('fork_name'):
                message += f"Fork仓库: {parsed_payload['fork_name']}\n"
            
            # 添加链接
            links = []
            if parsed_payload.get('repository_url'):
                links.append(f"仓库: {parsed_payload['repository_url']}")
            if parsed_payload.get('pr_url'):
                links.append(f"PR: {parsed_payload['pr_url']}")
            if parsed_payload.get('issue_url'):
                links.append(f"Issue: {parsed_payload['issue_url']}")
            if parsed_payload.get('comment_url'):
                links.append(f"评论: {parsed_payload['comment_url']}")
            if parsed_payload.get('release_url'):
                links.append(f"发布: {parsed_payload['release_url']}")
            if parsed_payload.get('milestone_url'):
                links.append(f"里程碑: {parsed_payload['milestone_url']}")
            if parsed_payload.get('label_url'):
                links.append(f"标签: {parsed_payload['label_url']}")
            if parsed_payload.get('member_url'):
                links.append(f"成员: {parsed_payload['member_url']}")
            if parsed_payload.get('fork_url'):
                links.append(f"Fork: {parsed_payload['fork_url']}")
            
            if links:
                message += f"\n链接:\n" + "\n".join(f"  - {link}" for link in links)
            
            # 添加时间
            if parsed_payload.get('timestamp'):
                message += f"\n\n时间: {parsed_payload['timestamp']}"
            
            # 添加提示
            message += "\n\n💡 此事件类型尚未完全适配，显示的是通用格式。"
            
            return message
