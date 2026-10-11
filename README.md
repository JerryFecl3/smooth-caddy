# Smooth Caddy

面向个人小站、家庭网络和自托管爱好者的 Caddy 配置与部署工具，让个人网络的 HTTPS 配置、证书管理与部署更顺手。

我非常喜欢 Lucky。它集成了 DDNS、Web 反向代理和 HTTPS 证书申请，对个人小站来说已经很好用。但随着我的网络变成多个内网节点加一个外网云服务器，并通过 WireGuard 互联，我开始需要一些更细的能力：多节点配置同步、证书集中管理、DNS 服务商密钥不落在代理节点上，以及内外网采用不同的访问规则。

Smooth Caddy 就是为这样的个人网络准备的。平时不必一直运行，在网络部署发生变化时打开它，调整配置，再统一生成和部署。

通过 **区域 × 节点 × 站点** 维护多节点配置，支持私有 CA、Let’s Encrypt 公共 TLS、节点间 mTLS 中继、离线部署包与 SSH 部署。一个实例管理一个网络，不承担通用主机维护，也不配置 DNS 解析、NAT 或防火墙；公共证书申请时会通过 DNS API 管理验证记录。

可从源码运行，也可使用版本标签触发构建的独立可执行文件。正式发布物见 GitHub Releases。完整 shell CLI 尚未实现，业务层已与 TUI 分离。

## 从源码运行

需要 Python 3.10 或更新版本。以下命令在项目目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e .
.venv/bin/python smooth_caddy.py
```

Linux 和 Windows 默认数据目录均为当前用户主目录下的 `~/.smooth-caddy/`，数据库直接保存在其中，不再嵌套 `data/`。默认路径不随程序位置或启动时的工作目录改变。可指定其他位置：

```bash
.venv/bin/python smooth_caddy.py --data-dir /path/to/data
```

首次启动立即引导设置程序口令并生成专用 SSH 密钥，随后必须创建 CA 才能进入主界面。中途返回会退出，下次启动继续完成；已有完整初始化数据时不强制启动解锁。建议使用约 140 列 × 40 行或更大的终端。

界面启动时自动跟随系统语言：中文环境使用简体中文，其他语言或无法识别时使用英文。Windows 读取当前用户的显示语言；Linux 按 `LC_ALL`、`LC_MESSAGES`、`LANG` 的优先级检测。不保存语言偏好、不提供切换按钮，旧 `ui.json` 不再读取。可使用 `--language en` 或 `--language zh-CN` 临时覆盖。用户名称、域名、证书内容及外部工具原始输出不翻译。

## 页面与操作

| 页面 | 用途 |
| --- | --- |
| 部署 | 保存配置批次，查看详情，部署或导出离线包 |
| 站点 | 配置域名、源头、TLS 来源和各区域服务规则 |
| 节点 | 配置目标平台、架构、监听地址、上游及 SSH 路径 |
| 区域 | 定义内网、外网等区域及默认端口 |
| mTLS证书 | 管理用户 Client 证书；二级页面管理私有 CA |
| TLS证书 | 独立管理 Let’s Encrypt 证书、DNS 凭据和 lego |

默认进入部署页。F1～F6 按上述顺序切换页面；Tab 在导航、内容和底部操作间移动，方向键在当前区域内移动。Enter 执行当前控件默认操作，Esc 逐级返回。F10 循环切换快捷键展示与使用帮助。

## 推荐使用流程

1. **区域**：设置 HTTP、HTTPS、中继 HTTPS 三个默认端口。
2. **节点**：选择平台与架构，启用区域并逐行填写绑定 IP，多个地址共用一组端口；`0.0.0.0` 仅监听 IPv4，`::` 仅监听 IPv6；上游地址可自由填写 HTTPS 地址和端口，留空则直达站点源头；节点之间没有父子关系。SSH 路径必填，每行一个 IP，按跳板到目标的顺序填写；最后一行是目标节点，与上游地址独立。
3. **站点**：填写唯一域名、不带路径的源头 URL，以及各区域的 HTTP、HTTPS 或 HTTPS + mTLS 服务规则。
4. **私有 CA**：首次启动时创建，之后可在“mTLS证书 → CA 管理”重新初始化。名称输入统一前缀，例如 `Personal WEB`，分别生成 `Personal WEB Root CA`、`Personal WEB TLS CA`、`Personal WEB mTLS CA`、`Personal WEB Relay CA`。中继始终使用私有 CA，因此使用公共网站证书时也需要初始化。按需签发用户 Client、导出 P12；使用私有网站 TLS 时，向访问设备安装导出的信任 CA。
5. **公共 TLS（可选）**：在“TLS证书”配置域名、通配选项及每条记录独立的 DNS 凭据，在 lego 管理中下载工具；将站点 TLS 来源设为公共 CA。
6. **生成与部署**：在“部署”新增配置批次，进入详情选择 Caddy 版本后部署；也可直接使用“新增并部署”。没有 SSH 条件时，在详情中“导出 package”，将各节点对应的 `.run` 拷贝到目标机执行 `sh 文件.run`。

编辑允许暂存不完整配置，错误在表格与导航中标记；修正后才能生成。SSH 路径为空或无效也属于配置错误；SSH 编辑弹窗必须修正后才能保存。

公共 TLS 仅支持 Let’s Encrypt，DNS 服务商目前支持阿里云和 DNSPod。**默认使用测试服务器，测试证书不受系统默认信任。** 正式使用前切换环境；两种环境共用域名、通配选项和 DNS 凭据，证书、私钥与 ACME 申请状态隔离。申请需要本机访问 CA 与 DNS API。

生成批次只处理公共 HTTPS 站点实际匹配的证书，精确域名优先于一级通配，按需申请或续签，最多并发三条。不相关记录不会随批次生成申请；“全部申请”则处理当前环境全部记录。目前没有后台定时续期，需要主动生成并部署新批次以更新节点证书。

## 配置批次与部署包

- **配置批次**：固化配置、节点材料和证书，不绑定 Caddy 版本，也不保存 `.run`。后续修改配置或重置证书不会改变已有批次。
- **SSH 部署**：选择 Caddy 版本，逐节点探测；只向版本不符的节点携带二进制。临时组包后先上传全部节点，再逐个部署。
- **导出 package**：为每个节点生成包含二进制的离线 `.run`。导出文件不另建管理索引，由使用者保管。

目标平台为 Debian 13（systemd）和 OpenWrt 25.12（procd）。Caddy 使用官方标准版二进制，由本程序管理，不依赖 apt/apk 的 Caddy 包。目标机无需联网下载 Caddy；部署脚本要求系统级权限，不自动 sudo，服务目前以 root 运行。

SSH 固定使用 root、22 端口，沿节点独立填写的 SSH 路径逐跳连接，不再根据上游地址推导。通过“SSH 公钥”查看手动授权方法；首次连接或主机指纹变化时需确认身份。探测失败可重试或停止，上传／部署失败可重试、跳过或停止。停止保留已完成操作，不自动回滚。

全部节点部署成功后清理本地临时包并尝试清理远端上传的 `.run`；失败、跳过或停止时保留现场。旧配置可通过目标机辅助脚本手动恢复：

```bash
# Debian；OpenWrt 改用 /usr/lib/smooth-caddy/manage
/usr/local/lib/smooth-caddy/manage list
/usr/local/lib/smooth-caddy/manage switch <批次标识>
```

目标机保留最近五份成功配置，失败现场保留；Caddy 二进制按版本复用，不自动清理。本地配置批次也不自动清理。完整路径见[部署布局](docs/product.md#固定文件布局)。

## 数据、口令与搬迁

| 路径（相对于数据目录） | 内容 |
| --- | --- |
| `smooth-caddy.db` | 配置、私有 CA、Client、公共 TLS 材料、DNS 凭据、SSH 身份与主机信任记录 |
| `tool_caddy/releases.json` | 官方版本列表缓存 |
| `tool_caddy/` | Caddy 二进制缓存 |
| `tool_lego/lego` | 本机申请公共证书使用的 lego 工具 |
| `releases/` | 配置批次、索引、元数据及文件哈希 |
| `.tmp/` | 下载、解压、部署和导出等临时文件 |
| `backups/` | 数据库格式迁移前的完整备份，不自动清理 |

P12 与信任 CA 固定导出到 `~/smooth-caddy-export/`，离线部署包导出到其 `packages/` 子目录；使用 `--data-dir` 不改变导出位置。导出目录在导出时创建，界面显示完整路径。Windows 对应用户目录下的 `.smooth-caddy` 与 `smooth-caddy-export` 文件夹，不位于 Documents 内。信任 CA 是根证书的 DER `.cer`，不含私钥；P12 包含用户证书、私钥和证书链，使用独立导出口令。

持久私钥、DNS 凭据和 ACME 私密状态由同一个程序口令加密。验证后解锁至进程退出，配置本身不加密；修改配置也需解锁。重置 SSH 私钥、重新初始化 CA 另需危险确认和再次验证口令。

配置批次材料加密保存，读取需要程序解锁。手动导出的部署包使用独立导出口令，目标机需有 `openssl` 命令并交互输入口令。SSH 部署临时包和目标机运行材料仍含明文私钥。

旧版本升级后需在退出程序的情况下，将旧 `data/` 内的全部内容（包括隐藏文件）复制到 `~/.smooth-caddy/`，不要复制成 `~/.smooth-caddy/data/`；也可通过 `--data-dir` 继续使用原目录。旧 `export/` 中需保留的文件可另行复制到 `~/smooth-caddy-export/`。程序不自动迁移旧目录。

搬迁或备份前退出程序，复制整个数据目录；源码运行时还需在新环境重建虚拟环境，不建议直接复制 `.venv/`。索引与清单采用相对路径，数据目录可整体迁移。

以首次正式发布的数据格式为兼容基线，不追溯支持所有开发期格式。后续数据结构升级允许并要求明确的版本迁移，迁移前备份；遇到更新版本的数据应拒绝写入。当前数据库格式为 6：打开正式发布的版本 2、3、4 或 5 数据库时，先在数据目录的 `backups/` 内生成完整 SQLite 备份，再以事务转换配置及 SSH 路径并升级版本；失败回滚，备份失败则不迁移。升级前退出所有旧程序。版本 1 等开发期格式仍需一次性转换，更新版本的数据库拒绝写入。旧程序不能打开升级后的数据库。如需回退，退出程序后在独立目录恢复 `backups/smooth-caddy-v<旧版本>-<唯一标识>.db` 为 `smooth-caddy.db`，配合升级前备份的批次目录使用；新格式批次不能交给旧程序读取。

绑定地址升级将原单个 IP 转为地址列表，端口仍共用一组；跨区域监听冲突会同时标记双方并阻止生成。

上游地址迁移会将旧节点／区域引用展开为 HTTPS URL，失效引用标错而不自动直达源头。中继使用专用 Relay CA 和固定 TLS 名称 `relay.smooth-caddy.internal`，不绑定具体节点证书；有效中继客户端可自由互联，用户证书不能用于中继。删除节点不撤销已签发证书，自由 URL 不做环路检测。已有批次不改写；新旧中继认证配置不保证互通，须重新生成并在维护窗口协调部署全部相关节点。

SSH 升级会将旧业务关系推导的路径展开为独立路径；缺少地址、上游丢失或循环等无法完整展开的路径置空并标记错误，需要补全。新批次 metadata 格式为 5，旧格式 1、2、3、4 只在读取时转换，不改写原文件。主机信任改为按连接路径前缀区分；旧节点主机记录保留但不自动套用，升级后首次逐跳连接需要重新确认指纹。

## 开发与文档

- [产品与交互规则](docs/product.md)：配置模型、证书规则、部署布局及 TUI 行为。
- [证书模块接口](docs/ca-lite-interface.md)：私有 PKI、公共 TLS 和密钥保护边界。
- [任务系统](docs/supertaskrunner.md)：任务计划、进度事件、并发与失败处理。

入口为 `smooth_caddy.py`；业务在 `app/network/`，界面在 `app/tui/`，测试在 `tests/`。开发目录保持模块化；独立发布物使用 PyInstaller，按运行主机的平台与架构构建，不包含用户数据。该发布计划与给节点生成的 `.run` 是两件事。

```bash
.venv/bin/python -m compileall -q smooth_caddy.py app tests
.venv/bin/python -m unittest discover -s tests
```

可用 `CADDY_TEST_BINARY=/path/to/caddy .venv/bin/python -m unittest discover -s tests -p test_relay.py` 运行本机真实 Caddy 中继集成测试（已验证 Caddy 2.11.7）；未设置该变量时跳过真实进程测试。

自动测试使用临时数据及网络／SSH 替身，覆盖业务和 TUI 回归，不代表真实 DNS、所有目标设备、自启动、恢复或跨架构兼容性均已验收。当前不声明未经验证的平台支持范围。

## 仓库范围

仓库仅包含入口、`app/` 源码、合成数据测试、当前文档、构建脚本、GitHub 工作流及许可证。真实运行数据、`data.bak/` 等备份、证书、凭据、工具缓存、导出物与本地产物不得提交。发布归档通过 GitHub Releases 分发，不进入源码历史。发布前运行 `python tools/audit_source.py` 检查 Git 跟踪范围和常见凭据模式；测试仅使用合成凭据。

## 版本与发布约定

仓库按公开项目维护，本项目采用 [MIT 许可证](LICENSE)；第三方依赖继续遵循各自许可证。

- 发布标签为 `vX.Y.Z`，初始标签为 `v0.1.0`。构建产物版本为 `X.Y.Z.commit`，`commit` 为对应提交的短哈希，例如 `0.1.0.a1b2c3d4`。
- 原则上每次提交增加 `Z`；这是文档约定，不设置强制检查，也不要求每次提交都发布标签。
- 数据结构变化时增加 `Y`，`Z` 归零；范围包括数据库、持久配置批次和部署包格式。其余修改增加 `Z`。`X` 暂时保持 `0`，后续由维护者决定。
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

解压后启动程序，默认数据位于当前用户主目录下的 `~/.smooth-caddy/`，与源码运行一致。退出后替换程序进行升级，保留数据目录；数据格式变更遵循前述兼容与迁移规则。

构建机的 Python、架构、libc 和依赖版本会写入 `build-info.json`。GitHub 发布使用 Ubuntu 22.04（glibc 2.35）构建 Linux 包，不保证更旧的 glibc 系统可运行。许可证收集包含构建环境包及可识别的系统库声明，是保守收集，不等于完成全部依赖授权审核。详见 [第三方声明](THIRD_PARTY_NOTICES.md)。

## 授权与外部服务

本项目采用 [MIT 许可证](LICENSE)；第三方项目保持各自授权，详见 [第三方声明](THIRD_PARTY_NOTICES.md)。

节点代理使用 [Caddy](https://github.com/caddyserver/caddy)，许可证为 [Apache-2.0](https://github.com/caddyserver/caddy/blob/master/LICENSE)。本程序下载官方标准版二进制，离线 package 及部分 SSH 部署包会携带该二进制。分发这些包时，应随附所用版本的许可证，并保留适用的版权、归属及上游 NOTICE 声明（如有）；不能仅用网页链接代替随包许可文本。

公共证书申请调用 [lego](https://github.com/go-acme/lego)，其许可证为 [MIT](https://github.com/go-acme/lego/blob/master/LICENSE)。申请使用 Let’s Encrypt 服务，程序调用 lego 时传入接受条款选项，使用者应阅读其[订户协议及相关文件](https://letsencrypt.org/repository/)。软件许可证与证书服务条款是不同事项。

正式发布前，按实际分发内容整理第三方声明：

- 独立程序：Python 运行时、Textual、AsyncSSH、cryptography 及实际收录的传递依赖和原生库。
- 附带工具或部署包：Caddy、lego 及相应二进制包含的依赖。
- 每项记录版本、来源和许可证，随包提供要求保留的许可与版权文本；若修改上游文件，按其条款标明修改。

发布脚本自动收集 Python、已安装依赖及可识别的系统库许可文本，并随包携带；收集结果和无法自动确认的项目记录在 build-info.json。携带 Caddy 的部署包同时包含 Caddy 和 Go 的许可文本。分发前仍需核对所选版本的额外声明。

## 致谢

感谢 Lucky 项目及其作者，提供了优秀的个人网络工具，也给了我开发这个项目的启发。

项目名称 Smooth Caddy 向 Michael Jackson 的《Smooth Criminal》致敬。

> 世界人民大团结万岁。
>
> L’Internationale Sera le genre humain.
>
> And the world will be as one.

Windows 验证包：推送 `preview/**` 分支会运行 Windows x64 测试和 `tools/build_release.py --preview`，产物保存在 Actions Artifacts 中 14 天，不创建 Release。预览版本以 `preview.<提交哈希>` 标识，要求干净工作区，无需版本标签。
