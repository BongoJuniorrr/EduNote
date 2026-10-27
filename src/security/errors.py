"""Actionable public errors without exception strings, stack traces, paths or keys."""

def public_error(error: Exception) -> str:
    message = str(error).lower()
    if '524' in message or 'cloudflare' in message:
        return 'Provider proxy timed out (HTTP 524). EduNote allows 300 seconds, but the upstream proxy has a separate limit. Use a reachable direct/local inference URL or adjust the provider proxy.'
    if '429' in message or 'quota' in message or 'rate limit' in message:
        return 'Provider rate limit or quota exceeded (HTTP 429). Wait for the provider window or choose another configured model.'
    if '401' in message or 'authentication' in message or 'unauthorized' in message:
        return 'Provider authentication failed (HTTP 401). Check the API key in Settings.'
    if '403' in message or 'forbidden' in message:
        return 'Provider denied access (HTTP 403). Check model permissions and endpoint configuration.'
    if '404' in message:
        return 'Provider endpoint or model was not found (HTTP 404). Check the base URL and model name.'
    if isinstance(error, TimeoutError) or 'timed out' in message or 'timeout' in message:
        return 'Request timed out. Model connection tests allow 300 seconds; check loading and server capacity.'
    if 'no answer text' in message:
        return 'The endpoint returned no answer text. Check model output and reasoning/token budget.'
    if 'outside' in message or 'escapes' in message or 'resource identifier' in message:
        return 'Invalid resource path.'
    return 'Operation failed. Check the local server logs for details.'
