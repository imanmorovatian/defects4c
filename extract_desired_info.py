import json
import os
from pathlib import Path
import re
import time
import requests
from tqdm import tqdm
from collections import Counter


DEFECTS4C_BASE_URL = 'http://127.0.0.1:11111'
BUG_HUNK_RE = re.compile(r"// buggy hunk\s*\n(.*?)(?:\n{2,}|\Z)", re.DOTALL)


def load_local_env(env_path: str = '.env') -> None:
    """
    Load simple KEY=VALUE pairs from a local `.env` file into `os.environ`.

    Existing environment variables are preserved so shell-provided values still
    take precedence over the `.env` file.
    """
    path = Path(env_path)
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue

        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_local_env()


def extract_bug(text: str) -> str:
    """
    Extract bug from the `text` using Regex. The bug is preceded by `// buggy hunk`
    and is followed by a few `\n`
    """
    match = BUG_HUNK_RE.search(text)
    return match.group(1).strip() if match else ""


def extract_error(text: str) -> str:
    """
    Extract error from the `text` using Regex. The error is preceded by `with the following test error`
    and is expanded until the end of the `text`
    """
    marker = "with the following test error:"
    start = text.find(marker)
    return text[start + len(marker):].strip() if start != -1 else ""


GITHUB_TOKEN = os.getenv('GITHUB_TOKEN') or os.getenv('GH_TOKEN')

github_session = requests.Session()
github_session.headers.update({
    'Accept': 'application/vnd.github+json',
    'User-Agent': 'defects4c-extract-desired-info',
    'X-GitHub-Api-Version': '2022-11-28',
})
if GITHUB_TOKEN:
    github_session.headers['Authorization'] = f'Bearer {GITHUB_TOKEN}'

commit_message_cache: dict[str, str] = {}

def extract_commit(url: str) -> str:
    """
    Fetch the commit payload from GitHub and return `commit.message`.

    Unauthenticated GitHub requests are heavily rate-limited, so this function
    uses `GITHUB_TOKEN` or `GH_TOKEN` automatically when available.
    """
    if url in commit_message_cache:
        return commit_message_cache[url]

    for attempt in range(3):
        response = github_session.get(url, timeout=30)

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if response.ok:
            message = payload.get('commit', {}).get('message', '')
            commit_message_cache[url] = message
            return message

        error_message = payload.get('message', response.text)
        is_limited = (
            response.status_code in (403, 429)
            and (
                'rate limit' in error_message.lower()
                or 'abuse detection' in error_message.lower()
            )
        )
        if not is_limited:
            raise requests.HTTPError(
                f'GitHub API request failed for {url}: '
                f'{response.status_code} {error_message}'
            )

        retry_after = response.headers.get('Retry-After')
        reset_at = response.headers.get('X-RateLimit-Reset')
        if retry_after is not None:
            wait_seconds = int(retry_after)
        elif reset_at is not None:
            wait_seconds = max(0, int(reset_at) - int(time.time()))
        else:
            wait_seconds = 60

        if not GITHUB_TOKEN:
            raise RuntimeError(
                'GitHub API rate limit reached. Set GITHUB_TOKEN or GH_TOKEN '
                'to make authenticated requests with a higher rate limit.'
            )

        if attempt == 2:
            raise RuntimeError(
                f'GitHub API kept throttling authenticated requests for {url}. '
                f'Last error: {error_message}'
            )

        time.sleep(min(wait_seconds, 300))

    return ''


def inject_bug(code: str, bug: str) -> str:
    """
    In the `code`, there is a place holder: `>>> [ INFILL ] <<<`. The function replace the place holer
    with the `bug`
    """
    return code.replace('>>> [ INFILL ] <<<', bug, 1)


def extract_line_number(code: str) -> int:
    """
    In the `code`, there is a place holder: `>>> [ INFILL ] <<<`. The function compute the line number of
    the place holder
    """
    marker = '>>> [ INFILL ] <<<'
    index = code.find(marker)
    return code.count('\n', 0, index) + 1 if index != -1 else -1


list_response = requests.get(f'{DEFECTS4C_BASE_URL}/list_defects_bugid')
defects_data = list_response.json()

if defects_data.get('status') != 'success':
    print(f'Error getting defects list: {defects_data}')
else:
    print(f'The number of defects is {len(defects_data["defects"])}')

result = []

for defect in tqdm(defects_data['defects']):
    response = requests.get(f"{DEFECTS4C_BASE_URL}/get_defect/{defect}")
    defect_data = response.json()

    d = {}

    d['defect_id'] = defect_data['defect_id']
    d['bug_id'] = defect_data['bug_id']

    d['code_without_bug'] = defect_data['prompt_data']['prompt_processed']

    prompts = defect_data['prompt_data']['prompt']
    raw_prompt = prompts[1]['content']

    d['bug'] = extract_bug(raw_prompt)

    d['error'] = extract_error(raw_prompt)
    
    url = defect_data['additional_info']['guidance']['api_url']
    d['commit_message'] = extract_commit(url)

    d['code_with_bug'] = inject_bug(d['code_without_bug'], d['bug'])
    
    d['bug_line_number'] = extract_line_number(d['code_without_bug'])


    result.append(d)


with open('result.json', 'w', encoding='utf-8') as f:
    json.dump(result, f)

empty_values = {"", None}
empty_field_counts = Counter()

for obj in result:
    for field, value in obj.items():
        if value in empty_values or (hasattr(value, '__len__') and not value and value != 0):
            empty_field_counts[field] += 1

for field in result[0]:
    print(f'{field}: {empty_field_counts[field]} empty objects')

print('The result was saved in result.json')
