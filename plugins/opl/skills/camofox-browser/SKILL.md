---
name: camofox-browser
description: Control a Jo CamoFox browser through its REST API on Windows or WSL. Use for Jo browser navigation, snapshots, page interaction, and session management with an existing installation.
---

# Jo CamoFox browser

Use this skill for `@askjo/camofox-browser`. The separate redfox package, `camofox-browser`, supplies the CLI documented by `$opl:camofox-cli`. Identify the installed package before selecting commands.

## Connect to the installed browser

Read [existing runtime guidance](references/existing-runtime.md) before the first connection or a platform change. Establish the owned launcher, API address, credential source, and browser profile. Reuse an existing installation and controller when available.

Check the authenticated health response before creating a tab. If the service is stopped, use its owned start command. If startup fails, inspect its logs and report the failure. Installation alone does not establish a working browser.

## Control a session

1. Keep `userId` and `sessionKey` stable for the workflow. List existing tabs before opening another tab.
2. Navigate with the installed controller or REST API. Read [API guidance](references/api-reference.md) for endpoint examples and authentication.
3. Get a snapshot and use its current element references to interact. Refresh the snapshot after navigation, form submission, or a page change that invalidates references.
4. Read [search macros](references/macros-and-search.md) when using a navigation macro. Confirm macro support in the installed server.
5. Close tabs created for the task when they are no longer needed. Stop the service only when its lifecycle belongs to the task.

For visible interaction, use the installed desktop launcher. Windows requires the Windows browser binary. WSL requires the Linux binary and a working display, such as WSLg. Keep paths and processes in the selected environment.

## Compatibility references

Read [capability limits](references/anti-detection.md) when selecting launch options or explaining browser behavior.

The bundled Bash helpers and templates are upstream compatibility material. Read `scripts/camofox.sh` and `scripts/setup.sh` when adapting an older POSIX installation. Read `templates/stealth-scrape.sh` or `templates/multi-session.sh` when translating those workflows to an owned controller. They assume a legacy installation, unauthenticated requests, and POSIX tools. Adapt authentication and process ownership before executing them. They are not native Windows commands.

Read [UPDATE.md](references/UPDATE.md) when maintaining this imported skill. It records the upstream package revision, verified local changes, and sources used to reassess them.
