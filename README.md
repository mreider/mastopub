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
   - **Scopes:** Check only **`write:statuses`**
4. Click **Submit**
5. Copy the **Access Token** (you'll need this in Step 2)

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
mastodon: true          # ← Add this line
---

Your post content here...
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

## How It Works

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

### Content Processing

1. **Removes markdown formatting** - Images, links (keeps text), code blocks, emphasis
2. **Splits at natural boundaries** - Paragraphs first, then sentences, then words
3. **Respects character limits** - Each chunk is ≤480 characters (safe margin for 500 limit)

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
- Make sure the token has `write:statuses` scope
- Check that the `MASTODON_ACCESS_TOKEN` secret is set correctly

### "404 Not Found"

- Verify your `mastodon_instance` URL is correct (include `https://`)

### Posts appearing twice

- Make sure the workflow commits the tracking file after posting
- Check that the tracking file commit step has push permissions

---

## License

MIT
