# Smooth Caddy

**简体中文** · [English](README.en.md)

面向个人小站、家庭网络和自托管爱好者的 Caddy 配置与部署工具。在一处管理多个节点的 HTTPS、证书和访问策略，按需打开、调整并部署，无需常驻运行。

这个项目源于我使用 Lucky 的经历：当个人网络扩展为通过 WireGuard 互联的家庭节点和云服务器后，我希望集中管理配置与证书，让内外网采用不同的访问规则，同时让 DNS 服务商密钥留在管理电脑上。

![Smooth Caddy 中文部署总览](docs/images/zh-CN/deployment.png)

## 能做什么

- **多节点配置**：通过区域、节点和站点组织服务，统一查看即将部署的配置。
- **HTTPS 与认证**：支持私有 CA、Let’s Encrypt 公共证书，以及可选的用户 mTLS 验证。
- **可信中继**：节点之间通过 TLS + mTLS 转发，业务上游与 SSH 路径独立配置。
- **部署与导出**：支持 SSH 跳板部署，以及带口令加密的离线 `.run` 包。
- **设置存档**：保存和载入配置快照，通过 JSON 导入、导出设置。

一个实例管理一个网络。程序不配置 DNS 解析、NAT 或防火墙；公共证书申请会通过 DNS API 管理验证记录。目前没有后台自动续期，需要主动重新部署以更新节点证书。

## 下载与开始使用

**[下载最新版本](https://github.com/JerryFecl3/smooth-caddy/releases/latest)** · [使用指南](docs/usage.md) · [从源码运行](docs/development.md#从源码运行)

| 用途 | 支持范围 |
| --- | --- |
| 运行管理程序 | Linux x64（glibc 2.35+）、Windows x64 |
| 被管理节点 | Debian 13、OpenWrt 25.12；amd64、arm64、armv7、386 |

下载、解压并启动程序，按提示设置口令和私有 CA，然后配置区域、节点、站点并部署。首次使用建议从[配置第一个网络](docs/usage.md#配置第一个网络)开始。

界面默认跟随系统语言，支持简体中文与英文；可在“设置 → 语言”中指定语言，下次启动生效。建议终端尺寸约 140 列 × 40 行。默认数据保存在 `~/.smooth-caddy/`，导出保存在 `~/smooth-caddy-export/`。

公共 TLS 目前支持阿里云、DNSPod，默认使用 Let’s Encrypt **测试环境**，正式使用前需切换。

## 文档

- [使用指南](docs/usage.md)：初始化、证书、SSH 部署、存档、备份与升级。
- [开发与发布](docs/development.md)：源码运行、测试、构建、版本约定和发布验证。
- [产品与交互规则](docs/product.md)：详细配置模型与当前行为。
- [证书模块接口](docs/ca-lite-interface.md) · [任务系统](docs/supertaskrunner.md)：内部接口与架构约束。

## 许可证与致谢

本项目采用 [MIT 许可证](LICENSE)，依赖与外部服务见[第三方声明](THIRD_PARTY_NOTICES.md)。

感谢 [Lucky](https://github.com/gdy666/lucky) 项目及其作者，提供了优秀的个人网络工具，也给了我开发这个项目的启发。

项目名称 Smooth Caddy 向 Michael Jackson 的《Smooth Criminal》致敬。

> 世界人民大团结万岁。
>
> L’Internationale Sera le genre humain.
>
> And the world will be as one.
