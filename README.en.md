# Smooth Caddy

[简体中文](README.md) · **English**

A Caddy configuration and deployment tool for personal websites, home networks, and self-hosted services. Manage HTTPS, certificates, and access policies across multiple nodes in one place. Open it when you need to make changes and deploy; it does not need to stay running.

This project grew out of my experience with Lucky. As my personal network expanded to home nodes and cloud servers connected through WireGuard, I wanted centralized configuration and certificate management, different access policies for private and public networks, and DNS provider credentials that stay on the management computer.

![Smooth Caddy deployment overview in English](docs/images/en/deployment.png)

## Features

- **Multi-node configuration**: Organize services by region, node, and site, with an overview of what will be deployed.
- **HTTPS and authentication**: Use a private CA or Let's Encrypt certificates, with optional client mTLS verification.
- **Authenticated relays**: Forward traffic between nodes using TLS and mTLS. Configure service upstreams independently of SSH routes.
- **Deployment and export**: Deploy over SSH, including jump hosts, or export password-encrypted offline `.run` packages.
- **Settings archives**: Save and restore configuration snapshots, and import or export settings as JSON.

One instance manages one network. It does not configure DNS resolution, NAT, or firewalls; public certificate requests use DNS APIs to manage validation records. There is currently no automatic background renewal. Redeploy to update certificates on your nodes.

## Download and get started

**[Download the latest release](https://github.com/JerryFecl3/smooth-caddy/releases/latest)** · [User guide (Chinese)](docs/usage.md) · [Run from source (Chinese)](docs/development.md#从源码运行)

| Purpose | Supported platforms |
| --- | --- |
| Run the management application | Linux x64 (glibc 2.35+), Windows x64 |
| Managed nodes | Debian 13, OpenWrt 25.12; amd64, arm64, armv7, 386 |

Download and extract the archive, then start the application. Follow the prompts to set an application password and create a private CA, configure your regions, nodes, and sites, and deploy. See [Configure your first network (Chinese)](docs/usage.md#配置第一个网络) for the walkthrough.

The interface defaults to your system language, with Simplified Chinese and English available. Choose a language in Settings → Language; changes take effect on next launch. A terminal of about 140 columns by 40 rows is recommended. Data is stored in `~/.smooth-caddy/` by default, and exports go to `~/smooth-caddy-export/`.

Public TLS currently supports Alibaba Cloud DNS and DNSPod. Let's Encrypt uses the **staging environment** by default; switch to production before using certificates for real services.

## Documentation

The detailed guides are currently in Chinese. The user guide includes screenshots of both interface languages.

- [User guide](docs/usage.md): Initialization, certificates, SSH deployment, archives, backups, and upgrades.
- [Development and releases](docs/development.md): Source setup, tests, builds, versioning, and release verification.
- [Product and interaction rules](docs/product.md): The configuration model and current behavior in detail.
- [Certificate module interface](docs/ca-lite-interface.md) · [Task system](docs/supertaskrunner.md): Internal interfaces and architecture constraints.

## License and acknowledgments

This project is licensed under the [MIT License](LICENSE). See [Third-party notices](THIRD_PARTY_NOTICES.md) for dependencies and external services.

Thanks to [Lucky](https://github.com/gdy666/lucky) and its author for an excellent personal networking tool and for inspiring this project.

The name Smooth Caddy is a tribute to Michael Jackson's *Smooth Criminal*.

> 世界人民大团结万岁。
>
> L’Internationale Sera le genre humain.
>
> And the world will be as one.
