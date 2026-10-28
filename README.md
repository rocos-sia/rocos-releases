# ROCOS Releases

ROCOS App、Viz 与 ECM 的公开发布入口，用于维护版本清单、发布说明和安装包。

## 当前状态

已配置 App、Viz 的自动同步：每小时 UTC 第 17 分钟检查源仓库，也支持在 Actions 手动运行 `Sync component releases`。ECM 本轮暂不接入，保持 `null`。这一步提供发布清单与下载文件，客户端的在线提示和安装程序另行接入。

`null` 表示该渠道尚无可提供的组件发布，不能据此判断用户已经安装最新版本。

## 版本清单

| 渠道 | 文件 | 固定读取地址 |
| --- | --- | --- |
| 正式版 | [channels/stable.json](channels/stable.json) | [stable.json](https://raw.githubusercontent.com/rocos-sia/rocos-releases/main/channels/stable.json) |
| 内测版 | [channels/internal.json](channels/internal.json) | [internal.json](https://raw.githubusercontent.com/rocos-sia/rocos-releases/main/channels/internal.json) |

清单格式由 [manifest.schema.json](schemas/manifest.schema.json) 定义，`schema_version` 当前为 `1`。App、Viz、ECM 分别保留自身版本号；正式版和内测版分别维护。破坏性格式变化需要提升清单版本。

每项已发布组件记录：

- 版本号、上游仓库、Release 标签、发布时间、发布页面和更新说明。
- 安装包的系统、CPU 架构、格式、下载地址、大小及 SHA256；可另附签名文件地址。
- API 契约版本与共享内存 ABI 要求；未知值为 `null`，不能视为已通过兼容性检查。

`version` 使用不带 `v` 前缀的 SemVer；`tag` 保留上游实际标签。`sha256` 使用文件内容的 64 位小写十六进制摘要，`size_bytes` 单位为字节，日期使用带时区的 RFC 3339 格式。内测发布使用 `prerelease: true`，正式发布使用 `false`。

## 安装包与发布步骤

安装包上传至本仓库的 [GitHub Releases](https://github.com/rocos-sia/rocos-releases/releases)，Git 文件目录维护清单与说明。保留历史 Release，以支持追溯和回退。

1. 在组件源仓库构建并验证发布产物。
2. 创建本仓库的 Release 草稿，使用组件名前缀区分标签，例如 `app-vX.Y.Z`、`viz-vX.Y.Z`、`ecm-vX.Y.Z`。
3. 上传安装包、校验文件和已有的签名，检查下载及文件摘要，再发布 Release。
4. 核对组件适用的平台、安装依赖，以及 App/Viz API 和 App/ECM ABI 兼容性。
5. 最后更新对应渠道 JSON 与 `updated_at`，使清单指向已经可用的文件。

一份组件清单只包含同一版本的产物。同一渠道汇总了三个组件，不表示这三个组件已被验证为兼容套装。Viz 若随 App 分发，其安装与兼容关系应在发布说明中明确；若独立部署，可提供单独的部署归档。

## 自动同步约定

[sources.json](sources.json) 固定允许读取的公开上游仓库；`null` 表示关闭该组件。工作流使用发布仓库自身的 `GITHUB_TOKEN`，无需保存个人 token。App、Viz 各自在自己的仓库通过 `v*` 标签构建 DEB 并发布 Release；带 rc 的版本必须标记为 Prerelease。

每个完整上游 Release 必须提供 `release.json`，其结构见 [source-release.schema.json](schemas/source-release.schema.json)。发布描述列出组件、版本、兼容性、安装包名称、架构、大小和 SHA256。当前同步器接收 DEB；渠道格式仍预留其他归档格式。上游示例：

```json
{
  "schema_version": 1,
  "component": "app",
  "version": "3.2.0-rc.1",
  "compatibility": {"api_version": "3.0.0", "shm_abi_version": 2},
  "assets": [{
    "name": "rocos-app_3.2.0~rc.1_amd64.deb",
    "os": "linux", "arch": "amd64", "format": "deb",
    "size_bytes": 1234,
    "sha256": "替换为文件的64位SHA256"
  }]
}
```

自动流程分页读取源仓库 Release，忽略草稿和没有 `release.json` 的旧发行。正式与内测分别按 SemVer 选择最高版本（例如 rc.10 高于 rc.9），不按发布时间猜测，也不把旧版本回退写入清单。标签、预发布标志、描述文件和 DEB 内部版本必须匹配；Debian 使用 `~rc.N`，JSON/Git 仍使用 `-rc.N`。

同步器下载并校验每个 DEB 的实际摘要、大小、包名、版本、架构，上传到本仓库草稿，再下载核对。全部成功才公开镜像 Release、最后更新渠道 JSON。失败时保留旧渠道文件；重试可补完草稿，已公开产物不覆盖。同版本已经收录后不重复下载，修订必须发布新版本。

工作流通过并发锁避免同步互相覆盖。上游发布到收录通常需要等下一次小时任务；GitHub 定时任务可能延迟，公开仓库长期无活动时定时任务也可能停用，可从 Actions 手动启用/运行。也保留 `repository_dispatch` 事件入口，后续使用具有本仓库权限的专用凭据接入即时通知；目前无需此凭据。

本地检查（需 Python 3.10+、GitHub CLI、dpkg-deb，并已登录 `gh`）：

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 scripts/sync_releases.py --dry-run
```

`--dry-run` 会下载并校验选中的源安装包，但不上传、不修改渠道文件。正常运行需要对本仓库的写权限；工作流负责提交修改后的渠道文件。

## 校验清单

使用 Python `jsonschema` 校验时：

```bash
python3 - <<'PY'
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

schema = json.loads(Path('schemas/manifest.schema.json').read_text())
Draft202012Validator.check_schema(schema)
validator = Draft202012Validator(schema, format_checker=FormatChecker())
for path in sorted(Path('channels').glob('*.json')):
    data = json.loads(path.read_text())
    validator.validate(data)
    assert data['channel'] == path.stem
    print(f'{path}: OK')
PY
```

格式校验不替代下载完整性、签名验证或组件兼容性验证。

## 许可

本仓库原创清单、文档和后续脚本采用 [MIT License](LICENSE)。分发的软件安装包及其依赖遵循各自上游许可证，本仓库的 MIT 许可不改变这些许可证。
