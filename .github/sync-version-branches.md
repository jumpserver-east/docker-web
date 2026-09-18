# 同步上游 Docker Web 分支

工作流：`.github/workflows/sync-version-branches.yml`。

| 配置 | 值 |
| --- | --- |
| 只读源仓库 | `https://github.com/jumpserver/docker-web.git` |
| 唯一写入目标 | `jumpserver-east/docker-web` |
| 工作流分支 | `docker-build`（需为默认分支） |
| 定时 | 周一至周五北京时间 09:00，UTC `0 1 * * 1-5` |
| 手动运行 | 支持，`dry_run` 默认勾选 |

工作流同时校验 `github.repository` 和 `github.ref`。同步步骤设置
`EXPECTED_ORIGIN_REPOSITORY=jumpserver-east/docker-web`，脚本在访问远程之前检查
origin 的实际 push URL（含 pushurl 和 URL rewrite）；错误目标或多个推送地址会直接
失败。不会推送到 upstream，也不会删除目标分支或同步 tag。

## 分支规则

- `dev`、`v3`、`v4`、`v5` 精确对齐 upstream，使用带显式旧 SHA 的
  `--force-with-lease`；会丢弃这些标准分支上 fork 独有的提交。
- 完整版本分支匹配 `^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9]+)?(-lts)?$`。
  缺失时创建，已有时只做 fast-forward；存在 fork 独有提交则跳过。
- `docker-build`、`master`、客户二开分支和 `v4.10` 等不完整版本名不在同步范围。
- HTTP 401/403 等认证拒绝会停止后续推送；其他分支推送失败记录为失败并继续处理。

## 工作流与镜像

`docker-build` 仅保留本 fork 自有的五个 workflow：

- `build-web-image.yml`
- `reusable-web-dispatch.yml`
- `test-web-build.yml`
- `notify-image-build.yml`
- `sync-version-branches.yml`

继承的 Nginx、静态资源、依赖更新、通用 handler 和构建测试 workflow 已从本配置分支
移除。源码分支仍保留上游原始提交，其中的继承 YAML workflow 通过 fork 仓库级 API
停用；GitHub 自动管理的 Dependency Graph 等任务跳过。实际同步必须等待测试与
停用任务成功，dry-run 则跳过停用操作。push/PR 仅验证配置，push 还会应用停用策略，
不执行分支同步。

Web 自动构建只监听 `客户@基线` 分支的 push，标准分支同步不会触发镜像构建。
要让客户分支接收 push 事件，该分支必须包含自有 `build-web-image.yml`；仅将工作流
放在 `docker-build` 无法监听其他源码分支。也可始终在 `docker-build` 手动运行构建，
或由 Lina/Luna 调用可复用 dispatch。手动构建不受标准分支过滤影响。

客户二开分支采用 `客户名称@基线分支`，例如 `ferror@v4.10.19-lts`，跨组件保持
相同拼写。客户代码放在二开分支，不修改用于镜像同步的标准开发分支。
构建时可分别指定 Lina、Luna、Web 引用，未指定的组件按同名 → `@` 后基线 → `dev`
选择，详见 [构建说明](../README.md#手动构建)。

## 凭据与首次运行

在 **jumpserver-east/docker-web → Settings → Secrets and variables → Actions**
设置 `SYNC_BRANCHES_TOKEN`。Fine-grained PAT 的 Resource owner 为 `jumpserver-east`，
包含 `docker-web`，具备 **Contents: Read and write**、**Workflows: Read and write**；
classic PAT 则需要 `repo` 与 `workflow`。组织策略要求的审批、SSO 也需完成。
受保护的标准开发分支需允许同步身份执行上述镜像更新。

存在该 secret 时优先使用它，否则回退到有 `contents: write` 的 `GITHUB_TOKEN`，
但后者可能无法推送工作流文件变更。停用继承 workflow 使用当前 fork 的
`GITHUB_TOKEN` 和 `actions: write`，无需额外提升 PAT 权限。

首次选择 **Sync upstream branches → Run workflow → docker-build**，先 dry-run
检查计划，再取消 dry-run 实际同步。GitHub 定时任务可能延迟。

## 本地验证

```bash
python3 .github/scripts/test_sync_version_branches.py
python3 .github/scripts/test_workflow_policy.py
python3 .github/scripts/tests/test_resolve_web_refs.py
EXPECTED_ORIGIN_REPOSITORY=jumpserver-east/docker-web DRY_RUN=true bash .github/scripts/sync-version-branches.sh
```
