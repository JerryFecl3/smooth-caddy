"""Product usage guide, shared by the help dialog."""

USAGE_GUIDE = """首次启动设置程序口令和根 CA 名称，生成 SSH 密钥及 CA。CA 名称填写前缀，例如 Personal WEB；程序会分别追加 Root CA、TLS CA、mTLS CA、Relay CA。请备份数据目录和口令，之后可在 CA 管理中重新初始化。

Smooth Caddy 用于维护一个网络中的多节点 Caddy 配置。区域定义服务边界，节点决定监听位置，站点决定提供哪些服务；可直接部署当前设置或导出离线 .run 安装包；设置可单独存档。

各模块的作用

设置
区域和存档统一在设置页顶部切换，右侧可导入配置或修改口令。导入配置确认后直接应用于当前，不创建存档。进入设置默认显示区域，关闭口令弹窗后保留当前子页。部署始终为主导航第一项。

部署
总览按节点、区域、站点的配置顺序展示最终 SSH 目标、绑定地址端口及站点服务方式。只使用当前设置。左侧导出、部署针对选中节点，右侧全部导出、全部部署针对所有节点。列表回车不触发操作。选择 Caddy 版本后执行。两者共用证书准备与临时打包流程，不保存生成材料。

设置 → 存档
保存当前站点、节点、区域、顺序及各站点源证书校验选项，“新增存档”保存当前设置；载入、删除、导出针对选中存档。列表回车无默认操作。不包含 TLS/mTLS 配置、凭据和材料。恢复或导入先确认整体替换，不自动保存旧设置；使用存档部署须先恢复。设置顶部的“导入配置”填写 JSON 路径；导出选中存档时预填 ~/smooth-caddy-export/settings/ 下的保存路径，可修改，已有文件需确认覆盖。

站点
配置名称、服务域名和源地址。源地址弹窗中可勾选校验 HTTPS 源证书，仅影响当前站点，默认不勾选。在各区域启用 HTTPS；TLS 来源和 mTLS 可继承区域默认值或分别覆盖。一个站点对应一个域名，自动应用于各节点已启用的区域。

节点
配置目标平台、CPU 架构、独立的 SSH 路径和上游 HTTPS 地址。启用区域时逐行填写绑定 IP，默认无需填写端口，可在绑定地址弹窗勾选覆盖 HTTP／HTTPS／中继端口（80／443／8443）。三个端口均为节点—区域独立配置，HTTP 仅用于跳转。列表默认只显示 IP，有端口覆盖时显示全部三端口。0.0.0.0 仅监听 IPv4，:: 仅监听 IPv6。节点至少两行，平台与架构分行，绑定地址逐行展示。SSH 地址显示最终目标，有跳板时第二行显示跳转地址数量。上游显示“直连”，或分两行显示“中继”和 HTTPS 地址。监听冲突会同时标记双方区域，编辑时可查看具体原因。SSH 每行一个 IP，最后一行是目标，不能为空；Enter 换行，Ctrl+S 保存。上游选择“直连”直接访问站点源头；选择“中继”后必须填写已存在的中继服务地址和端口，不引用已有节点；请避免转发环路。中继双方须属于同一中继 CA 体系。

设置 → 区域
定义内网、外网等服务区域，以及默认 TLS 来源与 mTLS 开关（新增区域默认私有 CA、关闭 mTLS；初始内外网均为私有 CA，外网开启 mTLS）。新增区域后，已有节点和站点默认不启用它。

mTLS证书
签发、启用或禁用用户 Client 证书，并导出 P12，供用户访问需要 mTLS 的站点。CA 管理位于此页面内，用于初始化私有 CA、导出信任 CA。客户端使用私有 HTTPS 时需信任该 CA。

TLS证书
管理 Let’s Encrypt 公共证书及各条记录的 DNS 服务商凭据，提供申请、强制申请和 lego 工具管理。站点选择公共 CA 后，按精确域名优先、一级通配其次匹配。测试环境的证书不受浏览器默认信任。

列表排序

在节点、站点、区域、TLS证书列表中，F7 / F8 上移／下移当前条目，立即保存顺序；仅列表获得焦点时生效。

推荐使用流程

1. 设置程序口令，并在“mTLS证书 → CA 管理”中初始化私有 CA。即使站点使用公共 CA，中继链路仍需要私有 CA。
2. 创建区域，再添加节点，填写平台、架构、监听地址和可选上游 HTTPS 地址。
3. 添加站点，配置域名、源头、TLS 来源及各区域的服务方式。
4. 使用公共 CA 时，先在“TLS证书”中配置对应域名和 DNS 凭据，并准备 lego。需要用户 mTLS 时，签发 Client 证书并导出 P12。
5. 修正界面标记的配置错误。待申请、待续签可以交给部署或 .run 导出流程处理，不必逐条手动申请。
6. 在“部署”选择部署当前设置，或导出 .run。流程只准备本次需要的公共证书，再临时生成运行材料。
7. 在“设置 → 存档”新增、载入或导出存档；使用设置顶部“导入配置”直接替换当前设置。离线 .run 拷贝到目标节点执行 sh 文件.run；远程部署前，在节点页查看 SSH 公钥说明并完成目标节点授权。

后续维护

配置修改、Client 启停或证书更新后，需要部署当前设置才会在节点生效。公共证书没有后台定时续签，请定期运行部署。存档不保存证书；部署或 .run 导出始终使用当前证书体系。

本程序不管理 DNS 解析、路由、端口转发或防火墙，请自行保证域名解析与网络可达。

语言

启动时自动跟随系统语言：中文环境使用简体中文，其他环境使用英文。不保存语言偏好。--language zh-CN 或 --language en 可临时覆盖。用户名称、域名、证书内容及外部工具输出不翻译。

第三方软件与服务条款

Caddy · Apache-2.0 开源许可证
Caddy 是节点上运行的代理服务器。本程序使用官方标准版二进制；分发含 Caddy 的部署包时，应随附对应许可证并保留适用声明。
https://github.com/caddyserver/caddy/blob/master/LICENSE

lego · MIT 开源许可证
lego 是本程序调用的 ACME 客户端。使用、修改和分发须遵守其 MIT 许可证；分发副本时须保留版权及许可声明，软件不提供担保。
https://github.com/go-acme/lego/blob/master/LICENSE

Let’s Encrypt · 证书订户协议
Let’s Encrypt 提供公共证书签发服务，其订户协议（Subscriber Agreement）与 lego 的开源许可证是不同的文件。申请或续签证书前，请阅读并同意适用的订户协议。程序调用 lego 时会传入接受条款的选项。
官方政策与法律文件（包含当前订户协议及隐私政策）：
https://letsencrypt.org/repository/

以上为简要说明，具体条款以官方原文为准。"""


ENGLISH_GUIDE = """On first launch, set an application password and root CA name to generate SSH keys and private CAs. Enter a CA name prefix such as Personal WEB; the application appends Root CA, TLS CA, mTLS CA, and Relay CA. Back up the data directory and keep your password safe. You can reinitialize the CAs in CA Manager.

Smooth Caddy manages Caddy configurations across multiple nodes. Regions define service boundaries, nodes define listening addresses, and sites define services. Deploy current settings remotely or export an offline .run installer. Save settings separately as archives.

Modules

Settings
Switch between Regions and Archives at the top; Import configuration and Change password are on the right. Import applies directly to current settings without creating an archive. Settings opens Regions by default. Closing the password dialog keeps the current tab. Deployment remains first in navigation.

Deployment
The overview follows node, region and site configuration order, showing final SSH targets, bindings and site service modes. Left-side Export and Deploy act on the selected node; right-side Export all and Deploy all act on every node. Enter on the list does nothing. Settings archives are managed separately. Both actions prepare certificates and generate runtime materials temporarily.

Settings → Archives
Save sites, nodes, regions, ordering and per-site origin verification options; New archive saves current settings; Load, Delete and Export act on the selected archive. Enter on the list has no default action. TLS/mTLS settings, credentials and materials are excluded. Restore/import replaces current settings after confirmation without automatically archiving previous settings. Restore first to deploy archived settings. Import configuration is available at the top of Settings and accepts a JSON file path; exporting the selected archive prefills an editable path under ~/smooth-caddy-export/settings/ and confirms overwriting existing files.

Sites
Set a name, domain and origin URL. The origin dialog includes certificate verification for this site, off by default. Enable HTTPS per region; inherit or override TLS source and mTLS independently. Each site has one domain and applies to the regions enabled on each node.

Nodes
Set the target platform, CPU architecture, independent SSH path, and upstream HTTPS address. Enable regions and enter one bind IP per line, all sharing one set of ports. Binding dialogs use default HTTP/HTTPS/relay ports (80/443/8443); check an override to customize a port. All three ports are independent per node-region binding; HTTP only redirects. Lists show IPs only unless a port is customized, then show all three ports. 0.0.0.0 binds IPv4 only; :: binds IPv6 only. Node rows have at least two lines. Platform and architecture are separate lines. SSH address shows the target, with jump count on the second line. Upstream shows Direct or Relay followed by its URL on a second line. Conflicts mark both region cells; edit either cell to see the details. Enter one IP per line for SSH, with the target last. A path is required. Enter adds a line; Ctrl+S saves.  Choose Direct to reach origins directly. Choose Relay to enable the address field; the HTTPS address and port must point to an existing relay service. No node relationship is required; avoid forwarding loops. Both relay peers must share the relay CA.

Settings → Regions
Define regions such as internal and external networks, with default TLS source and mTLS policy (new regions default to private CA with mTLS off; initial Private/Public regions use private CA, with mTLS on for Public). New regions are disabled on existing nodes and sites by default.

mTLS Certificates
Issue, enable, disable, and export Client certificates as P12 files for mTLS sites. CA Manager is available here to initialize private CAs and export the trusted root CA. Clients using private HTTPS must trust that CA.

TLS Certificates
Manage Let's Encrypt public certificates and per-record DNS credentials. Issue or force issuance and manage lego. Public TLS sites match exact domains first, then one-level wildcards. Staging certificates are not trusted by browsers by default.

Suggested workflow

1. Set the application password and initialize the private CA in mTLS Certificates > CA Manager. Relay connections require private CAs even when sites use public certificates.
2. Create regions, then add nodes with platforms, architectures, listening addresses, and upstream settings.
3. Add sites with domains, origins, TLS sources, and service modes for each region.
4. For public TLS, add certificate records and DNS credentials on the TLS Certificates page, then install lego. Issue Client certificates and export P12 files when mTLS is required.
5. Fix configuration errors shown in the UI. Pending issuance and renewal can be handled during deployment or .run export.
6. Choose Deploy or Export .run on the Deployment page. Only required public certificates are prepared before generating runtime materials.
7. Use Archives to save, restore, import or export settings. Select a Caddy version when deploying or exporting .run installers. Before remote deployment, authorize the SSH public key shown on the Nodes page.

Maintenance

After configuration or certificate changes, deploy current settings to update nodes. Archives contain no certificates; deployment and .run export use the current certificate system. Public certificates are not renewed in the background; deploy regularly to refresh node certificates.

This application does not manage DNS records for routing, network routes, port forwarding, or firewalls. Ensure name resolution and network connectivity yourself.

Language

The interface follows your system language at startup: Simplified Chinese for Chinese locales, English otherwise. No language preference is saved. The --language zh-CN or --language en option overrides detection for that launch. Names you enter, domains, certificate contents, and external tool output are not translated.

Third-party software and terms

Caddy · Apache-2.0 license
Caddy is the proxy server running on nodes. This application uses official standard binaries. Distributing packages containing Caddy requires its license and applicable notices.
https://github.com/caddyserver/caddy/blob/master/LICENSE

lego · MIT license
lego is the ACME client used by this application. Use, modification, and distribution are subject to the MIT license. Retain copyright and permission notices when distributing copies; the software is provided without warranty.
https://github.com/go-acme/lego/blob/master/LICENSE

Let's Encrypt · Subscriber Agreement
Let's Encrypt provides public certificate issuance. Its Subscriber Agreement is separate from lego's software license. Read and accept the applicable agreement before requesting or renewing certificates. The application passes the terms-acceptance option to lego.
Official policy and legal documents, including the current Subscriber Agreement and privacy policy:
https://letsencrypt.org/repository/

These are brief descriptions; the official terms govern."""


ENGLISH_GUIDE += "\n\nList ordering\n\nIn Nodes, Sites, Regions and TLS Certificates, F7 / F8 moves the selected item and saves the order immediately. Only active while the list has focus."


def usage_guide():
    from ..i18n import get_language
    return ENGLISH_GUIDE if get_language() == 'en' else USAGE_GUIDE
