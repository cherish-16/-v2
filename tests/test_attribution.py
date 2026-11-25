from datetime import UTC, datetime

from daily_report.generation.attribution import attribute
from daily_report.models import CommitRecord, Member, MessageRecord, TaskRecord

T = datetime(2026, 11, 25, 10, tzinfo=UTC)


def _commit(login, sha="s"):
    return CommitRecord(sha=sha, author_login=login, message="m", committed_at=T, repo="o/r")


def test_groups_commits_by_github_login():
    members = [
        Member(member_id="m1", name="张三", github_login="zhangsan"),
        Member(member_id="m2", name="李四", github_login="lisi"),
    ]
    result = attribute(members, [_commit("zhangsan"), _commit("lisi", "s2")], [], [])
    assert [c.sha for c in result.by_member["m1"].commits] == ["s"]
    assert [c.sha for c in result.by_member["m2"].commits] == ["s2"]


def test_unmapped_member_reported_not_guessed():
    members = [Member(member_id="m2", name="李四")]
    result = attribute(members, [_commit("lisi")], [], [])
    assert result.by_member["m2"].commits == []
    assert [m.member_id for m in result.unmapped] == ["m2"]


def test_unknown_author_not_attributed_to_anyone():
    members = [Member(member_id="m1", name="张三", github_login="zhangsan")]
    result = attribute(members, [_commit("stranger")], [], [])
    assert result.by_member["m1"].commits == []
    assert all(not d.commits for d in result.by_member.values())


def test_messages_not_used_to_infer_collaboration():
    members = [Member(member_id="m1", name="张三", feishu_open_id="ou_1")]
    msg = MessageRecord(
        msg_id="om1",
        sender_open_id="ou_1",
        content="我帮张三改了接口",
        created_at=T,
        chat_id="c1",
    )
    result = attribute(members, [], [], [msg])
    assert result.by_member["m1"].messages == [msg]
    assert result.by_member["m1"].commits == []


def test_tasks_grouped_by_assignee_open_id():
    members = [Member(member_id="m1", name="张三", feishu_open_id="ou_1")]
    task = TaskRecord(
        task_id="t1",
        title="写接口",
        status="done",
        assignee_open_id="ou_1",
        updated_at=T,
    )
    result = attribute(members, [], [task], [])
    assert [t.task_id for t in result.by_member["m1"].tasks] == ["t1"]