"""
js_scripts.py – JavaScript snippets injected into captured pages via Playwright.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# CAPTURE_FRAME_JS
# ---------------------------------------------------------------------------
# Evaluates inside the page.  Returns a base-64 JPEG string from the first
# <video> element, or throws an Error if the video is not ready or if
# MediaMTX reports that the stream is absent.
CAPTURE_FRAME_JS = """
() => {
    // Detect MediaMTX "stream not found" messages in the page body.
    // Both the full MediaMTX string and any substring match are handled.
    const bodyText = document.body ? document.body.innerText : '';
    if (bodyText.includes('Error: stream not found, retrying in some seconds')) {
        throw new Error('stream not found, retrying in some seconds');
    }
    if (bodyText.includes('stream not found')) {
        throw new Error('stream not found, retrying in some seconds');
    }

    const video = document.querySelector('video');
    if (!video) {
        throw new Error('no video element found');
    }
    if (video.readyState < 2) {
        throw new Error('video not ready (readyState=' + video.readyState + ')');
    }
    if (video.videoWidth === 0 || video.videoHeight === 0) {
        throw new Error('video has zero dimensions');
    }

    const canvas = document.createElement('canvas');
    canvas.width  = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.85).split(',')[1];
}
"""

# ---------------------------------------------------------------------------
# AUTOPLAY_JS
# ---------------------------------------------------------------------------
# Injected once after page load to unmute and play the video element so the
# browser does not block auto-play.
AUTOPLAY_JS = """
() => {
    const video = document.querySelector('video');
    if (video) {
        video.muted = true;
        video.play().catch(() => {});
    }
}
"""
