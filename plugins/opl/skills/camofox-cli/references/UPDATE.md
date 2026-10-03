UPDATED: 2026-10-01T04:28:00.179Z
VERSION: {"tree":"076f3ba9747f1687f83b1ad0784856b55197fdb3","commit":"b0e7bacb81fce8dc9452bd3c42104c12560e9301"}
SKILL SOURCE: "https://github.com/redf0x1/camofox-browser/tree/main/skills/camofox-cli"
FIX SOURCES: ["https://github.com/redf0x1/camofox-browser/blob/main/src/cli/index.ts","https://github.com/redf0x1/camofox-browser/blob/main/src/cli/commands/interaction.ts","https://github.com/redf0x1/camofox-browser/blob/main/src/cli/commands/content.ts","https://github.com/redf0x1/camofox-browser/blob/main/src/cli/commands/download.ts","https://github.com/redf0x1/camofox-browser/blob/main/src/cli/transport/http.ts","https://github.com/redf0x1/camofox-browser/blob/main/src/cli/server/manager.ts","https://github.com/redf0x1/camofox-browser/blob/main/CHANGELOG.md","Search current redfox CamoFox CLI implementation for drag, extract-structured, unavailable direct-download endpoint, automatic server startup, and Windows headless support. Compare registration and behavior with both skill files before removing or adding a correction."]
MANAGED FILES: ["references/command-reference.md","SKILL.md"]

FIXES:
- Remove the retired drag command from SKILL.md and command-reference.md. Installed redfox 2.4.8 interaction command registration has no drag command.
- Add extract-structured, which is registered in the content command module but omitted from the upstream skill. Keep the 50-command index consistent: content has eight commands and interaction has five.
- Explain that registered download returns ok:false in reviewed 2.4.8 because its direct-download endpoint is unavailable. Do not report that it downloaded a file. Distinguish tracked downloads from the supported batch-download API.
- Add Windows/WSL and existing-installation guidance. This CLI belongs to redfox's package, connects to loopback at the selected port, reads CAMOFOX_API_KEY, and can automatically start its own server. Do not direct it at Jo's server or promise a visible native Windows desktop from reviewed 2.4.8.
- Remove the Bash-only tool declaration from the entrypoint so the imported instructions do not prescribe a POSIX shell for native Windows CLI use.
- Preserve the eight CLI search engines; they already match the installed implementation and are separate from API navigation macros. Retain local runtime guidance, license, OPL skill references, and explicit invocation-policy metadata during refresh.
