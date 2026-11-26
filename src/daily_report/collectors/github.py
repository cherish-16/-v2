"""GitHub 提交采集。

只读令牌、UTC 区间、分页上限。达到上限时记录 warning —— 截断必须可感知，
否则日报看起来完整实则缺条目。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx

from daily_report.models import CommitRecord, ensure_utc
from daily_report.net import get_json

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"
PER_PAGE = 100


def _iso_z(moment: datetime) -> str:
    return ensure_utc(moment).isoformat().replace("+00:00", "Z")


class GitHubCommitSource:
    def __init__(
        self,
        client: httpx.Client,
        token: str,
        max_pages: int = 10,
        branch: str | None = None,
    ) -> None:
        self._client = client
        self._token = token
        self._max_pages = max_pages
        #: 不指定时用仓库默认分支。活跃开发常在 feature 分支上，
        #: 只看默认分支会漏掉大部分提交。
        self._branch = branch

    def collect_commits(
        self,
        owner: str,
        repo: str,
        since: datetime,
        until: datetime,
        *,
        max_pages: int | None = None,
    ) -> list[CommitRecord]:
        start = ensure_utc(since)
        end = ensure_utc(until)
        if start >= end:
            return []
        limit = self._max_pages if max_pages is None else max_pages

        records: list[CommitRecord] = []
        for page_items in self._iter_pages(owner, repo, start, end, limit):
            records.extend(self._to_record(item, owner, repo) for item in page_items)
        return records

    def _iter_pages(
        self,
        owner: str,
        repo: str,
        since: datetime,
        until: datetime,
        max_pages: int,
    ) -> Iterator[list[dict]]:
        for page in range(1, max_pages + 1):
            items = get_json(
                self._client,
                f"{API_BASE}/repos/{owner}/{repo}/commits",
                params={
                    "since": _iso_z(since),
                    "until": _iso_z(until),
                    "per_page": PER_PAGE,
                    "page": page,
                    **({"sha": self._branch} if self._branch else {}),
                },
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            if not items:
                return
            yield items
            if len(items) < PER_PAGE:
                # 短页 = 已到末页。继续翻页只会白白多打一次请求。
                return
        logger.warning(
            "commit collection truncated at %d pages for %s/%s",
            max_pages,
            owner,
            repo,
        )

    @staticmethod
    def _to_record(item: dict, owner: str, repo: str) -> CommitRecord:
        login = (item.get("author") or {}).get("login")
        if not login:
            # 作者账号可能已注销或未关联；用提交内的署名标记为未映射，
            # 保证 author_login 非空且不会被误归到任何成员。
            name = (item.get("commit", {}).get("author") or {}).get("name") or "unknown"
            login = f"{name}(unmapped)"
        committed_at = datetime.fromisoformat(
            item["commit"]["author"]["date"].replace("Z", "+00:00")
        )
        author_email = (item.get("commit", {}).get("author") or {}).get("email")
        return CommitRecord(
            sha=item["sha"],
            author_login=login,
            message=item["commit"]["message"],
            committed_at=committed_at.astimezone(UTC),
            repo=f"{owner}/{repo}",
            author_email=author_email,
        )