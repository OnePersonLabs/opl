# Existing Windows or WSL runtime

## Identify ownership

Find the existing `@askjo/camofox-browser` package, configuration, browser bundle, profile, start and stop commands, and controller. Confirm which process owns the selected API port. Do not connect the redfox CLI to a Jo server merely because both use port 9377 by default.

In this repository, check for `.temp/browser-tools/Start-Browser.ps1`, `Stop-Browser.ps1`, and `browser.mjs`. If present, inspect them and their configuration before use. They are local installation artifacts, not shipping files or required paths for other machines. Use their recorded credential source. Do not print the credential.

For an existing PowerShell installation with those files, the controller pattern is:

```powershell
& .\.temp\browser-tools\Start-Browser.ps1
node .\.temp\browser-tools\browser.mjs health
node .\.temp\browser-tools\browser.mjs tabs
node .\.temp\browser-tools\browser.mjs open https://example.com
& .\.temp\browser-tools\Stop-Browser.ps1
```

Run the stop command only when the task owns the service lifecycle. A configured website whitelist can reject the example URL; select an authorized destination.

## Platform and configuration

Use native Windows Node.js, paths, and browser binaries for a Windows installation. Use Linux Node.js, paths, and binaries inside WSL. Check WSLg or another supported display before requesting a visible Linux window. Check localhost connectivity when the controller and service run on different sides of WSL.

Read the installed Jo configuration and [current upstream documentation](https://github.com/jo-inc/camofox-browser) before setting options. Current Jo supports an external executable through `CAMOUFOX_EXECUTABLE` and desktop mode through `CAMOFOX_INTERACTIVE=desktop`. Version support can change. Preserve browser validation when resolving wrapper and native binary incompatibilities.

Jo authentication and redfox authentication use different configuration names. Use the Jo access key through its supported bearer header. Read a stored key from its owned private file or user environment variable. Avoid placing keys in URLs or command output.

For a new installation, use pnpm when requested. Install in a dedicated directory, retain the lockfile, and approve only required native dependency builds. Do not run the legacy Bash bootstrap against an existing installation; it selects its own home directory, package version, and process lifecycle.

Keep uBlock Origin and website policy configuration in the owned browser installation. Firefox WebsiteFilter restricts page and embedded-page navigation; it does not restrict all network requests. A simple whitelist does not implement approval prompts. Preserve the user's allowed service domains when updating the skill or package.
