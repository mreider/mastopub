#!/usr/bin/env python3
"""
Post Hugo blog content to Mastodon as a thread.
Reads markdown files, extracts content, splits into chunks, and posts as a thread.
Supports featured images and inline images.
"""

import os
import sys
import json
import re
import time
import requests
import frontmatter
from pathlib import Path
from urllib.parse import urljoin


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
                    'image': post.get('image', ''),  # Featured image
                    'mastodon_text': post.get('mastodon_text', ''),  # Custom toot text
                    'mastodon_thread': post.get('mastodon_thread', False),  # Full thread mode
                    'metadata': post.metadata
                })
        except Exception as e:
            print(f"Warning: Could not parse {md_file}: {e}")
    return posts


def extract_images_from_markdown(content: str) -> list:
    """Extract image URLs from markdown content in order of appearance.

    Returns list of dicts with 'url' and 'position' (character position in content).
    """
    images = []
    # Match ![alt](url) pattern
    for match in re.finditer(r'!\[.*?\]\(([^)]+)\)', content):
        images.append({
            'url': match.group(1),
            'position': match.start()
        })
    return images


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


def split_into_chunks_with_images(content: str, images: list, max_length: int = 480) -> list:
    """Split text into chunks and track which images belong to each chunk.

    Returns list of dicts with 'text' and 'images' (list of image URLs).
    """
    # First, figure out which paragraph each image belongs to
    paragraphs = content.split('\n\n')

    # Calculate character positions of each paragraph start
    para_positions = []
    pos = 0
    for para in paragraphs:
        para_positions.append(pos)
        pos += len(para) + 2  # +2 for \n\n

    # Assign images to paragraphs based on position
    para_images = [[] for _ in paragraphs]
    for img in images:
        # Find which paragraph this image belongs to
        for i in range(len(para_positions) - 1, -1, -1):
            if img['position'] >= para_positions[i]:
                para_images[i].append(img['url'])
                break

    # Now split into chunks, carrying images along
    chunks = []
    current_chunk = ""
    current_images = []

    for i, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            continue

        # If paragraph fits in current chunk
        if len(current_chunk) + len(para) + 2 <= max_length:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para
            current_images.extend(para_images[i])
        # If paragraph fits in a new chunk
        elif len(para) <= max_length:
            if current_chunk:
                chunks.append({'text': current_chunk, 'images': current_images})
            current_chunk = para
            current_images = list(para_images[i])
        # Paragraph is too long, need to split it
        else:
            if current_chunk:
                chunks.append({'text': current_chunk, 'images': current_images})
                current_chunk = ""
                current_images = []

            # Images for this para go with first chunk of the split
            first_chunk_of_para = True

            sentences = re.split(r'(?<=[.!?])\s+', para)
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 1 <= max_length:
                    if current_chunk:
                        current_chunk += " " + sentence
                    else:
                        current_chunk = sentence
                        if first_chunk_of_para:
                            current_images = list(para_images[i])
                            first_chunk_of_para = False
                elif len(sentence) <= max_length:
                    if current_chunk:
                        chunks.append({'text': current_chunk, 'images': current_images})
                    current_chunk = sentence
                    if first_chunk_of_para:
                        current_images = list(para_images[i])
                        first_chunk_of_para = False
                    else:
                        current_images = []
                else:
                    # Sentence too long, split by words
                    if current_chunk:
                        chunks.append({'text': current_chunk, 'images': current_images})
                        current_chunk = ""
                        current_images = [] if not first_chunk_of_para else list(para_images[i])
                        first_chunk_of_para = False

                    words = sentence.split()
                    for word in words:
                        if len(current_chunk) + len(word) + 1 <= max_length:
                            if current_chunk:
                                current_chunk += " " + word
                            else:
                                current_chunk = word
                        else:
                            if current_chunk:
                                chunks.append({'text': current_chunk, 'images': current_images})
                            current_chunk = word
                            current_images = []

    if current_chunk:
        chunks.append({'text': current_chunk, 'images': current_images})

    return chunks


def resolve_image_url(image_path: str, blog_base_url: str) -> str:
    """Convert a relative image path to a full URL."""
    if image_path.startswith('http://') or image_path.startswith('https://'):
        return image_path
    # Handle paths like /images/matt/photo.jpg
    return urljoin(blog_base_url.rstrip('/') + '/', image_path.lstrip('/'))


def upload_image_to_mastodon(instance_url: str, access_token: str, image_url: str) -> str:
    """Download an image and upload it to Mastodon. Returns media_id or None."""
    try:
        # Download the image
        print(f"    Downloading image: {image_url}")
        img_response = requests.get(image_url, timeout=30)
        img_response.raise_for_status()

        # Determine content type
        content_type = img_response.headers.get('Content-Type', 'image/jpeg')

        # Get filename from URL
        filename = image_url.split('/')[-1].split('?')[0]
        if not filename:
            filename = 'image.jpg'

        # Upload to Mastodon
        print(f"    Uploading to Mastodon: {filename}")
        upload_url = f"{instance_url.rstrip('/')}/api/v2/media"
        headers = {"Authorization": f"Bearer {access_token}"}
        files = {
            'file': (filename, img_response.content, content_type)
        }

        response = requests.post(upload_url, headers=headers, files=files)
        response.raise_for_status()

        result = response.json()
        media_id = result.get('id')
        print(f"    Uploaded successfully: media_id={media_id}")
        return media_id

    except Exception as e:
        print(f"    Warning: Failed to upload image {image_url}: {e}")
        return None


def post_to_mastodon(instance_url: str, access_token: str, status: str,
                     reply_to_id: str = None, media_ids: list = None,
                     visibility: str = "public") -> dict:
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
    if media_ids:
        data["media_ids"] = media_ids

    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()


def post_single(instance_url: str, access_token: str, title: str,
                blog_url: str, custom_text: str = None, featured_image_id: str = None,
                visibility: str = "public", dry_run: bool = False) -> list:
    """Post a single status to Mastodon (not a thread). Returns list with one post ID."""
    # Build the status text
    if custom_text:
        status = f"{custom_text}\n\n{blog_url}"
    else:
        status = f"My latest post: {title}\n\n{blog_url}"

    media_ids = [featured_image_id] if featured_image_id else None

    if dry_run:
        print(f"  [DRY RUN] Would post single status ({len(status)} chars)")
        print(f"    Text: {status[:100]}...")
        print(f"    With {1 if featured_image_id else 0} images")
        return ["dry-run-id"]
    else:
        print(f"Posting single status ({len(status)} chars) with {1 if featured_image_id else 0} images...")
        result = post_to_mastodon(instance_url, access_token, status,
                                   media_ids=media_ids, visibility=visibility)
        return [result['id']]


def post_thread(instance_url: str, access_token: str, title: str,
                blog_url: str, chunks: list, featured_image_id: str = None,
                blog_base_url: str = None, visibility: str = "public",
                dry_run: bool = False) -> list:
    """Post a thread to Mastodon. Returns list of post IDs."""
    post_ids = []

    # First post: title + link + start of content
    first_status = f"{title}\n\n{blog_url}"
    first_media_ids = []

    if featured_image_id:
        first_media_ids.append(featured_image_id)

    if chunks:
        first_chunk = chunks[0]
        if len(first_status) + len(first_chunk['text']) + 4 <= 500:
            first_status += f"\n\n{first_chunk['text']}"
            # Upload body images for first chunk (up to 4 total with featured)
            if not dry_run and blog_base_url:
                for img_url in first_chunk['images'][:4 - len(first_media_ids)]:
                    full_url = resolve_image_url(img_url, blog_base_url)
                    media_id = upload_image_to_mastodon(instance_url, access_token, full_url)
                    if media_id:
                        first_media_ids.append(media_id)
            chunks = chunks[1:]

    if dry_run:
        print(f"  [DRY RUN] Would post first status ({len(first_status)} chars)")
        print(f"    With {len(first_media_ids)} images")
        post_ids.append("dry-run-id")
        reply_to = "dry-run-id"
    else:
        print(f"Posting first status ({len(first_status)} chars) with {len(first_media_ids)} images...")
        result = post_to_mastodon(instance_url, access_token, first_status,
                                   media_ids=first_media_ids if first_media_ids else None,
                                   visibility=visibility)
        post_ids.append(result['id'])
        reply_to = result['id']

    # Remaining chunks as replies
    for i, chunk in enumerate(chunks):
        chunk_media_ids = []

        # Upload images for this chunk (max 4)
        if not dry_run and blog_base_url:
            for img_url in chunk['images'][:4]:
                full_url = resolve_image_url(img_url, blog_base_url)
                media_id = upload_image_to_mastodon(instance_url, access_token, full_url)
                if media_id:
                    chunk_media_ids.append(media_id)

        if dry_run:
            print(f"  [DRY RUN] Would post chunk {i+2} ({len(chunk['text'])} chars)")
            print(f"    With {len(chunk['images'])} images: {chunk['images']}")
            post_ids.append(f"dry-run-id-{i+2}")
        else:
            print(f"Posting chunk {i+2}/{len(chunks)+1} ({len(chunk['text'])} chars) with {len(chunk_media_ids)} images...")
            time.sleep(1)  # Rate limiting
            result = post_to_mastodon(instance_url, access_token, chunk['text'],
                                       reply_to_id=reply_to,
                                       media_ids=chunk_media_ids if chunk_media_ids else None,
                                       visibility=visibility)
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

        blog_url = generate_blog_url(blog_base_url, post['relative_path'])
        print(f"  URL: {blog_url}")

        # Determine posting mode
        use_thread_mode = post['mastodon_thread']
        custom_text = post['mastodon_text']

        if use_thread_mode:
            print("  Mode: Full thread")
        elif custom_text:
            print(f"  Mode: Single post with custom text")
        else:
            print("  Mode: Single post (default)")

        # Handle featured image
        featured_image_id = None
        if post['image'] and not dry_run:
            print(f"  Featured image: {post['image']}")
            full_image_url = resolve_image_url(post['image'], blog_base_url)
            featured_image_id = upload_image_to_mastodon(mastodon_instance, mastodon_token, full_image_url)
        elif post['image']:
            print(f"  Featured image: {post['image']} (would upload)")

        if use_thread_mode:
            # Full thread mode: post entire content as a thread
            body_images = extract_images_from_markdown(post['content'])
            print(f"  Found {len(body_images)} images in body")

            clean_content = clean_markdown(post['content'])
            chunks = split_into_chunks_with_images(clean_content, body_images)

            print(f"  Content length: {len(clean_content)} chars")
            print(f"  Split into {len(chunks)} chunks")

            if dry_run:
                print("  [DRY RUN] Would post thread:")
                post_ids = post_thread(
                    mastodon_instance,
                    mastodon_token,
                    post['title'],
                    blog_url,
                    chunks,
                    featured_image_id=featured_image_id,
                    blog_base_url=blog_base_url,
                    visibility=visibility,
                    dry_run=True
                )
            else:
                try:
                    post_ids = post_thread(
                        mastodon_instance,
                        mastodon_token,
                        post['title'],
                        blog_url,
                        chunks,
                        featured_image_id=featured_image_id,
                        blog_base_url=blog_base_url,
                        visibility=visibility,
                        dry_run=False
                    )
                    print(f"  Posted thread with {len(post_ids)} posts")
                except requests.exceptions.HTTPError as e:
                    print(f"  Error posting: {e}")
                    print(f"  Response: {e.response.text if e.response else 'No response'}")
                    sys.exit(1)
        else:
            # Single post mode: just the custom text (or default) + link + image
            if dry_run:
                post_ids = post_single(
                    mastodon_instance,
                    mastodon_token,
                    post['title'],
                    blog_url,
                    custom_text=custom_text,
                    featured_image_id=featured_image_id,
                    visibility=visibility,
                    dry_run=True
                )
            else:
                try:
                    post_ids = post_single(
                        mastodon_instance,
                        mastodon_token,
                        post['title'],
                        blog_url,
                        custom_text=custom_text,
                        featured_image_id=featured_image_id,
                        visibility=visibility,
                        dry_run=False
                    )
                    print(f"  Posted single status")
                except requests.exceptions.HTTPError as e:
                    print(f"  Error posting: {e}")
                    print(f"  Response: {e.response.text if e.response else 'No response'}")
                    sys.exit(1)

        # Mark as published
        if not dry_run:
            published.add(post['relative_path'])
            save_published_posts(tracking_file, published)
            print(f"  Marked as published")

    print(f"\nDone! Published {len(new_posts)} new posts")
    set_github_output('posts_published', str(len(new_posts)))


if __name__ == '__main__':
    main()
