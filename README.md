# JumpServer Web

JumpServer 的 LB Nginx Build 项目，其中包含 Lina, Luna 和一些静态安装包文件

每周一北京时间 08:17 从 `jumpserver/docker-web` 同步标准开发与完整版本分支到
`jumpserver-east/docker-web`。支持手动 dry-run；同步不会触发 Web 镜像构建。
目标仓库限制、Token 配置与二开分支公约见 [同步说明](.github/sync-version-branches.md)。

## CI 构建分支选择

Lina、Luna 通过复用工作流触发构建，或 Docker Web 分支自动触发构建时，触发方使用本次源码版本，其余两个仓库分别按以下顺序选择分支：

1. 与触发分支同名的分支。
2. 触发分支名称中 `@` 后面的基础分支，例如 `ferror@v4.10.19-lts` 对应 `v4.10.19-lts`。
3. `dev` 分支。

没有 `@` 时跳过第二步。查询远程仓库失败或所有候选分支均不存在时，工作流报错。选择结果显示在构建摘要中。

例如 Luna 的 `ferror@v4.10.19-lts` 触发构建时，Luna 使用触发提交的 SHA；Lina 如果存在同名分支就使用同名分支；Docker Web 如果仅存在 `v4.10.19-lts` 就使用该分支。

### 手动构建

在 Actions 中选择 **Build Complete EE Web Image → Run workflow**，工作流分支选择
`docker-build`。构建配置始终从该分支读取，应用源码由下面的输入决定：

| 输入 | 用途 |
| --- | --- |
| `branch` | 公共匹配分支，例如 `ferror@v4.10.19-lts` |
| `lina_branch` | 单独指定 Lina 分支、tag 或 SHA；留空按公共分支匹配 |
| `luna_branch` | 单独指定 Luna 分支、tag 或 SHA；留空按公共分支匹配 |
| `web_branch` | 单独指定 Docker Web 分支、tag 或 SHA；留空按公共分支匹配 |
| `tag` | 最终镜像标签；留空按公共分支和时间生成，不参与源码选择 |

每个仓库独立处理：显式覆盖引用优先，其余依次尝试同名分支、`@` 后基线分支和 `dev`。
全部自动选择时只填写 `branch`；也可以同时填写三个组件引用，构建不同分支的组合。
若 `branch` 留空，使用 `web_branch` 作为匹配依据；二者均留空则使用 `dev`。
显式填写 `dev` 表示主动选择该分支，不再自动替换；无效的显式引用会在 checkout 或
构建时失败。指定某个组件的 SHA 时，建议同时填写 `branch` 为其他组件提供匹配依据。

例如 `branch=ferror@v4.10.19-lts`，只填写 `luna_branch=5a7a9a70bd7cdd77fde1753af58a80f3918b14ab`，
Luna 将固定使用该 SHA，Lina 与 Web 各自按同名 → `v4.10.19-lts` → `dev` 匹配。
仅将镜像 `tag` 填成 `ferror_v4.10.19-lts` 不会选择同名源码分支；分支名中的 `@` 和
镜像标签中的 `_` 是不同用途，不能互相推断。

构建开始前会在日志和 Summary 列出三份选中的源码引用。Lina/Luna 发起的自动 dispatch
也使用同一解析器，固定触发组件 SHA，并为另外两个仓库应用上述匹配顺序。

本地验证：`python3 .github/scripts/tests/test_resolve_web_refs.py`。

### 自动构建与客户分支

客户分支使用 `客户名称@基线分支`，例如 `ferror@v4.10.19-lts`，各组件保持同名。
本仓库自有构建只监听含 `@` 的客户分支 push；该源码分支必须包含
`.github/workflows/build-web-image.yml` 才能收到 push 事件。构建实际使用的配置和解析器
仍从 `docker-build` 检出。标准分支只同步，手动运行仍可显式构建这些版本。
同一客户分支的新构建会取消其尚未完成的旧构建。

## Docker 构建

```bash
VERSION=dev
docker buildx build --build-arg VERSION=${VERSION} -t jumpserver/web:${VERSION} . --load
```
