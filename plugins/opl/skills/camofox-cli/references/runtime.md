# Runtime selection

This CLI belongs to redfox's `camofox-browser` package. Confirm the installed package before using it. The Jo package and community Bash wrapper use different interfaces.

If the package is installed in a project, use its existing pnpm executable context rather than adding a global installation:

```text
pnpm --dir <installation-directory> exec camofox --help
pnpm --dir <installation-directory> exec camofox --port <owned-port> server status --format json
```

Set `CAMOFOX_API_KEY` from the owned private credential source when the server requires it. The reviewed CLI uses a bearer header and connects to `127.0.0.1` at the selected port. Keep credentials out of printed commands and URLs.

Many browser commands automatically start the redfox server when no service is reachable. Confirm the package and port before executing them. Do not point this CLI at the existing Jo service on port 9377 or assume their API shapes match.

Use the Windows package and native paths on Windows. Use the Linux package and paths inside WSL. Redfox's reviewed 2.4.8 Windows support is headless; do not promise a visible native Windows desktop from this CLI. A Linux desktop requires an available display, such as WSLg, and supported launch configuration.

Use a stable `--user` value and refresh snapshots after page changes. Stop only a server whose lifecycle belongs to the task. Preserve existing profiles and website policy settings.
