# Jo REST API guidance

Read [existing runtime guidance](existing-runtime.md) before connecting. Use the installation's owned API address and credential source. Current access-key deployments require the supported bearer header. Prefer an existing controller that reads its private key without printing it.

The following routes are present in the reviewed Jo 1.18.0 server. Confirm fields and response shapes in the installed server before using a route that the existing controller does not expose.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/health` | Service health |
| POST | `/tabs` | Create a tab |
| GET | `/tabs?userId=...` | List a user's tabs |
| POST | `/tabs/:tabId/navigate` | Navigate by URL or supported macro |
| GET | `/tabs/:tabId/snapshot?userId=...` | Snapshot with element references |
| POST | `/tabs/:tabId/click` | Click by element reference |
| POST | `/tabs/:tabId/type` | Enter text |
| POST | `/tabs/:tabId/scroll` | Scroll the page |
| POST | `/tabs/:tabId/back` | Go back |
| POST | `/tabs/:tabId/forward` | Go forward |
| POST | `/tabs/:tabId/refresh` | Reload |
| GET | `/tabs/:tabId/links?userId=...` | Read links |
| GET | `/tabs/:tabId/screenshot?userId=...` | Receive PNG bytes |
| DELETE | `/tabs/:tabId?userId=...` | Close a tab |
| DELETE | `/sessions/:userId` | Close the owned user's session |

## Request examples

For `POST /tabs`, keep `userId` and `sessionKey` stable:

```json
{"userId":"local-research","sessionKey":"research","url":"https://example.com"}
```

For a blank tab, omit the `url` field. Use an allowed destination when a website whitelist is active.

For `POST /tabs/:tabId/navigate`, send either a URL or a supported macro:

```json
{"userId":"local-research","url":"https://example.com"}
```

```json
{"userId":"local-research","macro":"@google_search","query":"browser automation"}
```

For `POST /tabs/:tabId/click`, use the latest snapshot's element reference:

```json
{"userId":"local-research","ref":"e1"}
```

For `POST /tabs/:tabId/type`, send the element reference and text:

```json
{"userId":"local-research","ref":"e2","text":"example"}
```

URL-encode path and query identifiers. Do not place credentials in those fields. Refresh the snapshot after navigation or an interaction that changes the page.

## Ownership and errors

A server can share its browser process across multiple user contexts. Closing a session or stopping the service can affect more than the current tab. Use the lifecycle owner and configured session timeout as the authority; do not assume an upstream example's timeout or process layout.

Report failed HTTP responses and browser startup errors. Do not disable authentication, validation, or website policy to make an example succeed. Read the installed server and [current upstream implementation](https://github.com/jo-inc/camofox-browser/blob/master/server.js) for routes outside this reference.
