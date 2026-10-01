# Search macros

Use a macro through Jo's navigation API or an installed controller that supports it. The redfox CLI's `search --engine` command is a different interface.

The reviewed Jo 1.18.0 server supports these 14 macros:

| Macro | Purpose |
| --- | --- |
| `@google_search` | Google search |
| `@youtube_search` | YouTube search |
| `@amazon_search` | Amazon search |
| `@reddit_search` | Reddit search |
| `@reddit_subreddit` | Reddit subreddit |
| `@wikipedia_search` | Wikipedia search |
| `@twitter_search` | X/Twitter search |
| `@yelp_search` | Yelp search |
| `@spotify_search` | Spotify search |
| `@netflix_search` | Netflix search |
| `@linkedin_search` | LinkedIn search |
| `@instagram_search` | Instagram tag search |
| `@tiktok_search` | TikTok search |
| `@twitch_search` | Twitch search |

For a supported macro, send `userId`, `macro`, and `query` to `POST /tabs/:tabId/navigate` with the installation's authentication. Confirm the current macro list in the installed `lib/macros.js` or [upstream implementation](https://github.com/jo-inc/camofox-browser/blob/master/lib/macros.js).

Refresh the snapshot after navigation. Login state, website policy, and destination availability can affect the result. A macro does not bypass the configured website whitelist.
