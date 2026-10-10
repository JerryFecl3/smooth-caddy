"""Product usage guide, shared by the help dialog."""

USAGE_GUIDE = """首次启动设置程序口令和根 CA 名称，生成 SSH 密钥及 CA。CA 名称填写前缀，例如 Personal WEB；程序会分别追加 Root CA、TLS CA、mTLS CA、Relay CA。请备份数据目录和口令，之后可在 CA 管理中重新初始化。

Smooth Caddy 用于维护一个网络中的多节点 Caddy 配置。区域定义服务边界，节点决定监听位置，站点决定提供哪些服务；生成配置批次后，可远程部署或导出离线包。

各模块的作用

部署
保存配置批次、查看详情、部署到节点或导出 package。批次保存当时的配置与证书；后续修改不会改变已有批次。“新增并部署”可连续完成证书准备、批次生成和部署。

站点
配置名称、服务域名、源头地址和 TLS 来源，并为每个区域选择不提供服务、HTTP、HTTPS 或 HTTPS + mTLS。一个站点对应一个域名，自动应用于各节点已启用的区域。

节点
配置目标平台、CPU 架构、SSH 地址和上游关系。启用区域时填写监听 IP，端口默认继承区域设置，也可分别覆盖。直连节点访问站点源头，转发节点通过上游提供服务。

区域
定义内网、外网等服务区域，以及 HTTP、HTTPS、中继 HTTPS 的默认端口。新增区域后，已有节点和站点默认不启用它。

mTLS证书
签发、启用或禁用用户 Client 证书，并导出 P12，供用户访问需要 mTLS 的站点。CA 管理位于此页面内，用于初始化私有 CA、导出信任 CA。客户端使用私有 HTTPS 时需信任该 CA。

TLS证书
管理 Let’s Encrypt 公共证书及各条记录的 DNS 服务商凭据，提供申请、强制申请和 lego 工具管理。站点选择公共 CA 后，按精确域名优先、一级通配其次匹配。测试环境的证书不受浏览器默认信任。

推荐使用流程

1. 设置程序口令，并在“mTLS证书 → CA 管理”中初始化私有 CA。即使站点使用公共 CA，中继链路仍需要私有 CA。
2. 创建区域，再添加节点，填写平台、架构、监听地址和上游关系。
3. 添加站点，配置域名、源头、TLS 来源及各区域的服务方式。
4. 使用公共 CA 时，先在“TLS证书”中配置对应域名和 DNS 凭据，并准备 lego。需要用户 mTLS 时，签发 Client 证书并导出 P12。
5. 修正界面标记的配置错误。待申请、待续签可以交给生成流程处理，不必逐条手动申请。
6. 在“部署”新增配置批次，或选择“新增并部署”。流程只准备本次需要的公共证书；证书可用后才生成批次。
7. 在批次详情中选择 Caddy 版本并部署，或导出 package，拷贝到目标节点执行 sh 文件.run。远程部署前，按 SSH 公钥说明完成目标节点授权。

后续维护

配置修改、Client 启停或证书更新后，需要新增批次并部署才会在节点生效。已有批次部署或导出时不会重新签发证书；公共证书没有后台定时续签，请定期运行本程序生成新批次。

本程序不管理 DNS 解析、路由、端口转发或防火墙，请自行保证域名解析与网络可达。

语言

在侧栏选择简体中文或英文，保存后下次启动生效。--language zh-CN 或 --language en 可临时覆盖。用户名称、域名、证书内容及外部工具输出不翻译。

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

Smooth Caddy manages Caddy configurations across multiple nodes. Regions define service boundaries, nodes define listening addresses, and sites define services. Generate a configuration batch, then deploy it remotely or export an offline package.

Modules

Deployment
Save configuration batches, inspect details, deploy to nodes, or export packages. Each batch preserves its configuration and certificates; later changes do not modify existing batches. Create and deploy prepares certificates, generates a batch, and deploys it in one flow.

Sites
Set a name, domain, origin URL, and TLS source. Choose Disabled, HTTP, HTTPS, or HTTPS + mTLS for each region. Each site has one domain and applies to the regions enabled on each node.

Nodes
Set the target platform, CPU architecture, SSH address, and upstream relationship. Enable regions and enter listening IPs. Ports inherit region defaults unless overridden. Direct nodes connect to origins; forwarded nodes use their upstream.

Regions
Define regions such as internal and external networks, with default HTTP, HTTPS, and relay HTTPS ports. New regions are disabled on existing nodes and sites by default.

mTLS Certificates
Issue, enable, disable, and export Client certificates as P12 files for mTLS sites. CA Manager is available here to initialize private CAs and export the trusted root CA. Clients using private HTTPS must trust that CA.

TLS Certificates
Manage Let's Encrypt public certificates and per-record DNS credentials. Issue or force issuance and manage lego. Public TLS sites match exact domains first, then one-level wildcards. Staging certificates are not trusted by browsers by default.

Suggested workflow

1. Set the application password and initialize the private CA in mTLS Certificates > CA Manager. Relay connections require private CAs even when sites use public certificates.
2. Create regions, then add nodes with platforms, architectures, listening addresses, and upstream settings.
3. Add sites with domains, origins, TLS sources, and service modes for each region.
4. For public TLS, add certificate records and DNS credentials on the TLS Certificates page, then install lego. Issue Client certificates and export P12 files when mTLS is required.
5. Fix configuration errors shown in the UI. Pending issuance and renewal can be handled during batch generation.
6. Create a configuration batch on the Deployment page, or choose Create and deploy. Only public certificates required by this batch are prepared, before generating the batch.
7. Select a Caddy version in batch details and deploy, or export packages and run sh file.run on each target node. Before remote deployment, authorize the SSH public key on the nodes as described in the SSH guide.

Maintenance

After configuration changes, Client enable/disable changes, or certificate updates, create and deploy a new batch for changes to reach the nodes. Deploying or exporting an existing batch does not reissue certificates. Public certificates are not renewed by a background schedule; run the application regularly to generate new batches.

This application does not manage DNS records for routing, network routes, port forwarding, or firewalls. Ensure name resolution and network connectivity yourself.

Language

Choose Simplified Chinese or English with the sidebar language setting. Saved changes take effect on the next launch. The --language zh-CN or --language en option overrides the saved preference for that launch. Names you enter, domains, certificate contents, and external tool output are not translated.

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


def usage_guide():
    from ..i18n import get_language
    return ENGLISH_GUIDE if get_language() == 'en' else USAGE_GUIDE
