# abap-cli

Bulk export and import of ABAP objects between an SAP system and a local folder.

Pulls a whole package in one HTTP call and pushes back only what you changed —
activating everything in a single mass activation.

```
$ abap pull ZGET_SUBS_API_V2
pulled ZGET_SUBS_API_V2 from dha-110 - 83 files, 67,117 bytes
/Users/you/ZGET_SUBS_API_V2

ZGET_SUBS_API_V2
├── Class Library
│   ├── Classes (5)
│   └── Interfaces (1)
├── Core Data Services
│   └── Data Definitions (21)
├── Message Classes (1)
├── Service Bindings (1)
└── Service Definitions (1)
```

## How it works

The CLI talks to a single endpoint, `/sap/bc/zsync`, which must be installed in the
target system. That endpoint wraps abapGit's object layer, so serialization,
dependency-ordered deserialization and mass activation all happen inside SAP —
the CLI only moves a zip.

```
abap-cli  ──HTTPS──▶  /sap/bc/zsync  ──▶  ZCL_SYNC_*  ──▶  abapGit object layer
```

The CLI is standalone: no SAP GUI, no Eclipse, no abapGit UI, no MCP server.

## Install

```bash
pipx install git+https://github.com/vaibhavgoel-github-1986/abap-cli@release/v1
```

Or for development:

```bash
git clone https://github.com/vaibhavgoel-github-1986/abap-cli
cd abap-cli && python3 -m venv .venv && .venv/bin/pip install -e .
```

Requires Python 3.10+.

## Setup

```bash
abap init            # prompts for name, host, user, client
abap login           # stores the password in the OS keychain
abap ping            # confirms the endpoint answers
```

Systems are stored in `~/.abap-cli/config.json`:

```json
{
  "default_system": "dha-110",
  "systems": {
    "dha-110": {
      "host": "https://sap-dev.example.com:44300",
      "user": "MYUSER",
      "client": "110",
      "insecure": true
    }
  }
}
```

Passwords are never written to that file. They are read from `$ABAP_PASSWORD`, then
the macOS keychain, and only then by prompting. In CI, set `$ABAP_PASSWORD`.

## Commands

| Command | Purpose | Needs SAP |
|---|---|---|
| `abap init` | Add a system | no |
| `abap systems` | List systems and which have a stored password | no |
| `abap login` / `logout` | Manage stored credentials | no |
| `abap ping` | Check the endpoint | yes |
| `abap pull PACKAGE` | Download a package | yes |
| `abap status` | Show local changes | **no** |
| `abap push` | Upload changed objects and activate | yes |

### Pull

```bash
abap pull ZGET_SUBS_API_V2                      # flat src/ layout, sub-packages included
abap pull ZGET_SUBS_API_V2 --no-subpackages     # this package only
abap pull ZGET_SUBS_API_V2 --se80               # SE80-style folder tree
abap pull ZGET_SUBS_API_V2 --dest ~/work/subs   # choose the folder
abap pull ZSOME_PKG --system dha-300            # target another system
```

The default layout is abapGit's flat `src/`, identical to what a GitHub repo would
show. `--se80` mirrors the SE80 object tree instead, with sub-package objects under
`Subpackages/<NAME>/…`. Both push back the same way.

### Status and push

```bash
abap status                       # offline, no password
abap push --dry-run               # validate, write nothing
abap push --transport DHAK900123  # deploy and activate
```

`push` sends only the objects whose files changed. When a source file changes, its
metadata siblings are sent with it, because abapGit deserializes an object from its
complete file set.

Before writing, `push` saves a snapshot zip of the current SAP state under
`.abap/snapshots/`. Reverting is re-importing that zip. Disable with `--no-snapshot`.

A non-zero exit code means at least one object failed to activate; the previously
active version keeps running in that case.

## Local layout

Default (flat, same as a GitHub repo):

```
ZGET_SUBS_API_V2/
├── .abap/
│   ├── manifest.json          # canonical paths + hashes, powers status and push
│   └── snapshots/
├── .abapgit.xml
└── src/
    ├── package.devc.xml
    ├── zcl_subs_query_provider.clas.abap
    ├── zcl_subs_query_provider.clas.xml
    ├── zif_subs_dba.intf.abap
    └── zcds_i_serv_h.ddls.asddls
```

With `--se80`:

```
ZGET_SUBS_API_V2/
├── package.devc.xml
├── Class Library/
│   ├── Classes/ZCL_SUBS_QUERY_PROVIDER/
│   └── Interfaces/ZIF_SUBS_DBA/
├── Core Data Services/Data Definitions/
└── Subpackages/<SUBPKG>/…
```

Either way `manifest.json` keeps each file's canonical abapGit path, which is what
gets sent back on push - so the on-disk arrangement never affects deployment.

## Limitations

- The `/sap/bc/zsync` endpoint must be installed in the target system.
- Deployment is package-scoped; the package must not be covered by an abapGit repo
  bound to a different (for example parent) package.
- Deleting objects is not supported — deleted local files are reported and skipped.
- Keychain storage is macOS-only; elsewhere use `$ABAP_PASSWORD`.

## Licence

MIT
