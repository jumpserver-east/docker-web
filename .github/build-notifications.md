# 镜像构建邮件通知

JumpServer、Lion、KoKo、Docker Web 的镜像构建结束后，会调用
`jumpserver-east/docker-web/.github/workflows/notify-image-build.yml@docker-build`
发送结果邮件。支持成功、失败、取消；因分支过滤未执行的构建不发送邮件。
通知是独立任务，SMTP 失败不会改写原构建任务的状态。

Lina/Luna 的 dispatch 会把原始仓库、分支、提交、触发方式和操作人传给 Docker Web。
邮件在最终 Web 构建完成后发送，收件人不会变成 dispatch token 的所属账号。
若 dispatch 在提交构建请求前失败或取消，则由原组件发送“构建请求提交失败/已取消”。
整个 workflow 被强制终止、GitHub 停机等情况下无法保证通知任务执行。

## 收件人

- 所有构建：通知触发该 workflow 的操作人（重新运行时为重新运行的操作人），优先使用
  `MAIL_RECIPIENTS_JSON` 对该账号配置的邮箱，再查 GitHub 账号公开邮箱。
- GitHub noreply 邮箱不是真实收件箱，不发送到该地址。找不到可投递地址时在日志和
  Summary 明确提示；不读取 commit 作者邮箱，也不回退到其他人的邮箱。
- Lina/Luna 自动或手动 dispatch 保留原工作流操作人；直接在 Docker Web 重跑构建时，
  改为通知该次重跑操作人。`workflow_run` 链路取来源工作流的操作人。

## SMTP 配置

建议在组织 `jumpserver-east` 的 Actions Secrets 中配置以下值，授权给
`jumpserver`、`lion`、`koko`、`lina`、`luna`、`docker-web` 六个仓库，或在这些仓库分别配置：

| Secret | 用途 |
| --- | --- |
| `SMTP_HOST` | SMTP 服务器地址 |
| `SMTP_PORT` | 默认 587（STARTTLS），465 使用隐式 TLS |
| `SMTP_USERNAME` | SMTP 登录用户名 |
| `SMTP_PASSWORD` | SMTP 密码或应用授权码 |
| `SMTP_FROM` | 已获 SMTP 服务授权的发件邮箱，例如 `builds@example.com` |
| `MAIL_RECIPIENTS_JSON` | 可选：GitHub 用户名到真实邮箱的 JSON 映射，私有邮箱用户需要配置 |

映射格式示例（替换为真实地址后放入 Secret，不要提交进源码）：

```json
{"Nickyang00": "your-address@example.com"}
```

SMTP 使用 TLS 并验证服务端证书。用户名和密码必须同时设置；允许无需账号密码的
TLS 中继。Lina/Luna 的 dispatch 失败通知使用各自仓库的 Secrets，最终 Web 构建通知
使用 Docker Web 仓库的 Secrets。缺少 SMTP 或收件人配置时，只记录“邮件未发送”提示。

## 邮件内容

邮件包含构建结果、原始触发仓库/分支/提交、镜像地址、各组件选中的源码引用、
GitHub Actions 运行链接及重跑次数。失败或取消时注明可能已完成部分镜像推送，
需要查看日志。源码解析之前失败时，邮件保留请求的来源并注明尚未完成解析。

## 本地测试

```bash
python3 .github/scripts/tests/test_notify_image_build.py
```

测试使用模拟 SMTP 和模拟 GitHub 数据，不向真实用户发送邮件。
