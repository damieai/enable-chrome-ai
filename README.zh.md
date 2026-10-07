# Enable Chrome AI ✨

由 [lcandy2](https://twitter.com/vanillaCitron) 研究并制作脚本。

[![Twitter](https://img.shields.io/twitter/follow/vanillaCitron)](https://twitter.com/vanillaCitron)

[English](README.md) | 中文

尝试通过本地配置补丁启用 Google Chrome 的 AI 功能，无需清除数据或重新安装。功能是否可用仍由 Chrome 版本、账号、地区、实验分配和管理员策略共同决定。

<img width="512" alt="Google Chrome Gemini in Chrome" src="https://github.com/user-attachments/assets/a88c56a7-f20b-432a-926c-0184194225b4" />

Python 脚本，修复本地国家配置与 Gemini 资格缓存，提供持久国家覆盖、只读诊断、自动备份及可选启动参数。配置写入成功不代表服务端已授予 AI 功能使用权限。

## ✅ 环境要求
- Python `3.13+`（见 `.python-version` / `pyproject.toml`）
- 已安装 Google Chrome（Stable/Canary/Dev/Beta）

## ⚡️ 快速开始（uv）
1. 安装 uv（一次性）：
   - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
   - macOS & Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - 更多安装方式请参考 [uv 安装文档](https://docs.astral.sh/uv/getting-started/installation/)。
2. 安装依赖（自动创建虚拟环境）：`uv sync`。
3. 运行脚本：`uv run main.py`。
4. 运行前保存浏览器中的工作。脚本会关闭当前系统用户的 Chrome，等待退出，写入并校验配置，再恢复原启动参数。完成后自动退出。Windows 上自动关闭使用进程终止操作；希望自行正常退出时，请使用 `--no-close`。

## ⚡️ 快速开始（pip）
1. 创建并激活虚拟环境。
2. 安装依赖：`python -m pip install psutil`。
3. 运行：`python main.py`。

## 🔧 做了什么
- 自动定位 Windows / macOS / Linux 上的 Stable / Canary / Dev / Beta 数据目录；Windows 优先使用 `%LOCALAPPDATA%`，也可显式指定目录。
- 将 `profile.info_cache` 中各已有配置的 `is_glic_eligible` 设置为布尔值 `true`，缺失时补充。
- 将 `variations_country` 设为 `"us"`。
- 新增或修复 `variations_permanent_overridden_country: "us"`。这是 Chromium 支持的持久国家覆盖，比绑定版本的缓存优先。
- 将 `variations_permanent_consistency_country` 新增或修复为 `["<Last Version 中的版本号>", "us"]`。版本号会去除首尾空白；文件缺失或无效时仅跳过此字段，继续其余补丁。
- 每次实际修改前，在同目录保存原始字节备份 `Local State.backup-<UTC时间>`，通过临时文件原子替换并重新读取校验。重复运行且无需修改时不创建备份。
- 只修改上述字段，保留语言、实验开关、账号、加密数据、管理员策略和首次使用同意状态。`variations_safe_seed_*` 描述历史安全实验快照，保持原样。

## 🧪 预览、诊断与指定目录

仅预览，不关闭 Chrome、不写文件：

```powershell
uv run main.py --dry-run
```

只读检查本地补丁状态，可在 Chrome 重启后运行以观察字段是否被重算。退出码 `0` 表示所检查的本地字段已符合补丁目标，`1` 表示仍有待修改项或读取错误；这不是 Gemini 实际可用性检测：

```powershell
uv run main.py --check
```

显式指定 Windows 稳定版目录（PowerShell）：

```powershell
uv run main.py --user-data-dir "$env:LOCALAPPDATA\Google\Chrome\User Data"
```

自定义安装请使用 `chrome://version` 中“个人资料路径”的上一级目录。例如路径结尾为 `User Data\Default`，应传入 `User Data`，而不是 `Default`。

手动完全退出 Chrome（包括后台进程）后运行：

```powershell
uv run main.py --no-close
```

关闭后暂不重启使用 `--no-restart`。自动关闭模式会关闭当前系统用户的所有被识别的 Chrome 进程，即使指定了单个数据目录；其他系统用户的 Chrome 不受影响。

## 🔍 Chrome 154 与重启后失效

已对照 Chromium `154.0.8037.98` 源码核实：

- `is_glic_eligible` 是计算结果缓存，Chrome 会在账号/资格变化时重写。把它改成 `true` 不能取代实际资格判断。
- 持久国家覆盖与当前会话国家是不同输入。`variations_country` 可能随网络请求更新，新版本还可能从独立的实验种子存储读取国家信息，仅修改旧缓存不一定改变运行时结果。
- 如果需要排查会话国家，可让脚本在重启已运行的 Chrome 时加入国家覆盖参数：

```powershell
uv run main.py --restart-country
```

此选项在原启动参数中加入或替换 `--variations-override-country=us`，只对本次启动生效，不修改快捷方式。使用该选项前 Chrome 应处于运行状态；若 Chrome 原本未运行，脚本会提示手动带参数启动。后续从普通快捷方式启动不保留该参数，可在 `chrome://version` 的命令行中确认。

持久字段覆盖永久国家；启动参数覆盖永久国家与会话国家。两者都影响 Chrome 的地区实验，不只影响 AI，也不能改变服务端看到的网络位置、账号授权或管理员策略。

如果仍无法使用，请检查 `chrome://policy`、账号登录状态及 Google 官方可用性要求。受管理的工作/学校账号可能需要管理员开启。中文已在支持语言列表中，无需自动改成英文；Gemini、AI 历史搜索和 DevTools AI 的可用条件也不完全相同。

源码与官方说明：

- [Chrome 154 资格计算及缓存更新](https://chromium.googlesource.com/chromium/src/+/154.0.8037.98/chrome/browser/glic/public/glic_enabling.cc)
- [Chrome 154 国家覆盖优先级](https://chromium.googlesource.com/chromium/src/+/154.0.8037.98/components/variations/service/variations_field_trial_creator.cc)
- [Gemini in Chrome 可用性](https://support.google.com/chrome/answer/17140089)

## 🛟 备份、恢复与限制

- 需先启动一次 Chrome 生成 `Local State`。文件缺失、JSON 损坏或权限不足会明确报错；某个通道失败不阻止其他有效通道处理。
- 恢复时完全退出 Chrome，将所需的 `Local State.backup-<UTC时间>` 复制覆盖同目录的 `Local State`。完整恢复也会恢复备份时的其他本地设置，请选对时间。
- 使用拥有配置的同一系统用户运行。进程检测基于 Chrome 名称；特殊封装/改名的版本请先手动退出。脚本检查进程退出与文件内容变化，但无法锁住用户随后重新启动的浏览器，写入期间请勿启动 Chrome。
- 自动重启保留浏览器进程原命令行及工作目录，不保证恢复所有窗口、未保存表单或标签页状态。
- 当前自动测试使用临时配置和模拟进程，尚不能替代 Windows Chrome 中的实际功能验证。
- 与 Google 无关。分享诊断时只贴相关字段；完整 `Local State` 和备份包含账号标识及加密数据。

运行测试：`uv run python -m unittest discover -s tests -v`。

## 📜 许可
转载或基于本研究二次创作需要注明来源。

## 🙏 致谢
- [show-copilot](https://github.com/hzkaai/show-copilot)
