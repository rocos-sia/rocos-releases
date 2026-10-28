# ROCOS Releases

ROCOS App、Viz 与 ECM 的公开发布入口，用于维护版本清单、发布说明和安装包。

## 当前状态

发布仓库已初始化。正式版与内测版清单暂未收录安装包，各组件值为 `null`；自动同步、在线更新检测和安装程序尚未配置。

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

后续可以通过 GitHub Actions 接收上游发布通知、定时检查或手动运行，完成收集、校验和清单更新。正式版可查询 GitHub 最新正式 Release；内测版需单独筛选预发布列表并比较版本，不能共用正式版的 `releases/latest` 查询。

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
