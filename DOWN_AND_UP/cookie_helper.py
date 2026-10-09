"""Fast, shared cookie selection for format extraction and downloads.

Existing cookie files are reused immediately. Remote cookie sources are consulted
only when a YouTube cookie file is missing; newly fetched files are validated
before being saved. Download errors can still trigger the project's existing
cookie-retry flow.
"""
import os

from HELPERS.logger import logger
from URL_PARSERS.nocookie import is_no_cookie_domain
from URL_PARSERS.youtube import is_youtube_url


def _usable_file(path):
    try:
        return bool(path and os.path.isfile(path) and os.path.getsize(path) > 0)
    except OSError:
        return False


def get_cookie_file_for_url(url, user_id, download_dir=None):
    """Return the best available cookie file, without revalidating it per URL."""
    if user_id is None or is_no_cookie_domain(url):
        return None

    user_dir = os.path.join("users", str(user_id))
    user_cookie_path = os.path.join(user_dir, "cookie.txt")

    # A task-specific cookie takes precedence, then the user's saved cookie.
    for path in (
        os.path.join(download_dir, "cookie.txt") if download_dir else None,
        user_cookie_path,
    ):
        if _usable_file(path):
            logger.info("[COOKIES] Reusing local cookie file")
            return path

    if not is_youtube_url(url):
        # Preserve the existing successful-cookie cache for non-YouTube sites.
        try:
            from COMMANDS.cookies_cmd import get_cookie_cache_result
            cached = get_cookie_cache_result(user_id, url)
            cached_path = cached.get("cookie_path") if cached and cached.get("result") else None
            if _usable_file(cached_path):
                logger.info("[COOKIES] Reusing cached site cookie")
                return cached_path
        except Exception as exc:
            logger.debug("[COOKIES] Non-YouTube cookie cache lookup failed: %s", exc)
        return None

    # No local YouTube cookies: try configured sources once, validating each
    # downloaded file before replacing the user's saved cookie file.
    try:
        from COMMANDS.cookies_cmd import (
            get_youtube_cookie_urls,
            _download_content,
            test_youtube_cookies_on_url,
        )
        cookie_urls = get_youtube_cookie_urls()
    except Exception as exc:
        logger.warning("[COOKIES] Could not load YouTube cookie sources: %s", exc)
        return None

    if not cookie_urls:
        logger.info("[COOKIES] No configured YouTube cookie sources")
        return None

    os.makedirs(user_dir, exist_ok=True)
    temp_path = user_cookie_path + ".download.tmp"

    for index, cookie_url in enumerate(cookie_urls, start=1):
        try:
            ok, _status, data, _error = _download_content(
                cookie_url, timeout=30, user_id=user_id
            )
            if not ok or not data or len(data) > 100 * 1024:
                continue

            with open(temp_path, "wb") as cookie_file:
                cookie_file.write(data)

            if test_youtube_cookies_on_url(temp_path, url, user_id):
                os.replace(temp_path, user_cookie_path)
                logger.info("[COOKIES] Valid YouTube cookies acquired from source %s", index)
                return user_cookie_path

            logger.warning("[COOKIES] Configured YouTube cookie source %s was invalid", index)
        except Exception as exc:
            logger.warning("[COOKIES] Cookie source %s failed: %s", index, exc)
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass

    logger.warning("[COOKIES] No valid YouTube cookie source was available")
    return None
