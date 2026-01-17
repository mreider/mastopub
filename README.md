# Mastopub

A GitHub Action that automatically publishes Hugo blog posts to Mastodon as threaded posts.

When you add `mastodon: true` to a post's frontmatter and push to GitHub, this action will:
1. Parse the post content
2. Split it into thread-sized chunks (at paragraph/sentence boundaries)
3. Post it as a thread on Mastodon with a link to your article
4. Track what's been posted to avoid duplicates

## Quick Start

### Step 1: Create a Mastodon Application

1. Log in to your Mastodon instance (e.g., `mastodon.social`, `hachyderm.io`, `ieji.de`)
2. Go to **Preferences** → **Development** → **New Application**
   - Or navigate directly to: `https://YOUR-INSTANCE/settings/applications`
3. Fill in:
   - **Application name:** `Blog Publisher` (or whatever you want)
   - **Website:** Your blog URL (optional, just for reference)
   - **Redirect URI:** Leave as default (`urn:ietf:wg:oauth:2.0:oob`)
   - **Scopes:** Check **`write:statuses`** and **`write:media`** (uncheck everything else)
4. Click **Submit**
5. You'll see three credentials:
   ```
   Client key:        (ignore this)
   Client secret:     (ignore this)
   Your access token: abc123xyz...  ← Copy THIS one
   ```
   Only the **access token** is needed. The client key and secret are for OAuth flows which we don't use.

### Step 2: Add Secrets to Your GitHub Repository

Go to your Hugo blog's GitHub repository:

1. Navigate to **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Add this secret:

| Name | Value |
|------|-------|
| `MASTODON_ACCESS_TOKEN` | Your access token from Step 1 |

### Step 3: Create the Workflow File

Create a file in your Hugo repository at `.github/workflows/mastodon.yml`:

```yaml
name: Post to Mastodon

on:
  # Runs after your Hugo site deploys
  push:
    branches:
      - main
    paths:
      - 'content/**'

  # Allows manual testing
  workflow_dispatch:
    inputs:
      dry_run:
        description: 'Dry run (test without posting)'
        type: boolean
        default: false

jobs:
  post:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Post to Mastodon
        uses: mreider/mastopub@v1
        with:
          mastodon_instance: 'https://mastodon.social'  # ← Change to your instance
          mastodon_token: ${{ secrets.MASTODON_ACCESS_TOKEN }}
          blog_url: 'https://yourblog.com'              # ← Change to your blog URL
          dry_run: ${{ inputs.dry_run || 'false' }}

      - name: Commit tracking file
        run: |
          git config user.name "${{ github.actor }}"
          git config user.email "${{ github.actor_id }}+${{ github.actor }}@users.noreply.github.com"
          git add .github/mastodon-published.json
          git diff --staged --quiet || git commit -m "Track published Mastodon posts"
          git push
```

**Important:** Change these values:
- `mastodon_instance`: Your Mastodon server URL (e.g., `https://ieji.de`)
- `blog_url`: Your blog's URL (e.g., `https://mreider.com`)

### Step 4: Mark Posts for Mastodon

Add `mastodon: true` to the frontmatter of any post you want to publish:

```yaml
---
title: "My Blog Post Title"
date: 2025-01-17
author: "Your Name"
image: "/images/featured.jpg"
mastodon: true
---
```

This posts a **single toot** with:
- Default text: "My latest post: {title}"
- Link to your blog post
- Featured image attached

#### Customizing the Toot Text

Add `mastodon_text` to write your own message:

```yaml
---
title: "My Blog Post Title"
image: "/images/featured.jpg"
mastodon: true
mastodon_text: "Just published my thoughts on AI and creativity. Check it out!"
---
```

#### Full Thread Mode

To post the **entire article** as a threaded series of posts, add `mastodon_thread: true`:

```yaml
---
title: "My Blog Post Title"
image: "/images/featured.jpg"
mastodon: true
mastodon_thread: true
---

Your full post content here will be split into a thread...
```

### Step 5: Push and Publish

```bash
git add .
git commit -m "Add new blog post"
git push
```

The action will:
1. Find all posts with `mastodon: true`
2. Check which ones haven't been posted yet
3. Post new ones as Mastodon threads
4. Save the tracking file to prevent re-posting

---

## Configuration Reference

### Action Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `mastodon_instance` | Yes | - | Your Mastodon instance URL |
| `mastodon_token` | Yes | - | Your Mastodon access token |
| `blog_url` | Yes | - | Your blog's base URL |
| `content_dir` | No | `content` | Path to Hugo content directory |
| `visibility` | No | `public` | Post visibility: `public`, `unlisted`, or `private` |
| `dry_run` | No | `false` | Test without actually posting |

### Action Outputs

| Output | Description |
|--------|-------------|
| `posts_published` | Number of posts published in this run |

---

## Frontmatter Options

| Field | Required | Description |
|-------|----------|-------------|
| `mastodon: true` | Yes | Enable Mastodon posting for this post |
| `mastodon_text` | No | Custom text for single post (default: "My latest post: {title}") |
| `mastodon_thread: true` | No | Post full content as a thread instead of single post |
| `image` | No | Featured image URL, attached to first/only post |

---

## How It Works

### Posting Modes

**Single Post (default):**
- Posts one toot with your custom text (or default message) + link + featured image
- Best for sharing new posts with a brief intro

**Thread Mode (`mastodon_thread: true`):**
- Posts the entire article content as a series of replies
- Featured image on first post, body images distributed throughout
- Best for long-form content you want fully readable on Mastodon

### Thread Format

For each blog post, Mastopub creates a thread like this:

**First post:**
```
My Blog Post Title

https://yourblog.com/tech/my-post/

[First ~400 characters of content...]
```

**Reply posts:**
```
[Next chunk of content...]
```

### Image Support

Mastopub automatically includes images in your Mastodon thread:

- **Featured image** (from `image:` frontmatter) → Attached to the first post
- **Body images** (markdown `![alt](url)`) → Attached to the post containing that section of content

Images are downloaded from your blog and uploaded to Mastodon. Each post can have up to 4 images (Mastodon's limit).

Example post with images:
```yaml
---
title: "My Trip to Japan"
image: "/images/tokyo-skyline.jpg"  # ← Featured image on first post
mastodon: true
---

Here's what I saw on day one...

![Temple in Kyoto](/images/kyoto-temple.jpg)  # ← Attached to this chunk

More text about the trip...

![Mount Fuji](/images/fuji.jpg)  # ← Attached to this chunk
```

### Content Processing

1. **Extracts images** - Featured image and body images are uploaded to Mastodon
2. **Removes markdown formatting** - Links (keeps text), code blocks, emphasis
3. **Splits at natural boundaries** - Paragraphs first, then sentences, then words
4. **Respects character limits** - Each chunk is ≤480 characters (safe margin for 500 limit)

### Tracking

Published posts are tracked in `.github/mastodon-published.json`:

```json
{
  "published": [
    "content/tech/my-first-post/index.md",
    "content/life/another-post/index.md"
  ]
}
```

This file is committed automatically to prevent duplicate posts.

---

## Examples

### Run After Hugo Deploy

If you have an existing Hugo deploy workflow, trigger Mastopub after it completes:

```yaml
on:
  workflow_run:
    workflows: ["Deploy Hugo Site"]  # ← Your deploy workflow name
    types:
      - completed
    branches:
      - main
```

### Post as Unlisted

```yaml
- uses: mreider/mastopub@v1
  with:
    mastodon_instance: 'https://mastodon.social'
    mastodon_token: ${{ secrets.MASTODON_ACCESS_TOKEN }}
    blog_url: 'https://yourblog.com'
    visibility: 'unlisted'
```

### Test Without Posting

Run the workflow manually with "Dry run" checked, or:

```yaml
- uses: mreider/mastopub@v1
  with:
    mastodon_instance: 'https://mastodon.social'
    mastodon_token: ${{ secrets.MASTODON_ACCESS_TOKEN }}
    blog_url: 'https://yourblog.com'
    dry_run: 'true'
```

---

## Troubleshooting

### "No new posts to publish"

- Check that your post has `mastodon: true` in the frontmatter
- Check that the post path isn't already in `.github/mastodon-published.json`

### "401 Unauthorized"

- Verify your access token is correct
- Make sure the token has `write:statuses` and `write:media` scopes
- Check that the `MASTODON_ACCESS_TOKEN` secret is set correctly

### Images not appearing

- Make sure your token has `write:media` scope
- Check that the image URLs are accessible (not behind auth)
- Verify images are standard formats (jpg, png, gif, webp)

### "404 Not Found"

- Verify your `mastodon_instance` URL is correct (include `https://`)

### Posts appearing twice

- Make sure the workflow commits the tracking file after posting
- Check that the tracking file commit step has push permissions

---

## License

MIT
