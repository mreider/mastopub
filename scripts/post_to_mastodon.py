#!/usr/bin/env python3
"""
Post Hugo blog content to Mastodon as a thread.
Reads markdown files, extracts content, splits into chunks, and posts as a thread.
"""

import os
import sys
import json
import re
import time
import requests
import frontmatter
from pathlib import Path


def get_env_var(name: str) -> str:
    """Get required environment variable or exit."""
    value = os.environ.get(name)
    if not value:
        print(f"Error: {name} environment variable is required")
        sys.exit(1)
    return value


def set_github_output(name: str, value: str):
    """Set GitHub Actions output variable."""
    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a') as f:
            f.write(f"{name}={value}\n")


def load_published_posts(tracking_file: Path) -> set:
    """Load the set of already-published post paths."""
    if not tracking_file.exists():
        return set()
    with open(tracking_file, 'r') as f:
        data = json.load(f)
    return set(data.get('published', []))


def save_published_posts(tracking_file: Path, published: set):
    """Save the set of published post paths."""
    tracking_file.parent.mkdir(parents=True, exist_ok=True)
    with open(tracking_file, 'w') as f:
        json.dump({'published': sorted(list(published))}, f, indent=2)


def find_mastodon_posts(content_dir: Path) -> list:
    """Find all posts with mastodon: true in frontmatter."""
    posts = []
    for md_file in content_dir.rglob('*.md'):
        try:
            post = frontmatter.load(md_file)
            if post.get('mastodon', False):
                posts.append({
                    'path': str(md_file),
                    'relative_path': str(md_file.relative_to(content_dir.parent)),
                    'title': post.get('title', 'Untitled'),
                    'content': post.content,
                    'date': post.get('date', ''),
                    'metadata': post.metadata
                })
        except Exception as e:
            print(f"Warning: Could not parse {md_file}: {e}")
    return posts


def clean_markdown(content: str) -> str:
    """Remove markdown formatting for plain text posting."""
    # Remove images
    content = re.sub(r'!\[.*?\]\(.*?\)', '', content)
    # Remove links but keep text
    content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', content)
    # Remove HTML tags
    content = re.sub(r'<[^>]+>', '', content)
    # Remove markdown emphasis
    content = re.sub(r'\*\*([^*]+)\*\*', r'\1', content)
    content = re.sub(r'\*([^*]+)\*', r'\1', content)
    content = re.sub(r'__([^_]+)__', r'\1', content)
    content = re.sub(r'_([^_]+)_', r'\1', content)
    # Remove code blocks
    content = re.sub(r'```[\s\S]*?```', '', content)
    content = re.sub(r'`([^`]+)`', r'\1', content)
    # Remove headers markup
    content = re.sub(r'^#{1,6}\s+', '', content, flags=re.MULTILINE)
    # Remove blockquotes
    content = re.sub(r'^>\s*', '', content, flags=re.MULTILINE)
    # Remove horizontal rules
    content = re.sub(r'^[-*_]{3,}\s*$', '', content, flags=re.MULTILINE)
    # Collapse multiple newlines
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content.strip()


def split_into_chunks(text: str, max_length: int = 480) -> list:
    """Split text into chunks suitable for Mastodon posts.

    Tries to split at paragraph boundaries, then sentence boundaries,
    then word boundaries as a last resort.
    """
    chunks = []
    paragraphs = text.split('\n\n')
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If paragraph fits in current chunk
        if len(current_chunk) + len(para) + 2 <= max_length:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para
        # If paragraph fits in a new chunk
        elif len(para) <= max_length:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = para
        # Paragraph is too long, split by sentences
        else:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""

            sentences = re.split(r'(?<=[.!?])\s+', para)
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 1 <= max_length:
                    if current_chunk:
                        current_chunk += " " + sentence
                    else:
                        current_chunk = sentence
                elif len(sentence) <= max_length:
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = sentence
                else:
                    # Sentence too long, split by words
                    if current_chunk:
                        chunks.append(current_chunk)
                        current_chunk = ""
                    words = sentence.split()
                    for word in words:
                        if len(current_chunk) + len(word) + 1 <= max_length:
                            if current_chunk:
                                current_chunk += " " + word
                            else:
                                current_chunk = word
                        else:
                            if current_chunk:
                                chunks.append(current_chunk)
                            current_chunk = word

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def post_to_mastodon(instance_url: str, access_token: str, status: str,
                     reply_to_id: str = None, visibility: str = "public") -> dict:
    """Post a status to Mastodon."""
    url = f"{instance_url.rstrip('/')}/api/v1/statuses"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    data = {
        "status": status,
        "visibility": visibility
    }
    if reply_to_id:
        data["in_reply_to_id"] = reply_to_id

    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()


def post_thread(instance_url: str, access_token: str, title: str,
                blog_url: str, chunks: list, visibility: str = "public") -> list:
    """Post a thread to Mastodon. Returns list of post IDs."""
    post_ids = []

    # First post: title + link + start of content
    first_status = f"{title}\n\n{blog_url}"
    if chunks:
        first_chunk = chunks[0]
        if len(first_status) + len(first_chunk) + 4 <= 500:
            first_status += f"\n\n{first_chunk}"
            chunks = chunks[1:]

    print(f"Posting first status ({len(first_status)} chars)...")
    result = post_to_mastodon(instance_url, access_token, first_status, visibility=visibility)
    post_ids.append(result['id'])
    reply_to = result['id']

    # Remaining chunks as replies
    for i, chunk in enumerate(chunks):
        print(f"Posting chunk {i+2}/{len(chunks)+1} ({len(chunk)} chars)...")
        time.sleep(1)  # Rate limiting
        result = post_to_mastodon(instance_url, access_token, chunk,
                                   reply_to_id=reply_to, visibility=visibility)
        post_ids.append(result['id'])
        reply_to = result['id']

    return post_ids


def generate_blog_url(base_url: str, relative_path: str) -> str:
    """Generate the blog URL from the relative path."""
    # Convert content/tech/post-name/index.md to /tech/post-name/
    path = relative_path.replace('content/', '').replace('/index.md', '/').replace('.md', '/')
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def main():
    # Required environment variables
    mastodon_instance = get_env_var('MASTODON_INSTANCE')
    mastodon_token = get_env_var('MASTODON_ACCESS_TOKEN')
    blog_base_url = get_env_var('BLOG_BASE_URL')
    blog_content_dir = get_env_var('BLOG_CONTENT_DIR')

    # Optional
    tracking_file_path = os.environ.get('TRACKING_FILE', '.github/mastodon-published.json')
    visibility = os.environ.get('MASTODON_VISIBILITY', 'public')
    dry_run = os.environ.get('DRY_RUN', 'false').lower() == 'true'

    content_dir = Path(blog_content_dir)
    tracking_file = Path(blog_content_dir).parent / tracking_file_path

    if not content_dir.exists():
        print(f"Error: Content directory {content_dir} does not exist")
        sys.exit(1)

    # Load already published posts
    published = load_published_posts(tracking_file)
    print(f"Found {len(published)} previously published posts")

    # Find posts marked for Mastodon
    posts = find_mastodon_posts(content_dir)
    print(f"Found {len(posts)} posts marked for Mastodon")

    # Filter to only new posts
    new_posts = [p for p in posts if p['relative_path'] not in published]
    print(f"Found {len(new_posts)} new posts to publish")

    if not new_posts:
        print("No new posts to publish")
        set_github_output('posts_published', '0')
        return

    for post in new_posts:
        print(f"\nProcessing: {post['title']}")

        # Clean and split content
        clean_content = clean_markdown(post['content'])
        chunks = split_into_chunks(clean_content)
        blog_url = generate_blog_url(blog_base_url, post['relative_path'])

        print(f"  URL: {blog_url}")
        print(f"  Content length: {len(clean_content)} chars")
        print(f"  Split into {len(chunks)} chunks")

        if dry_run:
            print("  [DRY RUN] Would post thread:")
            print(f"    First: {post['title']}\\n{blog_url}")
            for i, chunk in enumerate(chunks):
                print(f"    Chunk {i+1}: {chunk[:50]}...")
        else:
            try:
                post_ids = post_thread(
                    mastodon_instance,
                    mastodon_token,
                    post['title'],
                    blog_url,
                    chunks,
                    visibility
                )
                print(f"  Posted thread with {len(post_ids)} posts")

                # Mark as published
                published.add(post['relative_path'])
                save_published_posts(tracking_file, published)
                print(f"  Marked as published")

            except requests.exceptions.HTTPError as e:
                print(f"  Error posting: {e}")
                print(f"  Response: {e.response.text if e.response else 'No response'}")
                sys.exit(1)

    print(f"\nDone! Published {len(new_posts)} new posts")
    set_github_output('posts_published', str(len(new_posts)))


if __name__ == '__main__':
    main()
