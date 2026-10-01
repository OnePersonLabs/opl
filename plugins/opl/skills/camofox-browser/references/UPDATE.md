UPDATED: 2026-10-01T04:28:00.179Z
VERSION: {"tree":"f0eae420ce38c08be5dc57d9e9f737654dc11545","commit":"b04d610f06eed5c783e5a439e5db3b1bac73adbc"}
SKILL SOURCE: "https://github.com/yelban/camofox-browser-skills/tree/main/camofox-browser"
FIX SOURCES: ["https://github.com/jo-inc/camofox-browser/blob/master/README.md","https://github.com/jo-inc/camofox-browser/blob/master/server.js","https://github.com/jo-inc/camofox-browser/blob/master/lib/macros.js","https://github.com/yelban/camofox-browser-skills/tree/main/camofox-browser","Search current Jo CamoFox documentation for CAMOUFOX_EXECUTABLE, CAMOFOX_INTERACTIVE desktop, access-key authentication, and Windows support. Compare the installed package and owned launcher with the Bash bootstrap before changing installation guidance."]
MANAGED FILES: ["references/anti-detection.md","references/api-reference.md","references/macros-and-search.md","scripts/camofox.sh","scripts/setup.sh","SKILL.md","templates/multi-session.sh","templates/stealth-scrape.sh"]
CHECK STATUS: "SUCCESS"

FIXES:
- Adapt the entrypoint for native Windows and WSL and reuse an existing installation. The upstream Bash helpers bootstrap their own installation and lack current access-key handling. Retain them as compatibility material with an explicit read/adapt condition rather than prescribe execution against an existing server.
- Distinguish the Jo REST controller from redfox's camofox CLI. The Jo package exposes camofox-browser and camofox-browser-mcp, not the community entrypoint's assumed camofox command.
- Replace unauthenticated legacy API examples with current route and request guidance. Remove unsupported response-size and session-timeout claims and a stray Markdown fence.
- Replace the claim that JavaScript detection is impossible with a qualified capability description. Check active launch options before describing WebRTC, proxy, locale, humanization, and display behavior.
- Update the macro reference from 13 to 14 entries, including @reddit_subreddit, based on installed Jo 1.18.0 lib/macros.js.
- Retain local runtime guidance, license, OPL skill references, and explicit invocation-policy metadata when refreshing upstream files. Browser startup remains subject to its actual installed wrapper/native version compatibility; this skill does not certify the current local launch.
