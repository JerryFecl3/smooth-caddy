# Third-party software and services

Smooth Caddy is licensed under the [MIT License](LICENSE). That license does not
replace the licenses of its dependencies or grant rights to their trademarks.

The portable program bundles Python and Python dependencies. Each release
includes a `licenses/` directory containing license and notice files collected
from its build environment, plus `build-info.json` recording their versions.
The inventory can include build-only packages; it is not a list of runtime imports.

| Component | Upstream license/source |
| --- | --- |
| Python | [Python license](https://docs.python.org/3/license.html) |
| Textual | [MIT](https://github.com/Textualize/textual/blob/main/LICENSE) |
| AsyncSSH | [EPL-2.0 or GPL-2.0-or-later](https://github.com/ronf/asyncssh/blob/develop/COPYRIGHT) |
| cryptography | [Apache-2.0 or BSD-3-Clause](https://github.com/pyca/cryptography/blob/main/LICENSE) |
| PyInstaller bootloader | [GPL exception for generated executables](https://pyinstaller.org/en/stable/license.html) |

Caddy and lego are separate executables downloaded on demand, not bundled with
the Smooth Caddy executable:

- [Caddy](https://github.com/caddyserver/caddy) is Apache-2.0 licensed. Generated
  node packages may contain Caddy; they include the Caddy Apache-2.0 and Go
  license texts under the deployed release’s `licenses/` directory. Additional
  notices required by a particular upstream binary remain applicable.
- [lego](https://github.com/go-acme/lego) is MIT licensed and has its own dependencies.
- Let's Encrypt is a certificate service, not a bundled library. Certificate
  requests accept its [subscriber agreement](https://letsencrypt.org/repository/).
- OpenSSL on the destination host decrypts password-protected node packages;
  it is supplied by the host's package manager, not by these packages.

[Lucky](https://github.com/gdy666/lucky) and its author are acknowledged as
inspiration; Lucky is not bundled or a runtime dependency.
