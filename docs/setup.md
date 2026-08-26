# Platform credential setup

How to obtain the API credentials each publisher adapter needs. All values go into `.env` (see `.env.example`); everything works in dry-run mode without them.

## Facebook (Graph API)

- Create a Meta app at <https://developers.facebook.com/> and request the permissions `pages_manage_posts`, `pages_read_engagement`, and `pages_show_list`.
- Production use requires Meta **App Review** and **Business Verification** for these permissions.
- Posting is done with a **Page access token**; derive a long-lived one from a long-lived **user** access token.
- Env vars: `META_APP_ID`, `META_APP_SECRET`.

## Instagram (Graph API)

- Requires an Instagram **Business or Creator** account linked to a Facebook Page; publishing goes through the same Meta app as Facebook.
- Permissions: `instagram_basic` and `instagram_content_publish`.
- Publishing is **container-based**: create a media container, then publish the container.
- Env vars: shared with Facebook (`META_APP_ID`, `META_APP_SECRET`).

## LinkedIn

- Create an app at <https://www.linkedin.com/developers/> and add the **"Share on LinkedIn"** product.
- Scopes: `w_member_social` (post as a member) or `w_organization_social` (post as an organization page).
- OAuth access tokens are valid for **60 days**; refresh tokens for **365 days**.
- Env vars: `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`.

## YouTube (Data API v3)

- Create a Google Cloud project, enable **YouTube Data API v3**, and configure OAuth consent.
- Scope: `youtube.upload`.
- Quota: **10,000 units/day** by default; one video upload costs **1,600 units**.
- Apps with an unverified OAuth consent screen upload videos as **private** until they pass verification.
- Env vars: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`.

## Twitter / X (API v2)

- Create a project/app in the X developer portal.
- Auth: **OAuth 2.0 with PKCE**; posting via `POST /2/tweets`.
- There is **no scheduled-posting endpoint** — posts go out immediately, so scheduling is handled by our own queue.
- Env vars: `TWITTER_CLIENT_ID`, `TWITTER_CLIENT_SECRET`.

## TikTok (Content Posting API)

- Apply for the **Content Posting API** in the TikTok developer portal.
- Scopes: `video.upload` and `video.publish`.
- Limit: **25 posts per day**; app approval typically takes **2–6 weeks**.
- Access tokens last **24 hours**; refresh tokens **365 days** — the token manager refreshes them automatically.
- Env vars: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`.

## Browser-automation platforms (X / TikTok)

For platforms where we post via Playwright instead of an official API:

- Persistent browser profiles live under `browser_profiles/` and stay on the local machine.
- On first run, a **headful browser window** opens — log in manually once; the session is reused afterwards.
- ⚠ Browser automation may violate these platforms' Terms of Service. Use only with your own accounts, respect `MAX_POSTS_PER_ACCOUNT_PER_DAY`, and get legal review before production use.
