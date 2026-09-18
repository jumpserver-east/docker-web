#!/usr/bin/env python3
"""Email an image build result to the workflow actor."""

from email.message import EmailMessage
from email.utils import parseaddr
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


REPOSITORIES = {f'jumpserver-east/{name}' for name in
                ('jumpserver', 'lion', 'koko', 'lina', 'luna', 'docker-web')}
RESULTS = {'success': '成功', 'failure': '失败', 'cancelled': '已取消'}


def address(value):
    """Accept one deliverable address; never treat GitHub noreply as a mailbox."""
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        return ''
    _, parsed = parseaddr(value)
    if parsed != value or not re.fullmatch(r'[^\s@<>,;]+@[^\s@<>,;]+\.[^\s@<>,;]+', parsed):
        return ''
    local, domain = parsed.lower().rsplit('@', 1)
    if domain == 'users.noreply.github.com' or local in ('noreply', 'no-reply'):
        return ''
    return parsed


def github(path, token):
    request = urllib.request.Request('https://api.github.com/' + path, headers={
        'Accept': 'application/vnd.github+json',
        'Authorization': 'Bearer ' + token,
        'X-GitHub-Api-Version': '2022-11-28',
    })
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError):
        # A missing public email must not redirect the notification to another user.
        return {}


def origin(env, event):
    forwarded = env.get('ORIGIN_CONTEXT', '')
    actor = (env.get('NOTIFICATION_ACTOR') or env.get('GITHUB_TRIGGERING_ACTOR') or
             env.get('GITHUB_ACTOR', ''))
    rerun = int(env.get('GITHUB_RUN_ATTEMPT') or '1') > 1
    if forwarded:
        context = json.loads(forwarded)
    else:
        event_name = env.get('NOTIFICATION_EVENT') or env.get('GITHUB_EVENT_NAME', '')
        run = event.get('workflow_run', {}) if event_name == 'workflow_run' else {}
        context = {
            'repository': env.get('SOURCE_REPOSITORY') or env['GITHUB_REPOSITORY'],
            'branch': env.get('SOURCE_BRANCH', ''),
            'ref': env.get('SOURCE_REF', ''),
            'event': run.get('event') or event_name,
            'actor': (run.get('triggering_actor') or {}).get('login') or
                     (run.get('actor') or {}).get('login') or actor,
        }
    if not isinstance(context, dict) or context.get('repository') not in REPOSITORIES:
        raise ValueError('Notification source must be a supported jumpserver-east repository')
    if rerun:
        context['actor'] = actor
    for key in ('branch', 'ref', 'event', 'actor'):
        if not isinstance(context.get(key, ''), str) or any(ord(c) < 32 for c in context.get(key, '')):
            raise ValueError('Invalid notification source metadata')
    return context


def recipient(context, event, mappings, token, api=github):
    """Resolve a deliverable address for the workflow actor only."""
    mappings = {name.lower(): value for name, value in mappings.items()}
    actor = context.get('actor', '')
    if not actor:
        return ''
    mapped = address(mappings.get(actor.lower(), ''))
    return mapped or address(api('users/' + urllib.parse.quote(actor, safe=''), token).get('email'))


def message(env, context, sources, destination):
    result = env['BUILD_RESULT']
    phase = '构建请求提交' if env.get('NOTIFICATION_PHASE') == 'dispatch' else '镜像构建'
    title = f"[{phase}{RESULTS[result]}] {env['GITHUB_REPOSITORY']} · {context.get('branch') or context.get('ref') or '未确定来源'}"
    mail = EmailMessage()
    mail['Subject'] = title
    mail['From'] = env['SMTP_FROM']
    mail['To'] = destination
    lines = [title, '', f"结果：{RESULTS[result]}",
             f"触发仓库：{context['repository']}",
             f"触发分支/引用：{context.get('branch', '')}",
             f"触发提交/引用：{context.get('ref', '')}",
             f"触发人：{context.get('actor', '')}",
             f"镜像：{env.get('BUILD_IMAGE') or '尚未生成镜像标签'}", '', '源码来源：']
    if not sources:
        lines.append('构建未完成源码解析；请查看触发引用和运行日志。')
    for repository, source in sources.items():
        lines.append(f"- {repository}：分支/引用={source.get('branch', '')}；构建提交/引用={source.get('ref', '')}")
    run_url = f"https://github.com/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"
    lines.extend(['', f"运行链接：{run_url}", f"运行次数：{env.get('GITHUB_RUN_ATTEMPT', '1')}"])
    if result != 'success':
        lines.extend(['', '本次未全部完成；镜像可能已推送到部分仓库，请以运行日志为准。'])
    mail.set_content('\n'.join(lines))
    return mail


def deliver(mail, env):
    port = int(env.get('SMTP_PORT') or '587')
    context = ssl.create_default_context()
    if port == 465:
        client = smtplib.SMTP_SSL(env['SMTP_HOST'], port, timeout=30, context=context)
    else:
        client = smtplib.SMTP(env['SMTP_HOST'], port, timeout=30)
    with client:
        if port != 465:
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        if env.get('SMTP_USERNAME'):
            client.login(env['SMTP_USERNAME'], env['SMTP_PASSWORD'])
        client.send_message(mail)


def report(text, warning=False):
    print(('::warning::' if warning else '') + text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write('\n' + text + '\n')


def main():
    env = os.environ
    if env.get('BUILD_RESULT') not in RESULTS:
        report('构建未执行，跳过邮件通知。')
        return 0
    if not env.get('SMTP_HOST') or not address(env.get('SMTP_FROM', '')):
        report('邮件未发送：请配置 SMTP_HOST 和有效的 SMTP_FROM。', warning=True)
        return 0
    try:
        if bool(env.get('SMTP_USERNAME')) != bool(env.get('SMTP_PASSWORD')):
            raise ValueError('SMTP_USERNAME and SMTP_PASSWORD must be configured together')
        event = json.loads(Path(env['GITHUB_EVENT_PATH']).read_text())
        context = origin(env, event)
        mappings = json.loads(env.get('MAIL_RECIPIENTS_JSON') or '{}')
        if not isinstance(mappings, dict):
            raise ValueError('MAIL_RECIPIENTS_JSON must be an object of GitHub login to email')
        destination = recipient(context, event, mappings, env.get('GH_TOKEN', ''))
        if not destination:
            report('邮件未发送：未找到可投递邮箱，请为目标用户配置 MAIL_RECIPIENTS_JSON；GitHub noreply 邮箱不可投递。', warning=True)
            return 0
        sources = json.loads(env.get('BUILD_SOURCES') or '{}')
        if not isinstance(sources, dict) or any(repo not in REPOSITORIES for repo in sources):
            raise ValueError('Invalid build source repositories')
        deliver(message(env, context, sources, destination), env)
        report('构建结果邮件已发送给触发工作流的操作人。')
        return 0
    except (ValueError, OSError, smtplib.SMTPException) as error:
        # SMTP exceptions can contain addresses or credentials; never log the raw response.
        report(f'邮件发送失败（{type(error).__name__}），请检查 SMTP/收件人配置；构建任务结果保持原状。', warning=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
