# 开发与发布

[返回首页](../README.md) · [使用指南](usage.md)

## 从源码运行

需要 Python 3.10 或更新版本。以下命令在项目目录执行。

### Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e .
.venv/bin/python smooth_caddy.py
```

### Windows（PowerShell）

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe smooth_caddy.py
```

下文以 Linux 命令为例；Windows 使用 `.\.venv\Scripts\python.exe` 替代 `.venv/bin/python`。启动参数见[启动与语言](usage.md#启动与语言)。目前提供 TUI，完整业务 shell CLI 尚未实现。

## 结构与测试

- [产品与交互规则](product.md)：配置模型、证书规则、部署布局及 TUI 行为。
- [证书模块接口](ca-lite-interface.md)：私有 PKI、公共 TLS 和密钥保护边界。
- [任务系统](supertaskrunner.md)：任务计划、进度事件、并发与失败处理。

入口为 `smooth_caddy.py`；业务在 `app/network/`，界面在 `app/tui/`，测试在 `tests/`。开发目录保持模块化；独立发布物使用 PyInstaller，按运行主机的平台与架构构建，不包含用户数据。程序发布物与给节点生成的 `.run` 部署包不同。

```bash
.venv/bin/python -m compileall -q smooth_caddy.py app tests
.venv/bin/python -m unittest discover -s tests
```

可用 `CADDY_TEST_BINARY=/path/to/caddy .venv/bin/python -m unittest discover -s tests -p test_relay.py` 运行本机真实 Caddy 中继集成测试（已验证 Caddy 2.11.7）；未设置该变量时跳过真实进程测试。

自动测试使用临时数据及网络／SSH 替身，覆盖业务和 TUI 回归，不代表真实 DNS、所有目标设备、自启动、恢复或跨架构兼容性均已验收。当前不声明未经验证的平台支持范围。

### 跨平台测试规则

主分支推送和面向主分支的 PR 会运行 Linux / Windows Python 3.13 测试，不打包；失败不会自动重试。测试日志作为 Actions Artifact 保留 14 天。版本标签仍执行发布前测试和打包。

- 异步界面使用 `tests.support.wait_for_screen` 等待目标弹窗及控件挂载，使用 `wait_until` 等待明确的操作结果；超时要说明等待的状态。不要把一次刷新或固定休眠当作就绪保证。
- Python 子进程使用 `tests.support.run_python`：统一工作目录、UTF-8、超时及退出码／双输出诊断。需要二进制输入输出的 OpenSSL、安装脚本测试保留字节流，但也必须设置超时。
- 文件位置比较先 `resolve()`；若检查已存在文件的身份可用 `samefile()`。只有展示格式测试才比较原始字符串，避免 Windows 短路径别名影响断言。
- 每个用例使用临时目录并关闭数据库、子进程及异步任务。修改环境、语言或模拟对象时用上下文管理器或 `addCleanup` 恢复。英文 UI 在独立子进程中设置语言后再导入 UI 类。
- 初始化挂载通过事件门控模拟延迟，验证等待条件；不靠整套测试重试掩盖竞态。真实 Caddy 集成测试仍需显式配置 `CADDY_TEST_BINARY`，普通 CI 的跳过项不代表已验收。

## 仓库范围

仓库仅包含入口、`app/` 源码、合成数据测试、当前文档、构建脚本、GitHub 工作流及许可证。真实运行数据、`data.bak/` 等备份、证书、凭据、工具缓存、导出物与本地产物不得提交。发布归档通过 GitHub Releases 分发，不进入源码历史。发布前运行 `python tools/audit_source.py` 检查 Git 跟踪范围和常见凭据模式；测试仅使用合成凭据。

## 版本与发布约定

仓库按公开项目维护，本项目采用 [MIT 许可证](../LICENSE)；第三方依赖继续遵循各自许可证。

- 发布标签为 `vX.Y.Z`，初始标签为 `v0.1.0`。构建产物版本为 `X.Y.Z.commit`，`commit` 为对应提交的短哈希，例如 `0.1.0.a1b2c3d4`。
- 原则上每次提交增加 `Z`；这是文档约定，不设置强制检查，也不要求每次提交都发布标签。
- 数据结构变化时增加 `Y`，`Z` 归零；范围包括数据库、设置存档／JSON 和部署包格式。其余修改增加 `Z`。`X` 暂时保持 `0`，后续由维护者决定。
- 标签是发布基础版本的唯一来源。构建读取触发工作流的 GitHub 标签及对应提交，不读取其他分支的最新标签，也不手工维护发布版本号。
- GitHub Actions 在推送 `v*` 版本标签时构建，普通分支提交不触发发布构建。正式标签须符合 `vX.Y.Z`；已发布标签不移动，新版本使用新标签。
- 新 Release 的说明自动列出上一版本以来的提交标题与正文，并附提交链接及完整代码差异链接；首个版本列出全部提交。基线取触发标签历史中版本号最高且低于当前版本的正式标签，不混入其他分支或后续版本。轻量标签和附注标签均支持，不要求手工编写 changelog。
- 提交信息应说明具体变化；需要升级操作时写入提交正文，发布时会原样展示。已存在的 Release 说明在重新打包时保留。
- 本阶段发布物仅提供 **Linux x64** 与 **Windows x64**，暂不提供 ARM 包。这是程序运行平台，与被管理节点的架构无关。

发布工作流位于 `.github/workflows/release.yml`。两个平台均通过测试和构建后才发布资产；实际验收结果以相应标签的 Actions 结果为准。

GitHub 构建在上传前为最终压缩包生成构建来源证明（Attestation）。通过 Actions 的 OIDC 身份自动签名，无须维护签名私钥或新增仓库 Secret；证明失败会阻止发布。此机制不属于 Windows 代码签名。

下载发布压缩包后，可用 GitHub CLI 联网验证其来源：

```bash
gh attestation verify <下载的压缩包路径> --repo JerryFecl3/smooth-caddy
```

验证对象是原始压缩包，SHA-256 校验文件仍然保留。来源证明仅适用于启用此流程后由 GitHub Actions 构建的发布物；现有旧包和本地构建不会自动获得证明。详见 [GitHub 构建来源证明文档](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)。

## 构建发布物

在对应目标平台的原生 Python 环境中执行。要求工作区干净，当前提交具有唯一的 `vX.Y.Z` 标签：

```bash
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python -m pip install -e .
.venv/bin/python tools/build_release.py
```

输出位于 `dist/`，命名为 `smooth-caddy-<版本>-<系统>-<架构>`。Linux 生成 `.tar.gz`，Windows 生成 `.zip`；压缩包含单文件程序、说明、许可证目录和 `build-info.json`，旁边提供 SHA-256 校验文件。Linux 和 Windows 的 x64 构建在 GitHub Actions 分别测试；ARM 不在本阶段发布范围。

解压后启动程序，默认数据位于当前用户主目录下的 `~/.smooth-caddy/`，与源码运行一致。退出后替换程序进行升级，保留数据目录；数据格式变更遵循[使用指南中的升级规则](usage.md#升级与旧数据)。

构建机的 Python、架构、libc 和依赖版本会写入 `build-info.json`。GitHub 发布使用 Ubuntu 22.04（glibc 2.35）构建 Linux 包，不保证更旧的 glibc 系统可运行。许可证收集包含构建环境包及可识别的系统库声明，是保守收集，不等于完成全部依赖授权审核。详见 [第三方声明](../THIRD_PARTY_NOTICES.md)。

## Windows 预览构建

Windows 验证包：推送 `preview/**` 分支会运行 Windows x64 测试和 `tools/build_release.py --preview`，产物保存在 Actions Artifacts 中 14 天，不创建 Release。预览版本以 `preview.<提交哈希>` 标识，要求干净工作区，无需版本标签。

## 第三方许可与服务

本项目采用 [MIT 许可证](../LICENSE)；第三方项目保持各自授权，详见 [第三方声明](../THIRD_PARTY_NOTICES.md)。

节点代理使用 [Caddy](https://github.com/caddyserver/caddy)，许可证为 [Apache-2.0](https://github.com/caddyserver/caddy/blob/master/LICENSE)。本程序下载官方标准版二进制，离线 package 及部分 SSH 部署包会携带该二进制。分发这些包时，应随附所用版本的许可证，并保留适用的版权、归属及上游 NOTICE 声明（如有）；不能仅用网页链接代替随包许可文本。

公共证书申请调用 [lego](https://github.com/go-acme/lego)，其许可证为 [MIT](https://github.com/go-acme/lego/blob/master/LICENSE)。申请使用 Let’s Encrypt 服务，程序调用 lego 时传入接受条款选项，使用者应阅读其[订户协议及相关文件](https://letsencrypt.org/repository/)。软件许可证与证书服务条款是不同事项。

正式发布前，按实际分发内容整理第三方声明：

- 独立程序：Python 运行时、Textual、AsyncSSH、cryptography 及实际收录的传递依赖和原生库。
- 附带工具或部署包：Caddy、lego 及相应二进制包含的依赖。
- 每项记录版本、来源和许可证，随包提供要求保留的许可与版权文本；若修改上游文件，按其条款标明修改。

发布脚本自动收集 Python、已安装依赖及可识别的系统库许可文本，并随包携带；收集结果和无法自动确认的项目记录在 build-info.json。携带 Caddy 的部署包同时包含 Caddy 和 Go 的许可文本。分发前仍需核对所选版本的额外声明。
